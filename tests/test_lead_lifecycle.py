"""Ciclo de vida del lead: estados, cierre, permisos, capacidad y overflow."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.assignment.service import (
    advisor_available_capacity,
    retry_assignment,
    run_assignment,
)
from app.auth import get_session as auth_get_session
from app.auth import hash_password
from app.dashboard import get_session
from app.db import Base
from app.lead_status import (
    ALL_STATUSES,
    CLOSE_REASONS,
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    LeadTransitionError,
    is_lead_open,
    is_lead_terminal,
    update_lead_status,
)
from app.main import app
from app.models import (
    Advisor,
    Assignment,
    Company,
    Conversation,
    Lead,
    LeadScore,
    PointOfSale,
    User,
)

DAY = date(2026, 9, 14)
DAY2 = date(2026, 9, 15)


# --- Estados (definición central única) ------------------------------------


def test_estados_abiertos_reconocidos():
    for status in OPEN_STATUSES:
        assert is_lead_open(status)
        assert not is_lead_terminal(status)


def test_estados_terminales_reconocidos():
    for status in TERMINAL_STATUSES:
        assert is_lead_terminal(status)
        assert not is_lead_open(status)


def test_descartado_sigue_siendo_terminal():
    assert is_lead_terminal("Descartado")


def test_no_hay_listas_duplicadas_de_estados():
    assert set(OPEN_STATUSES).isdisjoint(TERMINAL_STATUSES)
    assert set(ALL_STATUSES) == set(OPEN_STATUSES) | set(TERMINAL_STATUSES)
    assert "Cerrado" in TERMINAL_STATUSES and "Perdido" in TERMINAL_STATUSES
    assert len(CLOSE_REASONS) == len(set(CLOSE_REASONS)) > 0


# --- Fixtures de DB ---------------------------------------------------------


@pytest.fixture()
def maker(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'lifecycle.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(Company(company_id="EMP-01", name="E1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"))
        session.commit()
    yield session_factory
    engine.dispose()


def _add_lead(session, lead_id, status="Contactado", company="EMP-01", pos="PV-001"):
    session.add(Lead(lead_id=lead_id, company_id=company, point_of_sale_id=pos,
                     status=status, raw_payload={"lead_id": lead_id}, record_hash="h"))


def _add_score(session, lead_id, queue=50.0):
    session.add(LeadScore(lead_id=lead_id, score_version="v1", priority_score=queue,
                          urgency_score=10.0, queue_score=queue, band="Media",
                          is_current=True))


def _add_advisor(session, advisor_id, capacity=5, active=True):
    session.add(Advisor(advisor_id=advisor_id, company_id="EMP-01", point_of_sale_id="PV-001",
                        name=advisor_id, daily_capacity=capacity, active=active))


# --- Cierre (transición) ----------------------------------------------------


def test_cerrar_lead_cambia_estado_y_registra_cierre(maker):
    with maker() as session:
        _add_lead(session, "LD-01")
        session.commit()
        lead = session.get(Lead, "LD-01")
        update_lead_status(session, lead, "Cerrado", close_reason="Venta realizada")
        lead = session.get(Lead, "LD-01")
        assert lead.status == "Cerrado"
        assert lead.closed_at is not None
        assert lead.close_reason == "Venta realizada"


def test_cerrar_no_elimina_datos_relacionados(maker):
    with maker() as session:
        _add_lead(session, "LD-01")
        _add_score(session, "LD-01")
        _add_advisor(session, "AS-01")
        session.add(Conversation(conversation_id="CV-01", lead_id="LD-01",
                                 company_id="EMP-01", status="linked", messages=[]))
        session.commit()
        run_assignment(session, DAY)
        assignment_rows = session.scalar(sa.select(sa.func.count()).select_from(Assignment))
        score_rows = session.scalar(sa.select(sa.func.count()).select_from(LeadScore))
        conv_rows = session.scalar(sa.select(sa.func.count()).select_from(Conversation))

        update_lead_status(session, session.get(Lead, "LD-01"), "Perdido",
                           close_reason="No interesado")

        assert session.get(Lead, "LD-01") is not None
        assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == assignment_rows
        assert session.scalar(sa.select(sa.func.count()).select_from(LeadScore)) == score_rows
        assert session.scalar(sa.select(sa.func.count()).select_from(Conversation)) == conv_rows


def test_no_se_permite_reabrir_lead_terminal(maker):
    with maker() as session:
        _add_lead(session, "LD-01", status="Descartado")
        session.commit()
        with pytest.raises(LeadTransitionError):
            update_lead_status(session, session.get(Lead, "LD-01"), "Contactado")


def test_estado_desconocido_es_rechazado(maker):
    with maker() as session:
        _add_lead(session, "LD-01")
        session.commit()
        with pytest.raises(LeadTransitionError):
            update_lead_status(session, session.get(Lead, "LD-01"), "Inventado")


# --- Capacidad basada en leads abiertos ------------------------------------


def test_capacidad_descuenta_solo_leads_abiertos(maker):
    with maker() as session:
        _add_advisor(session, "AS-01", capacity=2)
        for lead_id in ("LD-01", "LD-02"):
            _add_lead(session, lead_id)
            _add_score(session, lead_id)
        session.commit()
        run_assignment(session, DAY)
        advisor = session.get(Advisor, "AS-01")
        assert advisor_available_capacity(session, advisor) == 0

        update_lead_status(session, session.get(Lead, "LD-01"), "Cerrado",
                           close_reason="Venta realizada")
        assert advisor_available_capacity(session, advisor) == 1


def test_capacidad_liberada_si_todos_terminales(maker):
    with maker() as session:
        _add_advisor(session, "AS-01", capacity=2)
        for lead_id in ("LD-01", "LD-02"):
            _add_lead(session, lead_id)
            _add_score(session, lead_id)
        session.commit()
        run_assignment(session, DAY)
        advisor = session.get(Advisor, "AS-01")
        update_lead_status(session, session.get(Lead, "LD-01"), "Cerrado", close_reason="Otro")
        update_lead_status(session, session.get(Lead, "LD-02"), "Perdido", close_reason="No interesado")
        assert advisor_available_capacity(session, advisor) == 2


# --- Overflow y promoción ---------------------------------------------------


def test_cerrar_libera_cupo_y_promueve_overflow(maker):
    with maker() as session:
        _add_advisor(session, "AS-01", capacity=1)
        _add_lead(session, "LD-A")
        _add_lead(session, "LD-B")
        _add_score(session, "LD-A", queue=90.0)
        _add_score(session, "LD-B", queue=80.0)
        session.commit()

        run_assignment(session, DAY)
        current = {
            row.lead_id: row
            for row in session.scalars(
                sa.select(Assignment).where(Assignment.is_current.is_(True))
            ).all()
        }
        assert current["LD-A"].status == "assigned"
        assert current["LD-B"].status == "overflow"

        update_lead_status(session, session.get(Lead, "LD-A"), "Cerrado",
                           close_reason="Venta realizada")
        retry_assignment(session, DAY)

        current = {
            row.lead_id: row
            for row in session.scalars(
                sa.select(Assignment).where(Assignment.is_current.is_(True))
            ).all()
        }
        # Cada lead tiene exactamente una asignación vigente (por lead, la última fecha).
        assert session.get(Lead, "LD-A") is not None  # no se borra
        assert current["LD-B"].status == "assigned"
        assert current["LD-B"].advisor_id == "AS-01"


# --- Continuidad ------------------------------------------------------------


def test_lead_abierto_conserva_asesor_en_nueva_corrida(maker):
    with maker() as session:
        _add_advisor(session, "AS-01", capacity=1)
        _add_advisor(session, "AS-02", capacity=10)
        _add_lead(session, "LD-01")
        _add_score(session, "LD-01", queue=50.0)
        session.commit()

        run_assignment(session, DAY)
        first = session.scalar(
            sa.select(Assignment).where(Assignment.is_current.is_(True))
        )
        original_advisor = first.advisor_id
        assert original_advisor in {"AS-01", "AS-02"}

        run_assignment(session, DAY2)
        # La vigente por lead es la del run_date más reciente.
        latest = session.scalar(
            sa.select(Assignment)
            .where(Assignment.lead_id == "LD-01", Assignment.is_current.is_(True))
            .order_by(Assignment.run_date.desc(), Assignment.assignment_id.desc())
        )
        assert latest.advisor_id == original_advisor  # continuidad, no reasigna por capacidad


# --- Exclusión de terminales ------------------------------------------------


def test_lead_terminal_no_se_asigna(maker):
    with maker() as session:
        _add_advisor(session, "AS-01", capacity=5)
        _add_lead(session, "LD-01", status="Cerrado")
        _add_score(session, "LD-01", queue=99.0)
        session.commit()
        report = run_assignment(session, DAY)
        assert report["candidates"] == 0
        assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == 0


# --- Permisos del endpoint --------------------------------------------------

PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture()
def client(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'lifecycle_api.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Uno", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Nueve", daily_capacity=5, active=True),
        ])
        session.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup1@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id=None, advisor_id=None, email="admin@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        session.add_all([
            Lead(lead_id="L1", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Propio", status="Contactado", raw_payload={}, record_hash="a"),
            Lead(lead_id="L2", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Ajeno", status="Contactado", raw_payload={}, record_hash="b"),
            Lead(lead_id="L9", company_id="EMP-02", point_of_sale_id="PV-006",
                 customer_name="OtraEmpresa", status="Contactado", raw_payload={}, record_hash="c"),
        ])
        session.add(
            Assignment(lead_id="L1", advisor_id="AS-001", company_id="EMP-01",
                       point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True)
        )
        session.commit()

    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def _login(client, email):
    response = client.post("/login", data={"email": email, "password": PASSWORD})
    assert response.status_code in (200, 303)
    return client


def _status(session_factory, lead_id):
    with session_factory() as session:
        return session.get(Lead, lead_id).status


def test_advisor_cierra_lead_propio(client):
    http, maker = client
    _login(http, "adv@x")
    response = http.post("/leads/L1/status",
                         data={"status": "Cerrado", "close_reason": "Venta realizada"})
    assert response.status_code == 200
    assert _status(maker, "L1") == "Cerrado"


def test_advisor_no_puede_cerrar_lead_ajeno(client):
    http, maker = client
    _login(http, "adv@x")
    response = http.post("/leads/L2/status",
                         data={"status": "Cerrado", "close_reason": "Venta realizada"})
    assert response.status_code == 403
    assert _status(maker, "L2") == "Contactado"


def test_supervisor_respeta_empresa(client):
    http, maker = client
    _login(http, "sup1@x")
    assert http.post("/leads/L1/status",
                     data={"status": "En proceso"}).status_code == 200
    assert _status(maker, "L1") == "En proceso"
    # Otra empresa → no encontrado.
    assert http.post("/leads/L9/status",
                     data={"status": "En proceso"}).status_code == 404


def test_admin_opera_global(client):
    http, maker = client
    _login(http, "admin@x")
    assert http.post("/leads/L9/status",
                     data={"status": "Perdido", "close_reason": "No interesado"}).status_code == 200
    assert _status(maker, "L9") == "Perdido"


def test_reabrir_terminal_por_endpoint_es_400(client):
    http, maker = client
    _login(http, "admin@x")
    http.post("/leads/L1/status", data={"status": "Cerrado", "close_reason": "Otro"})
    response = http.post("/leads/L1/status", data={"status": "Contactado"})
    assert response.status_code == 400
    assert _status(maker, "L1") == "Cerrado"
