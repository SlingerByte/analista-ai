from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import hash_password
from app.auth import get_session as auth_get_session
from app.dashboard import PAGE_SIZE, get_session
from app.db import Base
from app.main import app
from app.models import (
    Advisor,
    Assignment,
    CatalogItem,
    Company,
    Lead,
    LeadScore,
    PointOfSale,
    User,
)

DAY = date(2026, 9, 14)
PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)
BANDS = ["Alta", "Media", "Baja"]


def _build_db(maker):
    with maker() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Asesor Uno", daily_capacity=500, active=True),
            Advisor(advisor_id="AS-002", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Asesor Dos", daily_capacity=500, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Otra Empresa", daily_capacity=500, active=True),
        ])
        session.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-01", advisor_id=None, email="adm@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        session.add(CatalogItem(sku="SKU-1", brand="Honda", line="Navi",
                                engine_cc=110, segment="scooter",
                                list_price=7290000.0))
        for i in range(60):
            lead_id = f"LD-{i:02d}"
            band = BANDS[i % 3]
            session.add(Lead(
                lead_id=lead_id, company_id="EMP-01", point_of_sale_id="PV-001",
                customer_name=f"Cliente {i:02d}",
                status="Contactado" if i % 2 == 0 else "No contesta",
                city_raw="Bogotá",
                model_text_raw="Honda Navi" if i % 3 == 0 else "AKT NKD 125",
                sku="SKU-1" if i % 3 == 0 else None,
                raw_payload={}, record_hash=f"h{i}"))
            session.add(LeadScore(
                lead_id=lead_id, score_version="v1", priority_score=90.0 - i,
                urgency_score=10.0, queue_score=90.0 - i, band=band,
                reasons=[], is_current=True))
            session.add(Assignment(
                lead_id=lead_id,
                advisor_id="AS-001" if i % 2 == 0 else "AS-002",
                company_id="EMP-01", point_of_sale_id="PV-001",
                run_date=DAY, strategy_version="v1", priority_rank=i + 1,
                status="assigned", reason="rank por prioridad", is_current=True))
        for j in range(60):
            lead_id = f"LD-OV-{j}"
            session.add(Lead(
                lead_id=lead_id, company_id="EMP-01", point_of_sale_id="PV-001",
                customer_name=f"Overflow {j}", status="Contactado",
                city_raw="Bogotá", model_text_raw="AKT NKD 125",
                raw_payload={}, record_hash=f"ov{j}"))
            session.add(LeadScore(
                lead_id=lead_id, score_version="v1", priority_score=5.0,
                urgency_score=1.0, queue_score=5.0, band="Baja",
                reasons=[], is_current=True))
            session.add(Assignment(
                lead_id=lead_id, advisor_id=None,
                company_id="EMP-01", point_of_sale_id="PV-001",
                run_date=DAY, strategy_version="v1", priority_rank=100 + j,
                status="overflow", reason="sin_capacidad", is_current=True))
        session.add(Lead(
            lead_id="LD-OTHER", company_id="EMP-02", point_of_sale_id="PV-006",
            customer_name="Forastero", status="Contactado",
            raw_payload={}, record_hash="other"))
        session.add(LeadScore(
            lead_id="LD-OTHER", score_version="v1", priority_score=95.0,
            urgency_score=10.0, queue_score=95.0, band="Alta",
            reasons=[], is_current=True))
        session.add(Assignment(
            lead_id="LD-OTHER", advisor_id="AS-009",
            company_id="EMP-02", point_of_sale_id="PV-006",
            run_date=DAY, strategy_version="v1", priority_rank=1,
            status="assigned", reason="rank por prioridad", is_current=True))
        session.commit()


@pytest.fixture()
def sup_env(tmp_path):
    db_path = tmp_path / "supervision.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    _build_db(maker)

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override

    def make_client(email):
        client = TestClient(app, follow_redirects=False)
        response = client.post("/login",
                               data={"email": email, "password": PASSWORD})
        assert response.status_code in (200, 303), (email, response.status_code)
        return client

    yield {"make_client": make_client, "engine": engine}
    app.dependency_overrides.clear()
    engine.dispose()


def _get_text(client, path):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.text


def _count_queries(engine, client, path):
    seen: list = []

    def _listener(*args, **kwargs):
        seen.append(1)

    sa.event.listen(engine, "before_cursor_execute", _listener)
    try:
        text = _get_text(client, path)
    finally:
        sa.event.remove(engine, "before_cursor_execute", _listener)
    return text, len(seen)


# --- Paginación ---------------------------------------------------------------


def test_supervision_page_size_is_50():
    assert PAGE_SIZE == 50


