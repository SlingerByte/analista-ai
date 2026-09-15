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
    Company,
    Conversation,
    Lead,
    LeadScore,
    PointOfSale,
    User,
)
from app.presentation import SCORE_REASON_LABELS, score_reason_label

DAY = date(2026, 9, 14)
PASSWORD = "secret"

XSS = "<script>alert('xss')</script>"


def _fields(**overrides) -> dict:
    base = {
        "schema_version": "v1",
        "model_interes": "Hero Dash 110",
        "model_interes_evidence": "estoy interesado en la Hero Dash 110",
        "presupuesto": None,
        "presupuesto_evidence": None,
        "cuota_inicial": None,
        "cuota_inicial_evidence": None,
        "forma_pago": None,
        "forma_pago_evidence": None,
        "intencion_compra": "alta",
        "intencion_compra_evidence": "estoy interesado en la Hero Dash 110",
        "objecion": None,
        "objecion_evidence": None,
        "solicitud_cita": None,
        "solicitud_cita_evidence": None,
        "solicitud_cotizacion": True,
        "solicitud_cotizacion_evidence": "me la cotiza",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def make_client(tmp_path):
    db_path = tmp_path / "ui_presentation.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    password_hash = hash_password(PASSWORD)

    with maker() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Asesor Uno", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Asesor Nueve", daily_capacity=5, active=True),
        ])
        session.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=password_hash, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup1@x",
                 password_hash=password_hash, role="supervisor"),
            User(company_id="EMP-02", advisor_id=None, email="sup2@x",
                 password_hash=password_hash, role="supervisor"),
            User(company_id=None, advisor_id=None, email="admin@x",
                 password_hash=password_hash, role="admin"),
        ])
        session.add_all([
            Lead(lead_id="LD-NOCONV", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Sin Conversacion", status="Contactado",
                 raw_payload={}, record_hash="a"),
            Lead(lead_id="LD-CHAT", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Con Conversacion", status="Contactado",
                 raw_payload={}, record_hash="b"),
            Lead(lead_id="LD-OTHER", company_id="EMP-02", point_of_sale_id="PV-006",
                 customer_name="Ajeno", status="Contactado",
                 raw_payload={}, record_hash="c"),
        ])
        session.add_all([
            LeadScore(lead_id="LD-NOCONV", score_version="v1", priority_score=40.0,
                      urgency_score=10.0, queue_score=40.0, band="Baja",
                      reasons=[{"code": "BASE_GESTIONABLE", "dimension": "commercial",
                                "text": "Lead registrado y gestionable.", "contribution": 20.0}],
                      is_current=True),
            LeadScore(lead_id="LD-CHAT", score_version="v1", priority_score=70.0,
                      urgency_score=90.0, queue_score=70.0, band="Alta",
                      reasons=[
                          {"code": "BASE_GESTIONABLE", "dimension": "commercial",
                           "text": "Lead registrado y gestionable.", "contribution": 20.0},
                          {"code": "ESTADO_OPERATIVO", "dimension": "urgency",
                           "text": "Estado de gestión: Sin gestión.", "contribution": 70.0},
                          {"code": "TELEFONO_VALIDO", "dimension": "quality",
                           "text": "Teléfono contactable.", "contribution": 30.0},
                      ],
                      is_current=True),
            LeadScore(lead_id="LD-OTHER", score_version="v1", priority_score=50.0,
                      urgency_score=10.0, queue_score=50.0, band="Media",
                      reasons=[], is_current=True),
        ])
        session.add_all([
            Assignment(lead_id="LD-NOCONV", advisor_id="AS-001", company_id="EMP-01",
                       point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                       priority_rank=2, status="assigned", reason="r", is_current=True),
            Assignment(lead_id="LD-CHAT", advisor_id="AS-001", company_id="EMP-01",
                       point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
            Assignment(lead_id="LD-OTHER", advisor_id="AS-009", company_id="EMP-02",
                       point_of_sale_id="PV-006", run_date=DAY, strategy_version="v1",
                       priority_rank=1, status="assigned", reason="r", is_current=True),
        ])
        session.add_all([
            Conversation(
                conversation_id="CONV-A", lead_id="LD-CHAT", company_id="EMP-01",
                channel="WhatsApp", status="linked",
                messages=[
                    {"seq": 1, "sender": "cliente", "hour": "10:32",
                     "text": "Hola, estoy interesado en la Hero Dash 110."},
                    {"seq": 2, "sender": "asesor", "hour": "10:34",
                     "text": "Claro, con gusto te ayudo."},
                    {"seq": 3, "sender": "cliente", "hour": "10:35",
                     "text": f"¿Puedo comprarla a crédito? {XSS}"},
                    {"seq": 4, "sender": "sistema", "hour": "10:36",
                     "text": "Mensaje automático de sistema."},
                ],
            ),
            Conversation(
                conversation_id="CONV-B", lead_id="LD-CHAT", company_id="EMP-01",
                channel="WhatsApp", status="linked",
                messages=[
                    {"seq": 1, "sender": "cliente", "hour": "09:00",
                     "text": "Segunda conversacion, buenos dias."},
                ],
            ),
        ])
        session.add(
            AIExtraction(
                conversation_id="CONV-A", lead_id="LD-CHAT", provider="fake",
                model_name="fake-1", prompt_version="v2", schema_version="v1",
                status="success", input_hash="h1", fields=_fields(), is_current=True,
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
    app.dependency_overrides[auth_get_session] = _override

    def _make(email: str) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        response = client.post("/login", data={"email": email, "password": PASSWORD})
        assert response.status_code in (200, 303), (email, response.status_code)
        return client

    yield _make
    app.dependency_overrides.clear()
    engine.dispose()


def _text(client, path, status=200):
    response = client.get(path)
    assert response.status_code == status, (path, response.status_code)
    return response.text


# --- Etiquetas de score -----------------------------------------------------


def test_score_reason_codes_have_human_labels():
    codes = [
        "BASE_GESTIONABLE",
        "TICKET_REGLA_NEGOCIO",
        "ESTADO_OPERATIVO",
        "SIN_CONTACTO_MAS_48H",
        "OBJECION_PRECIO",
        "INTENCION_ALTA",
        "TELEFONO_VALIDO",
        "URGENCIA_HOY_CITA",
        "FECHA_NO_CONFIABLE",
    ]
    for code in codes:
        label = score_reason_label(code)
        assert label and label != code
        assert "_" not in label


def test_unknown_reason_code_gets_readable_fallback():
    label = score_reason_label("CODIGO_INTERNO_NUEVO")
    assert "_" not in label
    assert label.lower().startswith("codigo")


def test_internal_codes_are_unchanged():
    # El mapa solo traduce: las claves siguen siendo los códigos internos.
    assert "BASE_GESTIONABLE" in SCORE_REASON_LABELS
    assert SCORE_REASON_LABELS["ESTADO_OPERATIVO"] == "Estado operativo"


def test_detail_shows_human_labels_not_codes(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    assert "Base gestionable" in text
    assert "Estado operativo" in text
    assert "BASE_GESTIONABLE" not in text
    assert "ESTADO_OPERATIVO" not in text
    # quality sigue fuera del breakdown de prioridad.
    assert "TELEFONO_VALIDO" not in text


# --- Conversación original --------------------------------------------------


def test_detail_shows_original_conversation(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    assert "Ver conversación" in text
    assert "Conversación original" in text
    assert "Hero Dash 110" in text
    assert "Cliente" in text and "Asesor" in text
    assert "10:32" in text
    # emisor no estándar se muestra tal cual, sin asumir cliente/asesor
    assert "sistema" in text


def test_messages_in_original_order(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    first = text.index("Hola, estoy interesado")
    second = text.index("Claro, con gusto")
    third = text.index("¿Puedo comprarla a crédito?")
    assert first < second < third


def test_conversation_text_is_html_escaped(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    assert "&lt;script&gt;" in text
    assert XSS not in text


def test_ai_evidence_is_shown(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    assert "Evidencia:" in text
    assert "estoy interesado en la Hero Dash 110" in text


def test_lead_without_conversation_keeps_message(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-NOCONV")
    assert "Este lead no tiene conversaciones registradas." in text
    assert "Ver conversación" not in text


def test_multiple_conversations_shown_separately(make_client):
    text = _text(make_client("adv@x"), "/leads/LD-CHAT")
    assert "CONV-A" in text and "CONV-B" in text
    assert text.count("Ver conversación") == 2
    assert "Segunda conversacion" in text


# --- Permisos ----------------------------------------------------------------


def test_permissions_of_conversation_view(make_client):
    chat = "/leads/LD-CHAT"
    assert make_client("adv@x").get(chat).status_code == 200
    assert make_client("sup1@x").get(chat).status_code == 200
    assert make_client("admin@x").get(chat).status_code == 200
    # supervisor de otra empresa no ve el lead ni su conversación
    assert make_client("sup2@x").get(chat).status_code == 404
    # asesor no ve leads ajenos (otra empresa)
    assert make_client("adv@x").get("/leads/LD-OTHER").status_code == 404
