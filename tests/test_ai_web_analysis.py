"""Análisis IA desde la web (/supervision/run-ai): límite, scope, proveedor."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.dashboard as dashboard
from app.ai.base import ExtractionOutcome
from app.ai.schema import ExtractionResult
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

PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


class FakeExtractor:
    """Extractor fake: no llama a Groq/Ollama. Registra conversaciones."""

    def __init__(self, provider: str = "local", available: bool = True):
        self.provider = provider
        self.model = "qwen2.5:3b"
        self.available = available
        self.calls: list[str] = []

    def availability(self):
        return (True, "ok") if self.available else (False, "no disponible fake")

    def extract(self, conversation):
        self.calls.append(conversation.conversation_id)
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=1,
            result=ExtractionResult(),
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "web_ai.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add_all([Company(company_id="EMP-01", name="E1"),
                         Company(company_id="EMP-02", name="E2")])
        session.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        session.add_all([
            Advisor(advisor_id="AS-001", company_id="EMP-01",
                    point_of_sale_id="PV-001", name="Asesor", daily_capacity=5,
                    active=True),
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-01", advisor_id=None, email="adm@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        for lead_id, company in (("LD-1", "EMP-01"), ("LD-2", "EMP-01"),
                                 ("LD-3", "EMP-01"), ("LD-O", "EMP-02")):
            session.add(Lead(lead_id=lead_id, company_id=company,
                             point_of_sale_id="PV-001" if company == "EMP-01" else "PV-006",
                             raw_payload={}, record_hash=lead_id))
        for conv_id, lead_id, company in (
                ("CONV-1", "LD-1", "EMP-01"), ("CONV-2", "LD-2", "EMP-01"),
                ("CONV-3", "LD-3", "EMP-01"), ("CONV-O", "LD-O", "EMP-02")):
            session.add(Conversation(
                conversation_id=conv_id, lead_id=lead_id, company_id=company,
                channel="WhatsApp", status="linked",
                messages=[{"seq": 1, "sender": "cliente", "hour": "",
                           "text": "Me interesa una moto"}]))
        session.commit()

    # Config controlada: solo `local` configurado por defecto (sin claves).
    from app.config import Settings

    monkeypatch.setattr(
        dashboard, "get_settings",
        lambda: Settings(ai_provider="local", groq_api_key=None,
                         openrouter_api_key=None))

    state = {"extractor": FakeExtractor()}

    def _build(provider, settings=None):
        extractor = FakeExtractor(provider=provider,
                                  available=state["extractor"].available)
        state["extractor"] = extractor
        return extractor

    monkeypatch.setattr(dashboard, "build_extractor", _build)

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override

    def make_client(email: str | None = None):
        client = TestClient(app, follow_redirects=False)
        if email:
            response = client.post("/login",
                                   data={"email": email, "password": PASSWORD})
            assert response.status_code in (200, 303)
        return client

    yield {"make_client": make_client, "maker": maker, "state": state}
    app.dependency_overrides.clear()
    engine.dispose()


def _location(response) -> dict:
    query = urlparse(response.headers["location"]).query
    return {k: v[0] for k, v in parse_qs(query).items()}


# --- Seguridad -----------------------------------------------------------------


def test_run_ai_requires_auth(env):
    client = env["make_client"]()
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_run_ai_advisor_forbidden(env):
    client = env["make_client"]("adv@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"})
    assert response.status_code == 403


def test_run_ai_invalid_provider_rejected(env):
    client = env["make_client"]("sup@x")
    assert client.post("/supervision/run-ai",
                       data={"provider": "evil", "limit": "1"}).status_code == 400
    # groq no configurado (sin clave) → no permitido.
    assert client.post("/supervision/run-ai",
                       data={"provider": "groq", "limit": "1"}).status_code == 400


@pytest.mark.parametrize("bad", ["abc", "0", "-1", ""])
def test_run_ai_invalid_limit_rejected(env, bad):
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": bad})
    assert response.status_code == 400


# --- Límite --------------------------------------------------------------------


def test_run_ai_limit_one(env):
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"})
    assert response.status_code == 303
    params = _location(response)
    assert params["ai_candidates"] == "1"
    assert params["ai_processed"] == "1"
    assert env["state"]["extractor"].calls == ["CONV-1"]


def test_run_ai_limit_ten_processes_available_only(env):
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "10"})
    params = _location(response)
    # 3 pendientes en EMP-01; no se inventan errores por las faltantes.
    assert params["ai_candidates"] == "3"
    assert params["ai_processed"] == "3"
    assert len(env["state"]["extractor"].calls) == 3


def test_run_ai_excessive_limit_is_clamped_server_side(env):
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "999999"})
    params = _location(response)
    assert params["ai_limit"] == "20"  # tope duro del servidor
    assert len(env["state"]["extractor"].calls) <= 20


def test_run_ai_does_not_exceed_limit_and_leaves_rest_pending(env):
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "2"})
    assert response.status_code == 303
    assert len(env["state"]["extractor"].calls) == 2
    with env["maker"]() as session:
        created = session.scalar(
            sa.select(sa.func.count()).select_from(AIExtraction))
    assert created == 2  # la tercera sigue pendiente


# --- Scope por empresa ----------------------------------------------------------


def test_run_ai_scopes_to_supervisor_company(env):
    client = env["make_client"]("sup@x")
    client.post("/supervision/run-ai", data={"provider": "local", "limit": "10"})
    calls = env["state"]["extractor"].calls
    assert "CONV-O" not in calls  # EMP-02 fuera del alcance
    with env["maker"]() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(AIExtraction).where(
                AIExtraction.conversation_id == "CONV-O")) == 0


def test_run_ai_admin_scope_all_companies(env):
    client = env["make_client"]("adm@x")
    client.post("/supervision/run-ai", data={"provider": "local", "limit": "10"})
    assert "CONV-O" in env["state"]["extractor"].calls


# --- Sin pendientes / proveedor no disponible ----------------------------------


def _mark_all_extracted(maker, company="EMP-01"):
    with maker() as session:
        convs = session.scalars(
            sa.select(Conversation).where(Conversation.company_id == company)).all()
        for conv in convs:
            session.add(AIExtraction(
                conversation_id=conv.conversation_id, lead_id=conv.lead_id,
                provider="fake", model_name="fake-1", prompt_version="v7",
                schema_version="v1", status="success", input_hash=f"h-{conv.conversation_id}",
                fields={}, is_current=True))
        session.commit()


def test_run_ai_no_pending_does_not_call_provider(env):
    _mark_all_extracted(env["maker"])
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "10"})
    params = _location(response)
    assert params.get("ai_empty") == "1"
    assert env["state"]["extractor"].calls == []


def test_run_ai_skips_conversations_with_error_row(env):
    # Una fila vigente en `error` no es "pendiente": reprocesarla sin force
    # choca con la constraint única. No debe seleccionarse.
    with env["maker"]() as session:
        session.add(AIExtraction(
            conversation_id="CONV-1", lead_id="LD-1", provider="groq",
            model_name="openai/gpt-oss-20b", prompt_version="v7",
            schema_version="v1", status="error", error="x", input_hash="h-err",
            fields=None, is_current=True))
        session.commit()
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"})
    params = _location(response)
    assert "CONV-1" not in env["state"]["extractor"].calls
    assert params["ai_processed"] == "1"


def test_run_ai_provider_unavailable_is_reported(env):
    env["state"]["extractor"] = FakeExtractor(available=False)
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "10"})
    params = _location(response)
    assert params.get("ai_unavailable") == "1"
    assert env["state"]["extractor"].calls == []


# --- Proveedor remoto si está configurado --------------------------------------


def test_run_ai_remote_provider_allowed_when_configured(env, monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(
        dashboard, "get_settings",
        lambda: Settings(ai_provider="groq", groq_api_key="k",
                         groq_model="openai/gpt-oss-20b",
                         openrouter_api_key=None))
    client = env["make_client"]("sup@x")
    response = client.post("/supervision/run-ai",
                           data={"provider": "groq", "limit": "1"})
    assert response.status_code == 303
    params = _location(response)
    assert params["ai_provider"] == "groq"
    assert env["state"]["extractor"].provider == "groq"


# --- Idempotencia --------------------------------------------------------------


def test_run_ai_is_idempotent(env):
    client = env["make_client"]("sup@x")
    client.post("/supervision/run-ai", data={"provider": "local", "limit": "10"})
    first_calls = len(env["state"]["extractor"].calls)
    client.post("/supervision/run-ai", data={"provider": "local", "limit": "10"})
    # Segundo run: reutiliza lo ya extraído, no vuelve a llamar al proveedor.
    assert len(env["state"]["extractor"].calls) == first_calls


# --- Recálculo de score de leads afectados -------------------------------------


def _add_conversation(maker, conv_id: str, lead_id: str | None,
                      company: str = "EMP-01") -> None:
    with maker() as session:
        session.add(Conversation(
            conversation_id=conv_id, lead_id=lead_id, company_id=company,
            channel="WhatsApp", status="linked",
            messages=[{"seq": 1, "sender": "cliente", "hour": "", "text": "hola"}]))
        session.commit()


def test_run_ai_rescores_affected_lead(env):
    client = env["make_client"]("sup@x")
    params = _location(client.post(
        "/supervision/run-ai", data={"provider": "local", "limit": "1"}))
    assert params["ai_rescored"] == "1"
    assert params["ai_rescore_errors"] == "0"
    with env["maker"]() as session:
        score = session.scalar(
            sa.select(LeadScore).where(LeadScore.lead_id == "LD-1",
                                       LeadScore.is_current.is_(True)))
        assert score is not None
        # No se ejecuta asignación.
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Assignment)) == 0


def test_run_ai_rescores_lead_once_for_multiple_conversations(env):
    _add_conversation(env["maker"], "CONV-1B", "LD-1")
    client = env["make_client"]("sup@x")
    params = _location(client.post(
        "/supervision/run-ai", data={"provider": "local", "limit": "10"}))
    # CONV-1, CONV-1B, CONV-2, CONV-3 → 3 leads únicos.
    assert params["ai_processed"] == "4"
    assert params["ai_rescored"] == "3"
    assert params["ai_rescore_errors"] == "0"


def test_run_ai_conversation_without_lead_does_not_fail(env):
    _add_conversation(env["maker"], "CONV-NOLEAD", None)
    client = env["make_client"]("sup@x")
    params = _location(client.post(
        "/supervision/run-ai", data={"provider": "local", "limit": "10"}))
    assert params["ai_processed"] == "4"  # incluye la huérfana
    assert params["ai_rescored"] == "3"   # solo leads existentes
    assert params["ai_rescore_errors"] == "0"


def test_run_ai_supervisor_does_not_rescore_other_company(env):
    client = env["make_client"]("sup@x")
    client.post("/supervision/run-ai", data={"provider": "local", "limit": "10"})
    with env["maker"]() as session:
        other = session.scalar(
            sa.select(sa.func.count()).select_from(LeadScore).where(
                LeadScore.lead_id == "LD-O"))
    assert other == 0


def test_run_ai_admin_rescores_scope(env):
    client = env["make_client"]("adm@x")
    params = _location(client.post(
        "/supervision/run-ai", data={"provider": "local", "limit": "10"}))
    # 4 conversaciones (3 EMP-01 + CONV-O) → 4 leads.
    assert params["ai_processed"] == "4"
    assert params["ai_rescored"] == "4"


def test_run_ai_rescore_error_is_tolerated(env, monkeypatch):
    real = dashboard.score_and_persist_lead

    def flaky(session, lead_id, **kwargs):
        if lead_id == "LD-2":
            raise RuntimeError("boom")
        return real(session, lead_id, **kwargs)

    monkeypatch.setattr(dashboard, "score_and_persist_lead", flaky)
    client = env["make_client"]("sup@x")
    params = _location(client.post(
        "/supervision/run-ai", data={"provider": "local", "limit": "10"}))
    assert params["ai_rescored"] == "2"
    assert params["ai_rescore_errors"] == "1"


# --- Lista de conversaciones de ESTA ejecución ---------------------------------


def _run_and_get(client, data) -> tuple[str, str]:
    response = client.post("/supervision/run-ai", data=data)
    location = response.headers["location"]
    return location, client.get(location).text


def test_run_ai_shows_processed_list_one(env):
    client = env["make_client"]("sup@x")
    location, html = _run_and_get(client, {"provider": "local", "limit": "1"})
    assert "ai_ids=CONV-1" in location
    assert "Ver analizadas (1)" in html
    assert "CONV-1" in html
    # Solo la de esta ejecución (no otras pendientes).
    assert "CONV-2" not in html
    assert "CONV-3" not in html


def test_run_ai_shows_processed_list_count(env):
    client = env["make_client"]("sup@x")
    _, html = _run_and_get(client, {"provider": "local", "limit": "10"})
    assert "Ver analizadas (3)" in html


def test_run_ai_list_shows_sin_lead(env):
    _add_conversation(env["maker"], "CONV-NOLEAD", None)
    client = env["make_client"]("sup@x")
    _, html = _run_and_get(client, {"provider": "local", "limit": "10"})
    assert "Ver analizadas (4)" in html
    assert "Sin lead" in html


def test_run_ai_list_respects_scope(env):
    # Aunque el navegador envíe un id fuera del alcance, no se muestra.
    client = env["make_client"]("sup@x")
    html = client.get("/supervision?ai=1&ai_ids=CONV-O").text
    assert "CONV-O" not in html
    assert "Ver analizadas" not in html


def test_run_ai_list_distinguishes_error_status(env):
    # Una fila vigente `error` se marca como tal (no como éxito).
    with env["maker"]() as session:
        session.add(AIExtraction(
            conversation_id="CONV-1", lead_id="LD-1", provider="local",
            model_name="qwen2.5:3b", prompt_version="v7", schema_version="v1",
            status="error", error="x", input_hash="h-err",
            fields=None, is_current=True))
        session.commit()
    client = env["make_client"]("sup@x")
    html = client.get("/supervision?ai=1&ai_ids=CONV-1").text
    assert "Ver analizadas (1)" in html
    assert "(con error)" in html


