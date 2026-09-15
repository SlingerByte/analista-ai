from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.auth import _set_session
from app.config import Settings, validate_startup_configuration
from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_real_secret_key():
    for insecure in ("change-me-in-production", "dev-insecure-change-me", "", "secret"):
        with pytest.raises(RuntimeError):
            validate_startup_configuration(
                Settings(app_env="production", secret_key=insecure)
            )


def test_production_with_real_secret_key_passes():
    validate_startup_configuration(
        Settings(app_env="production", secret_key="a-long-random-production-secret-123")
    )


def test_development_does_not_require_real_secret_key():
    validate_startup_configuration(
        Settings(app_env="development", secret_key="dev-insecure-change-me")
    )


def test_cookie_is_secure_in_production(monkeypatch):
    production = Settings(app_env="production", secret_key="x" * 40)
    monkeypatch.setattr(auth_module, "get_settings", lambda: production)

    response = RedirectResponse(url="/", status_code=303)
    _set_session(response, user_id=1)
    header = response.headers["set-cookie"]
    assert "Secure" in header
    assert "HttpOnly" in header


def test_cookie_is_not_secure_in_development(monkeypatch):
    development = Settings(app_env="development", secret_key="dev-secret")
    monkeypatch.setattr(auth_module, "get_settings", lambda: development)

    response = RedirectResponse(url="/", status_code=303)
    _set_session(response, user_id=1)
    assert "Secure" not in response.headers["set-cookie"]


def test_health_returns_only_safe_fields():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert set(body) <= {"status", "database", "ai_provider"}
    rendered = str(body).lower()
    for needle in ("postgresql", "secret", "api_key", "password", "openrouter_api_key"):
        assert needle not in rendered


def test_deployment_config_runs_migrations_before_start():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    render = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "alembic upgrade head" in dockerfile
    assert "healthCheckPath" in render
    assert "APP_ENV" in render and "production" in render
    assert "DATABASE_URL" in render
    assert "SECRET_KEY" in render
    assert "OPENROUTER_API_KEY" in render
