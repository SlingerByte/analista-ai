"""Flujo IA browser-side (Ollama local): contexto y persistencia del resultado.

No usa navegador ni proveedores reales: ejercita los endpoints que el JS usa y
reutiliza `process_conversation` (validación, idempotencia, `is_current`) y el
scoring existente.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import get_session as auth_get_session
from app.auth import hash_password
from app.db import Base
from app.dashboard import get_session
from app.main import app
from app.models import (
    Advisor,
    AIExtraction,
    Company,
    Conversation,
    Lead,
    LeadScore,
    PointOfSale,
    User,
)

PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)

VALID_RESULT = {
    "model_interes": "Honda Navi",
    "model_interes_evidence": "me interesa la Honda Navi",
    "solicitud_cotizacion": True,
    "solicitud_cotizacion_evidence": "me la puede cotizar",
}


@pytest.fixture()
def client(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'browser.db'}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="E1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"))
        session.add(Advisor(advisor_id="AS-001", company_id="EMP-01",
                            point_of_sale_id="PV-001", name="Uno",
                            daily_capacity=5, active=True))
        session.add(User(company_id=None, advisor_id=None, email="admin@x",
                         password_hash=PASSWORD_HASH, role="admin"))
        session.add(Lead(lead_id="LD-01", company_id="EMP-01",
                         point_of_sale_id="PV-001", status="Sin gestión",
                         raw_payload={}, record_hash="h"))
        session.add(Conversation(
            conversation_id="CONV-01", lead_id="LD-01", company_id="EMP-01",
            status="linked",
            messages=[
                {"seq": 1, "sender": "cliente", "hour": "",
                 "text": "me interesa la Honda Navi"},
                {"seq": 2, "sender": "asesor", "hour": "", "text": "con gusto"},
                {"seq": 3, "sender": "cliente", "hour": "",
                 "text": "me la puede cotizar"},
            ]))
        session.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override
    yield TestClient(app), maker
    app.dependency_overrides.clear()
    engine.dispose()


def _login(client):
    assert client.post("/login", data={"email": "admin@x", "password": PASSWORD}
                      ).status_code in (200, 303)


def test_context_devuelve_mensajes_y_schema(client):
    http, _ = client
    _login(http)
    response = http.post("/supervision/ai-local-context", data={"limit": "1"})
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_version"] == "v8"
    assert body["schema_version"] == "v1"
    assert isinstance(body["schema"], dict)
    assert len(body["conversations"]) == 1
    messages = body["conversations"][0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "me la puede cotizar" in messages[1]["content"]


def test_result_persiste_rescora_e_idempotente(client):
    http, maker = client
    _login(http)
    first = http.post("/supervision/ai-local-result", json={
        "conversation_id": "CONV-01", "model": "qwen2.5:3b", "result": VALID_RESULT})
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["rescored"] is True

    with maker() as session:
        rows = session.scalars(sa.select(AIExtraction).where(
            AIExtraction.conversation_id == "CONV-01")).all()
        assert len(rows) == 1
        assert rows[0].provider == "ollama"
        assert rows[0].status == "success"
        assert rows[0].is_current is True
        assert session.scalar(sa.select(LeadScore).where(
            LeadScore.lead_id == "LD-01", LeadScore.is_current.is_(True))) is not None

    # Reintento del mismo input_hash: no duplica (misma fila).
    second = http.post("/supervision/ai-local-result", json={
        "conversation_id": "CONV-01", "model": "qwen2.5:3b", "result": VALID_RESULT})
    assert second.status_code == 200
    assert second.json()["ok"] is True
    with maker() as session:
        count = session.scalar(sa.select(sa.func.count()).select_from(AIExtraction)
                               .where(AIExtraction.conversation_id == "CONV-01"))
        assert count == 1


def test_result_invalido_no_rompe_y_mensaje_amigable(client):
    http, _ = client
    _login(http)
    response = http.post("/supervision/ai-local-result", json={
        "conversation_id": "CONV-01", "model": "qwen2.5:3b",
        "result": {"objecion": True, "intencion_compra": "altisima"}})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "no pudo procesar" in body["message"]
    assert "{" not in body["message"]


def test_endpoints_requieren_login(client):
    http, _ = client
    assert http.post("/supervision/ai-local-context", data={"limit": "1"}
                     ).status_code == 401
    assert http.post("/supervision/ai-local-result", json={
        "conversation_id": "CONV-01", "model": "m", "result": VALID_RESULT}
    ).status_code == 401
