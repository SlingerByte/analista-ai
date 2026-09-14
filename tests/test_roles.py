from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import hash_password
from app.auth import get_session as auth_get_session
from app.dashboard import get_session
from app.db import Base
from app.main import app
from app.models import (
    Advisor,
    Assignment,
    Company,
    Lead,
    LeadScore,
    PointOfSale,
    User,
)

DAY = date(2026, 9, 14)
PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


def _login(client, email):
    response = client.post("/login", data={"email": email, "password": PASSWORD})
    assert response.status_code in (200, 303), (email, response.status_code)
    return client


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "roles.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-002", company_id="EMP-01", name="P2"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Uno", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-002", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Dos", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-003", company_id="EMP-01", point_of_sale_id="PV-002",
                    name="Tres", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Nueve", daily_capacity=5, active=True),
        ])
        session.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup1@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-02", advisor_id=None, email="sup2@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id=None, advisor_id=None, email="admin@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        session.add_all([
            Lead(lead_id="L1", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Propio", status="Contactado",
                 raw_payload={}, record_hash="a"),
            Lead(lead_id="L2", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="MismoPos", status="Contactado",
                 raw_payload={}, record_hash="b"),
            Lead(lead_id="L3", company_id="EMP-01", point_of_sale_id="PV-002",
                 customer_name="OtroPos", status="Contactado",
                 raw_payload={}, record_hash="c"),
            Lead(lead_id="L9", company_id="EMP-02", point_of_sale_id="PV-006",
                 customer_name="OtraEmpresa", status="Contactado",
                 raw_payload={}, record_hash="d"),
        ])
        session.add_all([
            LeadScore(lead_id="L1", score_version="v1", priority_score=80.0,
                      urgency_score=10.0, queue_score=80.0, band="Alta", is_current=True),
            LeadScore(lead_id="L2", score_version="v1", priority_score=50.0,
                      urgency_score=10.0, queue_score=50.0, band="Media", is_current=True),
            LeadScore(lead_id="L3", score_version="v1", priority_score=60.0,
                      urgency_score=10.0, queue_score=60.0, band="Media", is_current=True),
            LeadScore(lead_id="L9", score_version="v1", priority_score=70.0,
                      urgency_score=10.0, queue_score=70.0, band="Alta", is_current=True),
        ])
        session.add_all([
            Assignment(lead_id="L1", advisor_id="AS-001", company_id="EMP-01",
                       point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
            Assignment(lead_id="L2", advisor_id="AS-002", company_id="EMP-01",
                       point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
            Assignment(lead_id="L3", advisor_id="AS-003", company_id="EMP-01",
                       point_of_sale_id="PV-002", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
            Assignment(lead_id="L9", advisor_id="AS-009", company_id="EMP-02",
                       point_of_sale_id="PV-006", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
        ])
        session.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _text(client, path, status=200):
    response = client.get(path)
    assert response.status_code == status, (path, response.status_code)
    return response.text


# ---- Advisor (AS-001) ----

def test_1_advisor_ve_sus_propios(client):
    _login(client, "adv@x")
    text = _text(client, "/")
    assert "Propio" in text
    assert "Vista asesor" in text
    # Sin selector de POS ni de empresa: el sistema ya sabe quién soy.
    assert 'name="pos"' not in text
    assert 'name="empresa"' not in text


def test_2_3_advisor_no_ve_otro_asesor_mismo_pos(client):
    _login(client, "adv@x")
    assert "MismoPos" not in _text(client, "/")


def test_4_advisor_no_ve_otro_pos(client):
    _login(client, "adv@x")
    assert "OtroPos" not in _text(client, "/")
    _text(client, "/leads/L3", status=404)


def test_4b_advisor_manipular_company_no_cambia_alcance(client):
    _login(client, "adv@x")
    text = _text(client, "/?company_id=EMP-02")
    assert "Propio" in text
    assert "OtraEmpresa" not in text
    # El backend sigue aceptando pos pero siempre dentro del alcance propio.
    assert "Sin leads" in _text(client, "/?pos=PV-002")


def test_5_advisor_no_ve_otra_empresa(client):
    _login(client, "adv@x")
    assert "OtraEmpresa" not in _text(client, "/")
    _text(client, "/leads/L9", status=404)


def test_6_advisor_no_consulta_lead_ajeno_directo(client):
    _login(client, "adv@x")
    _text(client, "/leads/L2", status=404)


def test_7_advisor_no_cambia_identidad_por_query_param(client):
    _login(client, "adv@x")
    text = _text(client, "/?advisor_id=AS-002")
    assert "Propio" in text
    assert "MismoPos" not in text


def test_advisor_supervision_es_403(client):
    _login(client, "adv@x")
    _text(client, "/supervision", status=403)


# ---- Supervisor (EMP-01) ----

def test_8_supervisor_ve_su_empresa(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision")
    for name in ("Propio", "MismoPos", "OtroPos"):
        assert name in text
    assert "Supervisión" in text
    # Sin filtro de empresa: el sistema ya sabe de qué empresa soy.
    assert 'name="empresa"' not in text
    assert "EMP-01" in text


def test_8b_supervisor_no_ve_otra_empresa(client):
    _login(client, "sup1@x")
    assert "OtraEmpresa" not in _text(client, "/supervision")


def test_9_supervisor_filtro_empresa_ajena_se_ignora(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision?empresa=EMP-02")
    assert "OtraEmpresa" not in text
    assert "Propio" in text


def test_10_supervisor_filtra_pos(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision?pos=PV-001")
    assert "Propio" in text and "MismoPos" in text
    assert "OtroPos" not in text


def test_11_supervisor_filtra_asesor(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision?asesor=AS-003")
    assert "OtroPos" in text
    assert "Propio" not in text


def test_12_supervisor_combina_empresa_pos_asesor(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision?empresa=EMP-01&pos=PV-001&asesor=AS-001")
    assert "Propio" in text
    assert "MismoPos" not in text


def test_13_supervisor_todos_sin_filtros(client):
    _login(client, "sup1@x")
    text = _text(client, "/supervision?empresa=&pos=&asesor=")
    for name in ("Propio", "MismoPos", "OtroPos"):
        assert name in text


def test_14_supervisor_detalle_permitido_y_ajeno_no(client):
    _login(client, "sup1@x")
    text = _text(client, "/leads/L1")
    assert "Propio" in text
    _text(client, "/leads/L9", status=404)


def test_supervisor_emp02_ve_su_empresa(client):
    _login(client, "sup2@x")
    text = _text(client, "/supervision")
    assert "OtraEmpresa" in text
    assert "Propio" not in text


def test_supervisor_filtra_relevancia_estado_modelo(client):
    _login(client, "sup1@x")
    assert "Propio" in _text(client, "/supervision?banda=Alta")
    assert "MismoPos" not in _text(client, "/supervision?banda=Alta")
    assert "Propio" in _text(client, "/supervision?estado=Contactado")
    assert "Propio" not in _text(client, "/supervision?estado=No+contesta")


# ---- Admin ----

def test_admin_login_entra_a_supervision(client):
    response = client.post("/login", data={"email": "admin@x", "password": PASSWORD})
    assert response.status_code in (200, 303)


def test_admin_ve_multiples_empresas(client):
    _login(client, "admin@x")
    text = _text(client, "/supervision")
    for name in ("Propio", "MismoPos", "OtroPos", "OtraEmpresa"):
        assert name in text
    assert "Supervisión global" in text
    assert 'name="empresa"' in text
    assert 'name="supervisor"' in text


def test_admin_filtra_empresa(client):
    _login(client, "admin@x")
    text = _text(client, "/supervision?empresa=EMP-02")
    assert "OtraEmpresa" in text
    assert "Propio" not in text


def test_admin_filtra_supervisor(client):
    _login(client, "admin@x")
    text = _text(client, "/supervision?supervisor=sup2@x")
    assert "OtraEmpresa" in text
    assert "Propio" not in text


def test_admin_filtra_asesor_pos_relevancia(client):
    _login(client, "admin@x")
    assert "OtroPos" in _text(client, "/supervision?asesor=AS-003")
    assert "Propio" not in _text(client, "/supervision?asesor=AS-003")
    assert "MismoPos" in _text(client, "/supervision?pos=PV-001")
    assert "OtroPos" not in _text(client, "/supervision?pos=PV-001")
    assert "Propio" in _text(client, "/supervision?banda=Alta")
    assert "MismoPos" not in _text(client, "/supervision?banda=Alta")
    assert "Propio" in _text(client, "/supervision?estado=Contactado")
    assert "Propio" not in _text(client, "/supervision?estado=No+contesta")


def test_admin_combinacion_inconsistente_no_filtra_datos(client):
    _login(client, "admin@x")
    # Asesor de EMP-01 con empresa EMP-02: combinación imposible → vacío.
    assert "Sin asignaciones" in _text(client, "/supervision?empresa=EMP-02&asesor=AS-001")
    # Empresa inexistente → vacío, sin error.
    assert "Sin asignaciones" in _text(client, "/supervision?empresa=EMP-99")
    # Supervisor inexistente → vacío.
    assert "Sin asignaciones" in _text(client, "/supervision?supervisor=nadie@x")


def test_admin_detalle_cualquier_empresa(client):
    _login(client, "admin@x")
    assert "OtraEmpresa" in _text(client, "/leads/L9")
    assert "Propio" in _text(client, "/leads/L1")
    _text(client, "/leads/NOPE", status=404)


def test_admin_ve_supervisores_varias_empresas(client):
    _login(client, "admin@x")
    text = _text(client, "/supervision")
    assert "sup1@x" in text and "sup2@x" in text
