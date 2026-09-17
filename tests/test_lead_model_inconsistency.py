"""Inconsistencia de modelo CRM vs IA en el detalle del lead."""

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
    AIExtraction,
    Assignment,
    CatalogItem,
    Company,
    Conversation,
    Lead,
    PointOfSale,
    User,
)

DAY = date(2026, 9, 14)
PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)

CATALOG = [
    ("SKU-GN", "Suzuki", "GN 125"),
    ("SKU-TTR", "AKT", "TTR 200"),
    ("SKU-GIXXER", "Suzuki", "Gixxer 150"),
    ("SKU-BEST", "Suzuki", "Best 125"),
    ("SKU-NS125", "Bajaj", "Pulsar NS 125"),
]


def _extraction(conv_id, lead_id, model, evidence=None, status="success",
                is_current=True, hash_suffix="a"):
    return AIExtraction(
        conversation_id=conv_id, lead_id=lead_id, provider="fake",
        model_name="fake-1", prompt_version="v7", schema_version="v1",
        status=status, input_hash=f"h-{conv_id}-{hash_suffix}",
        fields={"model_interes": model, "model_interes_evidence": evidence},
        is_current=is_current,
    )


def _setup(maker):
    with maker() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add(Advisor(advisor_id="AS-001", company_id="EMP-01",
                            point_of_sale_id="PV-001", name="Demo",
                            daily_capacity=5, active=True))
        session.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-01", advisor_id=None, email="adm@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        for sku, brand, line in CATALOG:
            session.add(CatalogItem(sku=sku, brand=brand, line=line, engine_cc=125,
                                    segment="moto", list_price=6000000.0))
        leads = {
            "LD-CASE1": ("Suzuki GN 125", "SKU-GN"),
            "LD-CASE2": ("Suzuki Gixxer 150", "SKU-GIXXER"),
            "LD-CASE3": ("Suzuki Gixxer 150", "SKU-GIXXER"),
            "LD-CASE4": ("Bajaj", None),
            "LD-ERR": ("Suzuki Best 125", "SKU-BEST"),
            "LD-STALE": ("Suzuki Best 125", "SKU-BEST"),
            "LD-OTHER": ("Suzuki GN 125", "SKU-GN"),
        }
        for lead_id, (text, sku) in leads.items():
            company = "EMP-02" if lead_id == "LD-OTHER" else "EMP-01"
            pos = "PV-006" if lead_id == "LD-OTHER" else "PV-001"
            session.add(Lead(lead_id=lead_id, company_id=company,
                             point_of_sale_id=pos, customer_name=lead_id,
                             model_text_raw=text, sku=sku, raw_payload={},
                             record_hash=lead_id))
        session.commit()

        convos = {
            "CONV-1": ("LD-CASE1", "AKT TTR 200",
                       "Buen día, vi el anuncio de la AKT TTR 200"),
            "CONV-2": ("LD-CASE2", "Suzuki Best 125", "me gusta la Best 125"),
            "CONV-3": ("LD-CASE3", "Suzuki Gixxer 150", "quiero la Gixxer 150"),
            "CONV-4": ("LD-CASE4", "Bajaj Pulsar NS 125", "quiero la Pulsar"),
            "CONV-ERR": ("LD-ERR", "Suzuki GN 125", "vi la GN 125"),
            "CONV-STALE": ("LD-STALE", "Suzuki Best 125", "la Best 125"),
            "CONV-OTHER": ("LD-OTHER", "AKT TTR 200", "vi la TTR"),
        }
        for conv_id, (lead_id, _model, _ev) in convos.items():
            company = "EMP-02" if lead_id == "LD-OTHER" else "EMP-01"
            session.add(Conversation(
                conversation_id=conv_id, lead_id=lead_id, company_id=company,
                channel="WhatsApp", status="linked",
                messages=[{"seq": 1, "sender": "cliente", "hour": "",
                           "text": "hola"}]))
        session.commit()

        session.add_all([
            _extraction("CONV-1", "LD-CASE1", "AKT TTR 200",
                        "Buen día, vi el anuncio de la AKT TTR 200"),
            _extraction("CONV-2", "LD-CASE2", "Suzuki Best 125", "me gusta la Best 125"),
            _extraction("CONV-3", "LD-CASE3", "Suzuki Gixxer 150", "quiero la Gixxer 150"),
            _extraction("CONV-4", "LD-CASE4", "Bajaj Pulsar NS 125", "quiero la Pulsar"),
            # Error: la IA no debe generar inconsistencia.
            _extraction("CONV-ERR", "LD-ERR", "Suzuki GN 125", "vi la GN 125",
                        status="error"),
            # Vigente OK, pero existe una vieja (is_current=False) con otro modelo:
            # la vieja NO cuenta.
            _extraction("CONV-STALE", "LD-STALE", "Suzuki Best 125", "la Best 125"),
            _extraction("CONV-STALE", "LD-STALE", "AKT TTR 200", "vi la TTR",
                        is_current=False, hash_suffix="old"),
            _extraction("CONV-OTHER", "LD-OTHER", "AKT TTR 200", "vi la TTR"),
        ])
        for lead_id in leads:
            session.add(Assignment(
                lead_id=lead_id, advisor_id="AS-001",
                company_id="EMP-02" if lead_id == "LD-OTHER" else "EMP-01",
                point_of_sale_id="PV-006" if lead_id == "LD-OTHER" else "PV-001",
                run_date=DAY, strategy_version="v1", priority_rank=1,
                status="assigned", reason="x", is_current=True))
        session.commit()


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "lead_inconsistency.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    _setup(maker)

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override

    def make_client(email: str):
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"email": email, "password": PASSWORD})
        return client

    yield {"make_client": make_client, "maker": maker}
    app.dependency_overrides.clear()
    engine.dispose()