def test_supervision_page1_shows_first_50(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision")
    assert "Página 1 de 3" in text
    assert "Cliente 00" in text
    assert "Cliente 49" in text
    assert "Cliente 50" not in text


def test_supervision_page2_shows_rest(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?page=2")
    assert "Página 2 de 3" in text
    assert "Cliente 50" in text
    assert "Cliente 59" in text
    assert "Cliente 00" not in text


def test_supervision_page_out_of_range_clamps_to_last(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?page=99")
    assert "Página 3 de 3" in text
    assert "Overflow 59" in text


@pytest.mark.parametrize("bad_page", ["0", "-1", "abc", ""])
def test_supervision_invalid_page_falls_back_to_first(sup_env, bad_page):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, f"/supervision?page={bad_page}")
    assert "Página 1 de 3" in text
    assert "Cliente 00" in text


# --- Filtros con paginación ------------------------------------------------------


def test_supervision_filter_banda(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?banda=Alta")
    assert "Cliente 00" in text  # i=0 → Alta
    assert "Cliente 01" not in text  # Media
    assert "Página" not in text  # una sola página: sin controles


def test_supervision_filter_estado(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?estado=No+contesta")
    assert "Cliente 01" in text
    assert "Cliente 00" not in text


def test_supervision_filter_modelo(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?modelo=navi")
    assert "Cliente 00" in text  # Honda Navi (catálogo)
    assert "Cliente 01" not in text  # AKT


def test_supervision_filter_asesor_y_pos(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?asesor=AS-002")
    assert "Cliente 01" in text
    assert "Cliente 00" not in text
    text = _get_text(client, "/supervision?pos=PV-001")
    assert "Cliente 00" in text


def test_supervision_overflow_visible_on_both_pages(sup_env):
    client = sup_env["make_client"]("sup@x")
    assert "Overflow 0" in _get_text(client, "/supervision")
    assert "Overflow 0" in _get_text(client, "/supervision?page=2")


# --- Separación gestión vs pendientes --------------------------------------------


def test_supervision_sections_are_separate(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision")
    assert "Gestión comercial" in text
    assert "Pendientes de asignación" in text
    assert 'aria-label="Paginación de gestión comercial"' in text
    assert 'aria-label="Paginación de pendientes"' in text
    assert "Listado independiente de la paginación de gestión comercial" in text


def test_pending_pagination_is_independent(sup_env):
    client = sup_env["make_client"]("sup@x")
    # ppage=2 cambia solo pendientes; gestión sigue en página 1.
    text = _get_text(client, "/supervision?ppage=2")
    assert "Página 1 de 3" in text
    assert "Cliente 00" in text
    assert "Overflow 50" in text
    assert "Pendientes: página 2 de 2" in text
    # page=2 no mueve pendientes (siguen en su página 1).
    text = _get_text(client, "/supervision?page=2")
    assert "Página 2 de 3" in text
    assert "Overflow 0" in text
    assert "Overflow 50" not in text


def test_pending_invalid_ppage_clamps(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?ppage=abc")
    assert "Overflow 0" in text
    text = _get_text(client, "/supervision?ppage=99")
    assert "Pendientes: página 2 de 2" in text


def test_pending_nav_preserves_filters_and_main_page(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?pos=PV-001")
    assert "ppage=2" in text
    assert "pos=PV-001" in text
    assert "page=1" in text


def test_assigned_plus_pending_equals_candidates():
    from app.assignment.service import (
        AdvisorCapacity,
        LeadCandidate,
        plan_assignments,
    )
    candidates = [LeadCandidate(f"LD-{i}", "E", "P", queue=100.0 - i) for i in range(7)]
    advisors = [AdvisorCapacity("A1", "E", "P", daily_capacity=3),
                AdvisorCapacity("A2", "E", "P", daily_capacity=2)]
    decisions = plan_assignments(candidates, advisors)
    assigned = sum(1 for d in decisions if d.status == "assigned")
    overflow = sum(1 for d in decisions if d.status == "overflow")
    assert assigned + overflow == len(candidates)
    assert (assigned, overflow) == (5, 2)


# --- Seguridad ---------------------------------------------------------------------


def test_supervision_advisor_is_forbidden(sup_env):
    client = sup_env["make_client"]("adv@x")
    assert client.get("/supervision").status_code == 403


def test_supervision_supervisor_scoped_to_company(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision")
    assert "Cliente 00" in text
    assert "Forastero" not in text


def test_supervision_admin_sees_all_companies(sup_env):
    client = sup_env["make_client"]("adm@x")
    text = _get_text(client, "/supervision")
    assert "Supervisión global" in text
    # EMP-02 va después de EMP-01 por el orden actual: Forastero está en página 3.
    assert "Forastero" in _get_text(client, "/supervision?page=3")


# --- UI -------------------------------------------------------------------------------


def test_supervision_pagination_links_preserve_filters(sup_env):
    client = sup_env["make_client"]("sup@x")
    text = _get_text(client, "/supervision?pos=PV-001")
    assert "Página 1 de 3" in text
    assert "page=2" in text
    assert "pos=PV-001" in text


# --- Rendimiento / N+1 -------------------------------------------------------------------


def test_supervision_queries_do_not_grow_per_row(sup_env):
    client = sup_env["make_client"]("sup@x")
    _, queries_page1 = _count_queries(sup_env["engine"], client, "/supervision")
    _, queries_page2 = _count_queries(sup_env["engine"], client, "/supervision?page=2")
    # 50 filas vs 15 filas: con N+1 diferirían en ~100 queries; en batch son iguales.
    assert queries_page1 == queries_page2
    assert queries_page1 <= 30, queries_page1
