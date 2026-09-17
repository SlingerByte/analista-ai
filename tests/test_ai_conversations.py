"""Conversaciones analizadas (/ai/conversations): lista, detalle, scope, integridad."""

from __future__ import annotations

from datetime import date, datetime

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

DAY = date(2026, 9, 14)
PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


def _conv(session, conv_id, lead_id, company, text="Hola"):
    session.add(Conversation(
        conversation_id=conv_id, lead_id=lead_id, company_id=company,
        channel="WhatsApp", status="linked",
        messages=[
            {"seq": 1, "sender": "cliente", "hour": "10:00", "text": text},
            {"seq": 2, "sender": "asesor", "hour": "10:05", "text": "Con gusto"},
        ]))


def _ext(session, conv_id, lead_id, fields, *, status="success", current=True, h="x"):
    session.add(AIExtraction(
        conversation_id=conv_id, lead_id=lead_id, provider="local",
        model_name="qwen2.5:3b", prompt_version="v7", schema_version="v1",
        status=status, input_hash=f"{conv_id}-{h}", fields=fields, is_current=current,
        latency_ms=1234))


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "ai_conversations.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        s.add_all([Company(company_id="EMP-01", name="E1"),
                   Company(company_id="EMP-02", name="E2")])
        s.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        s.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Asesor Uno", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-002", company_id="EMP-01", point_of_sale_id="PV-001",
                    name="Asesor Dos", daily_capacity=5, active=True),
            Advisor(advisor_id="AS-009", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Otra", daily_capacity=5, active=True),
        ])
        s.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-01", advisor_id=None, email="adm@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        s.add_all([
            Lead(lead_id="LD-A", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Ana Alta", raw_payload={}, record_hash="a"),
            Lead(lead_id="LD-B", company_id="EMP-01", point_of_sale_id="PV-001",
                 customer_name="Beto Medio", raw_payload={}, record_hash="b"),
            Lead(lead_id="LD-O", company_id="EMP-02", point_of_sale_id="PV-006",
                 customer_name="Olga Otra", raw_payload={}, record_hash="o"),
        ])
        _conv(s, "CONV-1", "LD-A", "EMP-01", "Buen día, me interesa la Honda Navi")
        _conv(s, "CONV-2", "LD-B", "EMP-01", "Me interesa la AKT TTR 200")
        _conv(s, "CONV-3", "LD-A", "EMP-01", "error conv")
        _conv(s, "CONV-4", "LD-A", "EMP-01", "vieja conv")
        _conv(s, "CONV-5", "LD-O", "EMP-02", "moto EMP-02")
        _conv(s, "CONV-6", "LD-A", "EMP-01", "presupuesto y cotizacion")
        _conv(s, "CONV-7", "LD-A", "EMP-01", "historica y vigente")
        _ext(s, "CONV-1", "LD-A", {
            "model_interes": "Honda Navi",
            "model_interes_evidence": "me interesa la Honda Navi",
            "intencion_compra": "alta", "intencion_compra_evidence": "la quiero",
            "presupuesto": 5000000, "presupuesto_evidence": "tengo 5 millones",
            "cuota_inicial": None, "forma_pago": "contado",
            "forma_pago_evidence": "de contado", "objecion": None,
            "solicitud_cita": True, "solicitud_cita_evidence": "los visito",
            "solicitud_cotizacion": False})
        _ext(s, "CONV-2", "LD-B", {
            "model_interes": "AKT TTR 200", "intencion_compra": "media",
            "solicitud_cita": None, "solicitud_cotizacion": None})
        _ext(s, "CONV-3", "LD-A", {"model_interes": "No deberia"}, status="error")
        _ext(s, "CONV-4", "LD-A", {"model_interes": "No vigente"}, current=False)
        _ext(s, "CONV-5", "LD-O", {"model_interes": "Suzuki GN", "intencion_compra": "alta"})
        _ext(s, "CONV-6", "LD-A", {
            "model_interes": "Hero Dash", "intencion_compra": "baja",
            "solicitud_cotizacion": True, "solicitud_cotizacion_evidence": "mándemela",
            "objecion": "precio", "objecion_evidence": "muy cara"})
        _ext(s, "CONV-7", "LD-A", {
            "model_interes": "Suzuki Best 125", "intencion_compra": "media"}, h="new")
        _ext(s, "CONV-7", "LD-A", {
            "model_interes": "Yamaha XTZ 250"}, current=False, h="old")
        # Lead sin asignación vigente: aparece en IA (no en Supervisión).
        s.add(Lead(lead_id="LD-UNASSIGNED", company_id="EMP-01",
                   point_of_sale_id="PV-001", customer_name="Un Sin Asignar",
                   raw_payload={}, record_hash="u"))
        _conv(s, "CONV-8", "LD-UNASSIGNED", "EMP-01", "sin asignacion")
        _ext(s, "CONV-8", "LD-UNASSIGNED", {
            "model_interes": "Honda Navi", "intencion_compra": "alta"})
        # Banda del lead (score vigente), independiente de la intención.
        s.add(LeadScore(lead_id="LD-A", score_version="v1", priority_score=80.0,
                        urgency_score=100.0, queue_score=86.0, band="Alta",
                        reasons=[], is_current=True))
        s.add(LeadScore(lead_id="LD-B", score_version="v1", priority_score=40.0,
                        urgency_score=50.0, queue_score=42.0, band="Baja",
                        reasons=[], is_current=True))
        for lead_id, advisor_id, company, pos in (
                ("LD-A", "AS-001", "EMP-01", "PV-001"),
                ("LD-B", "AS-002", "EMP-01", "PV-001"),
                ("LD-O", "AS-009", "EMP-02", "PV-006")):
            s.add(Assignment(lead_id=lead_id, advisor_id=advisor_id, company_id=company,
                             point_of_sale_id=pos, run_date=DAY, strategy_version="v1",
                             priority_rank=1, status="assigned", reason="x", is_current=True))
        s.commit()

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


def _text(client, path) -> str:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.text


# --- Lista ---------------------------------------------------------------------


def test_lists_success_current(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "CONV-1" in html and "Analizada" in html


def test_error_extraction_not_listed(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "CONV-3" not in html
    assert "No deberia" not in html


def test_non_current_extraction_not_listed(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "CONV-4" not in html
    assert "No vigente" not in html


def test_only_current_used_when_history_exists(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "Suzuki Best 125" in html
    assert "Yamaha XTZ 250" not in html


# --- Búsqueda ------------------------------------------------------------------


def test_search_by_conversation_id(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?search=CONV-1")
    assert "CONV-1" in html


def test_search_by_customer_name(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?search=Beto")
    assert "CONV-2" in html and "CONV-1" not in html


def test_search_by_lead_id(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?search=LD-B")
    assert "CONV-2" in html and "CONV-1" not in html


# --- Filtros -------------------------------------------------------------------


def test_filter_by_intent(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?intent=alta")
    assert "CONV-1" in html and "CONV-2" not in html


def test_filter_by_cita(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?signal=cita")
    assert "CONV-1" in html and "CONV-2" not in html


def test_filter_by_cotizacion(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?signal=cotizacion")
    assert "CONV-6" in html and "CONV-1" not in html


def test_filter_by_objecion(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?signal=objecion")
    assert "CONV-6" in html and "CONV-1" not in html


# --- Detalle -------------------------------------------------------------------


def test_detail_shows_messages_fields_and_metadata(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations/CONV-1")
    assert "Buen día, me interesa la Honda Navi" in html
    assert "Honda Navi" in html
    assert "Alta" in html or "alta" in html.lower()
    assert "Evidencia" in html
    assert "Proveedor: local" in html
    assert "qwen2.5:3b" in html
    assert "Versión del prompt: v7" in html
    assert "/leads/LD-A" in html


def test_detail_null_is_no_determinado(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations/CONV-2")
    assert "No determinado" in html


def test_detail_false_is_no(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations/CONV-1")
    assert "Cotización" in html
    assert "No" in html


# --- Seguridad -----------------------------------------------------------------


def test_advisor_cannot_see_out_of_scope(env):
    client = env["make_client"]("adv@x")
    assert client.get("/ai/conversations/CONV-2").status_code == 404
    html = _text(client, "/ai/conversations?search=CONV-2")
    # El término buscado se refleja en el input, pero la fila no aparece.
    assert "/ai/conversations/CONV-2" not in html


def test_advisor_sees_own_scope(env):
    html = _text(env["make_client"]("adv@x"), "/ai/conversations")
    assert "CONV-1" in html
    assert "CONV-2" not in html


def test_supervisor_cannot_see_other_company(env):
    client = env["make_client"]("sup@x")
    assert client.get("/ai/conversations/CONV-5").status_code == 404
    html = _text(client, "/ai/conversations?search=Olga")
    assert "CONV-5" not in html


def test_admin_sees_all_companies(env):
    client = env["make_client"]("adm@x")
    assert client.get("/ai/conversations/CONV-5").status_code == 200
    html = _text(client, "/ai/conversations")
    assert "CONV-5" in html and "CONV-1" in html


def test_anonymous_redirected(env):
    bare = TestClient(app, follow_redirects=False)
    assert bare.get("/ai/conversations").status_code == 303


# --- Integridad ----------------------------------------------------------------


def test_visiting_views_does_not_change_data(env):
    client = env["make_client"]("sup@x")
    with env["maker"]() as s:
        before = {
            "extractions": s.scalar(sa.select(sa.func.count()).select_from(AIExtraction)),
            "scores": s.scalar(sa.select(sa.func.count()).select_from(LeadScore)),
            "assignments": s.scalar(sa.select(sa.func.count()).select_from(Assignment)),
        }
        lead = s.get(Lead, "LD-A")
        lead_hash = lead.record_hash
    client.get("/ai/conversations")
    client.get("/ai/conversations/CONV-1")
    with env["maker"]() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AIExtraction)) == before["extractions"]
        assert s.scalar(sa.select(sa.func.count()).select_from(LeadScore)) == before["scores"]
        assert s.scalar(sa.select(sa.func.count()).select_from(Assignment)) == before["assignments"]
        assert s.get(Lead, "LD-A").record_hash == lead_hash


# --- Orden ---------------------------------------------------------------------


def _add_analyzed(maker, rows):
    """rows: (conv_id, analyzed_at, started_at)."""
    with maker() as s:
        for conv_id, analyzed_at, started_at in rows:
            s.add(Conversation(conversation_id=conv_id, company_id="EMP-01",
                               status="linked", started_at=started_at, messages=[]))
            s.add(AIExtraction(
                conversation_id=conv_id, provider="p", model_name="m",
                prompt_version="v7", schema_version="v1", status="success",
                input_hash=f"h-{conv_id}", is_current=True,
                fields={"intencion_compra": "alta"}, created_at=analyzed_at))
        s.commit()


def _positions(html, ids):
    return {cid: html.index(cid) for cid in ids}


def test_default_order_is_most_recently_analyzed(env):
    _add_analyzed(env["maker"], [
        ("CONV-A", datetime(2026, 9, 1, 10), datetime(2026, 9, 1)),
        ("CONV-B", datetime(2026, 9, 3, 10), datetime(2026, 9, 3)),
        ("CONV-C", datetime(2026, 9, 2, 10), datetime(2026, 9, 2)),
    ])
    html = _text(env["make_client"]("adm@x"), "/ai/conversations")
    pos = _positions(html, ["CONV-A", "CONV-B", "CONV-C"])
    assert pos["CONV-B"] < pos["CONV-C"] < pos["CONV-A"]


def test_order_analyzed_asc(env):
    _add_analyzed(env["maker"], [
        ("CONV-A", datetime(2026, 9, 1, 10), datetime(2026, 9, 1)),
        ("CONV-B", datetime(2026, 9, 3, 10), datetime(2026, 9, 3)),
        ("CONV-C", datetime(2026, 9, 2, 10), datetime(2026, 9, 2)),
    ])
    html = _text(env["make_client"]("adm@x"), "/ai/conversations?order=analyzed_asc")
    pos = _positions(html, ["CONV-A", "CONV-B", "CONV-C"])
    assert pos["CONV-A"] < pos["CONV-C"] < pos["CONV-B"]


def test_order_by_conversation_date(env):
    _add_analyzed(env["maker"], [
        ("CONV-A", datetime(2026, 9, 1, 10), datetime(2026, 9, 1)),
        ("CONV-B", datetime(2026, 9, 2, 10), datetime(2026, 9, 5)),
        ("CONV-C", datetime(2026, 9, 3, 10), datetime(2026, 9, 3)),
    ])
    desc = _text(env["make_client"]("adm@x"), "/ai/conversations?order=conversation_desc")
    pos = _positions(desc, ["CONV-A", "CONV-B", "CONV-C"])
    assert pos["CONV-B"] < pos["CONV-C"] < pos["CONV-A"]
    asc = _text(env["make_client"]("adm@x"), "/ai/conversations?order=conversation_asc")
    pos = _positions(asc, ["CONV-A", "CONV-B", "CONV-C"])
    assert pos["CONV-A"] < pos["CONV-C"] < pos["CONV-B"]


def test_pagination_preserves_order(env):
    rows = [(f"CONV-{i:03d}", datetime(2026, 9, 1, 0, i), datetime(2026, 9, 1))
            for i in range(60)]
    _add_analyzed(env["maker"], rows)
    html = _text(env["make_client"]("adm@x"), "/ai/conversations?order=analyzed_asc")
    assert "Página 1 de 2" in html
    assert "order=analyzed_asc" in html and "page=2" in html


# --- Filtros adicionales -------------------------------------------------------


def test_filter_intent_none(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?intent=none")
    # CONV-2 (media) queda fuera; ninguna del fixture es null, aparece vacío.
    assert "No hay conversaciones analizadas" in html or "CONV-2" not in html


def test_filter_state_any_and_none(env):
    any_html = _text(env["make_client"]("sup@x"), "/ai/conversations?state=any")
    assert "CONV-1" in any_html  # tiene cita/presupuesto/forma de pago
    none_html = _text(env["make_client"]("sup@x"), "/ai/conversations?state=none")
    assert "CONV-2" in none_html  # sin señales determinadas
    assert "CONV-1" not in none_html


def test_filter_state_undetermined(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?state=undetermined")
    assert "CONV-2" in html  # cita/cotización null
    assert "CONV-1" in html  # cuota_inicial/objeción null


def test_signal_null_is_not_false(env):
    # Cita: CONV-1 true, CONV-2 null. El filtro "cita" solo trae true.
    html = _text(env["make_client"]("sup@x"), "/ai/conversations?signal=cita")
    assert "CONV-1" in html
    assert "CONV-2" not in html


def test_detail_link_preserves_filters(env):
    html = _text(env["make_client"]("sup@x"),
                 "/ai/conversations?intent=alta&order=analyzed_asc")
    assert "order=analyzed_asc" in html
    assert "intent=alta" in html


# --- Etiquetas: intención (conversación) vs banda (lead) + prompt -------------


def test_ui_labels_intent_band_and_prompt(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "Intención de compra:" in html      # intención de la conversación
    assert "Banda del lead:" in html           # banda del LeadScore
    assert "Prompt:" in html and "Schema:" in html
    assert "Prompt:</span>" not in html  # sanity


def test_unassigned_lead_visible_in_ai_not_in_supervision(env):
    # El lead sin asignación aparece en la vista IA (con aviso), no en Supervisión.
    html = _text(env["make_client"]("sup@x"), "/ai/conversations")
    assert "CONV-8" in html
    assert "Sin asignación" in html


def test_advisor_scope_unchanged_for_unassigned(env):
    # El asesor no ve la conversación de un lead sin asignación suya.
    html = _text(env["make_client"]("adv@x"), "/ai/conversations")
    assert "CONV-8" not in html
    assert "CONV-1" in html


def test_detail_shows_intent_label_and_prompt_version(env):
    html = _text(env["make_client"]("sup@x"), "/ai/conversations/CONV-1")
    assert "Intención de compra" in html
    assert "Versión del prompt: v7" in html


