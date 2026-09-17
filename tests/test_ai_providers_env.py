"""Proveedores IA según entorno y seguridad del resumen de errores."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import get_session as auth_get_session
from app.auth import hash_password
from app.config import Settings
from app.dashboard import _configured_ai_providers, _safe_error_summary, get_session
from app.db import Base
from app.main import app
from app.models import Advisor, Company, PointOfSale, User


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="development",
        secret_key="x" * 40,
        database_url="sqlite+pysqlite:///:memory:",
        ai_provider="openrouter",
        openrouter_api_key=None,
        openrouter_model=None,
        groq_api_key=None,
        groq_model=None,
    )
    base.update(overrides)
    return Settings(**base)


def _values(settings: Settings) -> list[str]:
    return [p["value"] for p in _configured_ai_providers(settings)]


# --- Proveedores por entorno --------------------------------------------------


def test_desarrollo_muestra_local_y_remoto_configurado():
    values = _values(_settings(app_env="development", openrouter_api_key="k",
                               openrouter_model="m"))
    assert "local" in values
    assert "openrouter" in values
    assert "groq" not in values


def test_produccion_no_muestra_local():
    values = _values(_settings(app_env="production", openrouter_api_key="k",
                               openrouter_model="m"))
    assert "local" not in values
    assert values == ["openrouter"]


def test_produccion_muestra_openrouter_si_configurado():
    assert "openrouter" in _values(_settings(app_env="production",
                                             openrouter_api_key="k",
                                             openrouter_model="m"))


def test_produccion_muestra_groq_si_configurado():
    values = _values(_settings(app_env="production", groq_api_key="g",
                               groq_model="gm"))
    assert values == ["groq"]


def test_ausencia_de_groq_no_rompe_openrouter():
    values = _values(_settings(app_env="production", openrouter_api_key="k",
                               openrouter_model="m", groq_api_key=None))
    assert "openrouter" in values
    assert "groq" not in values


# --- Seguridad del resumen de errores ----------------------------------------


def test_safe_error_summary_redacta_secretos_y_colapsa():
    summary = _safe_error_summary([
        {"error": "HTTP 429: rate limit Bearer sk-abc123XYZ api_key=supersecreto\n"
                  "stack trace: File \"/x.py\" y mas"},
    ])
    assert "429" in summary
    assert "sk-abc123XYZ" not in summary
    assert "supersecreto" not in summary
    assert "\n" not in summary
    assert "Bearer ***" in summary


# --- Endpoint: producción rechaza 'local' enviado manualmente -----------------

PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture()
def client(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'provs.db'}")
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


def _login(client):
    response = client.post("/login", data={"email": "admin@x", "password": PASSWORD})
    assert response.status_code in (200, 303)
    return client


def test_produccion_no_permite_local_por_http(client, monkeypatch):
    monkeypatch.setattr(
        "app.dashboard.get_settings",
        lambda: _settings(app_env="production", openrouter_api_key="k",
                          openrouter_model="m"),
    )
    _login(client)
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"},
                           follow_redirects=False)
    assert response.status_code == 400


def test_produccion_permite_remoto_configurado_por_http(client, monkeypatch):
    monkeypatch.setattr(
        "app.dashboard.get_settings",
        lambda: _settings(app_env="production", openrouter_api_key="k",
                          openrouter_model="m"),
    )
    _login(client)
    response = client.post("/supervision/run-ai",
                           data={"provider": "openrouter", "limit": "1"},
                           follow_redirects=False)
    # Sin conversaciones pendientes → redirect (no 400 de proveedor).
    assert response.status_code == 303


# --- Éxito del análisis actualiza el score (extractor fake, sin red) ----------


class FakeProviderExtractor:
    provider = "fake"
    model = "fake-1"

    def availability(self):
        return True, "ok"

    def extract(self, conversation):
        from app.ai.base import ExtractionOutcome
        from app.ai.schema import ExtractionResult

        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider, model=self.model,
            success=True, schema_valid=True, latency_ms=1,
            result=ExtractionResult(model_interes="Honda Navi",
                                    model_interes_evidence="me interesa la Honda Navi"),
        )


@pytest.fixture()
def rescore_client(tmp_path):
    from app.models import Conversation, Lead

    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'rescore.db'}")
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
        session.add(Conversation(conversation_id="CONV-01", lead_id="LD-01",
                                 company_id="EMP-01", status="linked",
                                 messages=[{"seq": 1, "sender": "cliente",
                                            "hour": "", "text": "me interesa la Honda Navi"}]))
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


def test_run_ai_success_updates_lead_score(rescore_client, monkeypatch):
    from app.models import LeadScore

    client, maker = rescore_client
    monkeypatch.setattr("app.dashboard.build_extractor",
                        lambda provider, settings: FakeProviderExtractor())
    _login(client)
    response = client.post("/supervision/run-ai",
                           data={"provider": "local", "limit": "1"},
                           follow_redirects=False)
    assert response.status_code == 303
    with maker() as session:
        score = session.scalar(
            sa.select(LeadScore).where(LeadScore.lead_id == "LD-01",
                                       LeadScore.is_current.is_(True)))
        assert score is not None
