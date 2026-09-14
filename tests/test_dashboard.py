from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
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
    LeadScore,
    PointOfSale,
)

DAY = date(2026, 9, 14)


def _score(lead_id, queue, band, reasons=None):
    return LeadScore(
        lead_id=lead_id,
        score_version="v1",
        priority_score=queue,
        urgency_score=10.0,
        queue_score=queue,
        band=band,
        reasons=reasons or [],
        is_current=True,
    )


def _assignment(lead_id, advisor_id, company, pos, rank, run_date=DAY, current=True):
    return Assignment(
        lead_id=lead_id,
        advisor_id=advisor_id,
        company_id=company,
        point_of_sale_id=pos,
        run_date=run_date,
        strategy_version="v1",
        priority_rank=rank,
        status="assigned",
        reason="rank por prioridad",
        is_current=current,
    )


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "dashboard.db"
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
                    name="Demo Asesor", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-002", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Otro", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-003", company_id="EMP-01", point_of_sale_id="PV-002",
                    name="Pos Dos", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Otra Empresa", daily_capacity=5, active=True),
        ])
        session.add(CatalogItem(sku="SKU-1", brand="Honda", line="Navi",
                                engine_cc=110, segment="scooter", list_price=7290000.0))
        session.add_all([
            Lead(lead_id="LD-A", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Ana Alta", status="Contactado", city_raw="Bogotá",
                 model_text_raw="Honda Navi", sku="SKU-1",
                 raw_payload={}, record_hash="a"),
            Lead(lead_id="LD-B", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Beto Medio", status="Contactado", city_raw="Medellín",
                 model_text_raw="AKT NKD 125", raw_payload={}, record_hash="b"),
            Lead(lead_id="LD-C", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Ceci Baja", status="No contesta",
                 raw_payload={}, record_hash="c"),
            Lead(lead_id="LD-OTHER", company_id="EMP-02", point_of_sale_id="PV-006",
                 customer_name="Forastero", status="Contactado",
                 raw_payload={}, record_hash="d"),
            Lead(lead_id="LD-POS2", company_id="EMP-01", point_of_sale_id="PV-002",
                 customer_name="Vecino", status="Contactado",
                 raw_payload={}, record_hash="e"),
        ])
        session.add_all([
            _score("LD-A", 80.0, "Alta",
                   [{"code": "INTENCION_ALTA", "dimension": "commercial",
                     "text": "Quiere comprar", "contribution": 30.0}]),
            _score("LD-B", 50.0, "Media"),
            _score("LD-C", 20.0, "Baja"),
            _score("LD-OTHER", 95.0, "Alta"),
            _score("LD-POS2", 90.0, "Alta"),
        ])
        session.add_all([
            _assignment("LD-A", "AS-001", "EMP-01", "PV-001", 1),
            _assignment("LD-B", "AS-001", "EMP-01", "PV-001", 2),
            _assignment("LD-C", "AS-001", "EMP-01", "PV-001", 3),
            _assignment("LD-OTHER", "AS-009", "EMP-02", "PV-006", 1),
            _assignment("LD-POS2", "AS-003", "EMP-01", "PV-002", 1),
            _assignment("LD-B", "AS-001", "EMP-01", "PV-001", 9,
                        run_date=date(2026, 9, 13), current=False),
        ])
        session.add_all([
            Conversation(conversation_id="CONV-1", lead_id="LD-A", company_id="EMP-01",
                         channel="WhatsApp", status="linked",
                         messages=[{"seq": 1, "sender": "cliente", "hour": "",
                                    "text": "Me interesa la Navi"}]),
            Conversation(conversation_id="CONV-3", lead_id="LD-C", company_id="EMP-01",
                         channel="WhatsApp", status="linked",
                         messages=[{"seq": 1, "sender": "cliente", "hour": "",
                                    "text": "Hola"}]),
        ])
        session.add(
            AIExtraction(
                conversation_id="CONV-1", lead_id="LD-A", provider="fake",
                model_name="fake-1", prompt_version="v2", schema_version="v1",
                status="success", input_hash="h1",
                fields={"schema_version": "v1", "model_interes": "Honda Navi",
                        "model_interes_evidence": "Me interesa la Navi",
                        "presupuesto": None, "presupuesto_evidence": None,
                        "cuota_inicial": None, "cuota_inicial_evidence": None,
                        "forma_pago": "financiacion",
                        "forma_pago_evidence": "financiada porfa",
                        "intencion_compra": "alta",
                        "intencion_compra_evidence": "la quiero comprar",
                        "objecion": None, "objecion_evidence": None,
                        "solicitud_cita": None, "solicitud_cita_evidence": None,
                        "solicitud_cotizacion": True,
                        "solicitud_cotizacion_evidence": "me la cotiza"},
                is_current=True,
            )
        )
        session.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_listado_muestra_solo_leads_del_asesor(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Mis leads de hoy" in response.text
    assert "Priorizacion" in response.text
    for name in ("Ana Alta", "Beto Medio", "Ceci Baja"):
        assert name in response.text
    assert "Forastero" not in response.text
    assert "Vecino" not in response.text
    assert ">3<" in response.text  # total


def test_orden_por_priority_rank(client):
    text = response_text(client, "/")
    assert text.index("Ana Alta") < text.index("Beto Medio") < text.index("Ceci Baja")


def response_text(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return response.text


def test_filtro_por_banda(client):
    text = response_text(client, "/?banda=Alta")
    assert "Ana Alta" in text
    assert "Beto Medio" not in text
    assert "Ceci Baja" not in text


def test_filtro_por_estado(client):
    text = response_text(client, "/?estado=No+contesta")
    assert "Ceci Baja" in text
    assert "Ana Alta" not in text


def test_filtro_por_modelo(client):
    text = response_text(client, "/?modelo=navi")
    assert "Ana Alta" in text
    assert "Beto Medio" not in text


def test_fecha_sin_asignaciones_muestra_vacio(client):
    text = response_text(client, "/?run_date=2026-01-01")
    assert "Sin leads" in text
    assert "Ana Alta" not in text


def test_detalle_muestra_razones_y_senales(client):
    text = response_text(client, "/leads/LD-A")
    assert "INTENCION_ALTA" in text
    assert "Quiere comprar" in text
    assert "financiacion" in text
    assert "ranking #1" in text
    # Null de IA visible como desconocido, sin inventar.
    assert "Desconocido" in text


def test_detalle_sin_extraccion_y_sin_conversacion(client):
    assert "Sin extracción IA vigente" in response_text(client, "/leads/LD-C")
    assert "no tiene conversaciones" in response_text(client, "/leads/LD-B")


def test_detalle_fuera_del_contexto_es_404(client):
    assert client.get("/leads/LD-OTHER").status_code == 404
    assert client.get("/leads/LD-POS2").status_code == 404
    assert client.get("/leads/NOPE").status_code == 404


def test_asesor_demo_inexistente_es_404(client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.dashboard.get_settings",
        lambda: SimpleNamespace(demo_advisor_id="NOPE", app_name="x"),
    )
    assert client.get("/").status_code == 404