def test_case1_different_brand(env):
    html = env["make_client"]("sup@x").get("/leads/LD-CASE1").text
    assert "Inconsistencia detectada" in html
    assert "Suzuki GN 125" in html
    assert "AKT TTR 200" in html
    assert "Marca distinta" in html
    assert "vi el anuncio de la AKT TTR 200" in html


def test_case2_same_brand_different_model(env):
    html = env["make_client"]("sup@x").get("/leads/LD-CASE2").text
    assert "Inconsistencia detectada" in html
    assert "Mismo fabricante, modelo diferente" in html


def test_case3_same_sku_no_inconsistency(env):
    html = env["make_client"]("sup@x").get("/leads/LD-CASE3").text
    assert "Inconsistencia detectada" not in html


def test_case4_ambiguous_crm_no_inconsistency(env):
    # CRM "Bajaj" es solo marca → no comparable → no se muestra.
    html = env["make_client"]("sup@x").get("/leads/LD-CASE4").text
    assert "Inconsistencia detectada" not in html


def test_error_extraction_does_not_flag(env):
    html = env["make_client"]("sup@x").get("/leads/LD-ERR").text
    assert "Inconsistencia detectada" not in html


def test_stale_extraction_is_ignored(env):
    # La fila vigente coincide con el CRM; la vieja (is_current=False) no cuenta.
    html = env["make_client"]("sup@x").get("/leads/LD-STALE").text
    assert "Inconsistencia detectada" not in html


def test_crm_data_is_not_modified(env):
    client = env["make_client"]("sup@x")
    assert client.get("/leads/LD-CASE1").status_code == 200
    with env["maker"]() as session:
        lead = session.get(Lead, "LD-CASE1")
        assert lead.model_text_raw == "Suzuki GN 125"
        assert lead.sku == "SKU-GN"


def test_scope_blocks_other_company(env):
    client = env["make_client"]("sup@x")
    assert client.get("/leads/LD-OTHER").status_code == 404
