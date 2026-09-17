from __future__ import annotations

import json

import pytest

import app.ai.local as local_module
from app.ai.base import AIRequestError
from app.ai.factory import (
    AIProviderConfigError,
    build_extractor,
    validate_ai_configuration,
)
from app.ai.local import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, LocalExtractor
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schema import ConversationInput, Message
from app.config import Settings


def _conversation() -> ConversationInput:
    return ConversationInput(
        conversation_id="CONV-1",
        messages=[Message(sender="cliente", text="De contado, la pago de contado.")],
    )


def _settings(**overrides) -> Settings:
    base = {"ai_provider": "local", "ai_timeout_seconds": 5.0}
    base.update(overrides)
    return Settings(**base)


def _extractor(model: str | None = DEFAULT_MODEL) -> LocalExtractor:
    return LocalExtractor(DEFAULT_OLLAMA_URL, model, 5.0)


# --- Disponibilidad amigable (A: ok, B: sin Ollama, C: sin modelo) -------------


def test_availability_ok_when_ollama_and_model_present(monkeypatch):
    extractor = _extractor()
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"models": [{"name": "qwen2.5:3b"}]})
    assert extractor.availability() == (True, "ok")


def test_availability_missing_model_config(monkeypatch):
    extractor = _extractor(model=None)
    available, reason = extractor.availability()
    assert available is False
    assert "LOCAL_AI_MODEL" in reason


def test_availability_ollama_not_installed_is_friendly(monkeypatch):
    extractor = _extractor()

    def _raise(*args, **kwargs):
        raise AIRequestError("network error: URLError")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    monkeypatch.setattr(local_module.shutil, "which", lambda _name: None)
    available, reason = extractor.availability()
    assert available is False
    assert "IA local no disponible" in reason
    assert "Ollama no está disponible" in reason
    # Nunca expone el detalle técnico.
    assert "URLError" not in reason
    assert "unreachable" not in reason
    assert "Traceback" not in reason


def test_availability_ollama_installed_but_not_running(monkeypatch):
    extractor = _extractor()

    def _raise(*args, **kwargs):
        raise AIRequestError("network error: URLError")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    monkeypatch.setattr(local_module.shutil, "which",
                        lambda _name: "C:/ollama/ollama.exe")
    available, reason = extractor.availability()
    assert available is False
    assert "instalado pero no está en ejecución" in reason
    assert "URLError" not in reason


def test_availability_model_not_pulled(monkeypatch):
    extractor = _extractor()
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"models": [{"name": "llama3.2:3b"}]})
    available, reason = extractor.availability()
    assert available is False
    assert "Modelo local no disponible" in reason
    assert "qwen2.5:3b" in reason
    assert "ollama pull qwen2.5:3b" in reason


def test_availability_unexpected_error_is_friendly(monkeypatch):
    extractor = _extractor()

    def _raise(*args, **kwargs):
        raise RuntimeError("boom interno")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    available, reason = extractor.availability()
    assert available is False
    assert "IA local no disponible" in reason
    assert "RuntimeError" not in reason


# --- Extracción directa contra Ollama ------------------------------------------


def test_local_call_uses_ollama_chat(monkeypatch):
    extractor = _extractor()
    captured = {}

    def _capture(method, url, payload=None, headers=None):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"message": {"content": '{"model_interes": null}'}}

    monkeypatch.setattr(extractor, "_request_json", _capture)
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True
    assert outcome.provider == "local"
    assert captured["method"] == "POST"
    assert captured["url"] == f"{DEFAULT_OLLAMA_URL}/api/chat"
    assert captured["payload"]["messages"][0]["content"] == SYSTEM_PROMPT
    assert captured["payload"]["options"]["temperature"] == 0
    schema = captured["payload"]["format"]
    assert schema.get("type") == "object"
    assert "objecion" in schema.get("properties", {})


def test_local_extract_valid_json(monkeypatch):
    extractor = _extractor()
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"message": {"content": json.dumps(
            {"forma_pago": "contado", "forma_pago_evidence": "de contado"})}})
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.result.forma_pago == "contado"


def test_local_extract_invalid_json(monkeypatch):
    extractor = _extractor()
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"message": {"content": "no es json"}})
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert "invalid JSON" in outcome.error


def test_local_extract_transport_error_is_controlled(monkeypatch):
    extractor = _extractor()

    def _raise(*args, **kwargs):
        raise AIRequestError("network error: URLError")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert outcome.provider == "local"
    assert "network error" in outcome.error


# --- Factory / configuración ---------------------------------------------------


def test_factory_builds_local_direct_to_ollama():
    extractor = build_extractor("local", _settings())
    assert isinstance(extractor, LocalExtractor)
    assert extractor.provider == "local"
    assert extractor.model == DEFAULT_MODEL
    assert extractor.base_url == DEFAULT_OLLAMA_URL


def test_factory_local_uses_configured_ollama_url_and_model():
    extractor = build_extractor(
        "local",
        _settings(local_ai_ollama_url="http://127.0.0.1:9999/",
                  local_ai_model="llama3.2:3b"))
    assert extractor.base_url == "http://127.0.0.1:9999"
    assert extractor.model == "llama3.2:3b"


def test_local_is_known_provider():
    from app.ai.factory import KNOWN_PROVIDERS
    assert "local" in KNOWN_PROVIDERS


def test_production_rejects_local():
    with pytest.raises(AIProviderConfigError, match="no está permitido"):
        validate_ai_configuration(
            _settings(app_env="production", ai_provider="local")
        )
