from __future__ import annotations

import json

import pytest

from app.ai.base import AIRequestError
from app.ai.factory import (
    AIProviderConfigError,
    build_extractor,
    validate_ai_configuration,
)
from app.ai.local import DEFAULT_AGENT_URL, DEFAULT_MODEL, LocalExtractor
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schema import ConversationInput, ExtractionResult, Message
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


def _ok_payload(result: str = '{"model_interes": null}') -> dict:
    return {"ok": True, "model": "qwen2.5:3b", "result": result}


def test_local_availability_requires_model():
    extractor = LocalExtractor(DEFAULT_AGENT_URL, None, 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert "LOCAL_AI_MODEL" in reason


def test_local_availability_when_agent_unreachable(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)

    def _raise(*args, **kwargs):
        raise AIRequestError("network error: URLError")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    available, reason = extractor.availability()
    assert available is False
    assert "unreachable" in reason


def test_local_availability_when_ollama_down(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"status": "ok", "ollama": "no disponible: URLError",
                         "model": "qwen2.5:3b"})
    available, reason = extractor.availability()
    assert available is False
    assert "ollama not available" in reason


def test_local_availability_ok(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"status": "ok", "ollama": True, "model": "qwen2.5:3b"})
    assert extractor.availability() == (True, "ok")


def test_local_call_sends_messages_and_schema(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    captured = {}

    def _capture(method, url, payload=None, headers=None):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return _ok_payload()

    monkeypatch.setattr(extractor, "_request_json", _capture)
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True
    assert captured["method"] == "POST"
    assert captured["url"] == f"{DEFAULT_AGENT_URL}/analyze"
    # Reutiliza exactamente el mismo SYSTEM_PROMPT que Groq/Ollama.
    assert captured["payload"]["messages"][0]["content"] == SYSTEM_PROMPT
    assert captured["payload"]["model"] == "qwen2.5:3b"
    # El schema enviado es el de ExtractionResult (misma validación posterior).
    schema = captured["payload"]["format"]
    assert schema.get("type") == "object"
    assert "objecion" in schema.get("properties", {})


def test_local_extract_valid_json(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: _ok_payload(json.dumps(
            {"forma_pago": "contado", "forma_pago_evidence": "de contado"})))
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True
    assert outcome.result.forma_pago == "contado"
    assert outcome.provider == "local"


def test_local_extract_invalid_json(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: _ok_payload("no es json"))
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert "invalid JSON" in outcome.error


def test_local_extract_schema_invalid(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: _ok_payload('{"forma_pago": "crypto"}'))
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is False
    assert outcome.result is None


def test_local_extract_agent_error_is_controlled(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"ok": False, "model": "qwen2.5:3b",
                         "error": "RuntimeError: boom"})
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert "agent error" in outcome.error


def test_local_extract_transport_error(monkeypatch):
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)

    def _raise(*args, **kwargs):
        raise AIRequestError("HTTP 500: server error")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert "HTTP 500" in outcome.error


def test_local_never_leaks_credentials(monkeypatch):
    # El proveedor local no usa credenciales; aun así, ningún error debe
    # contener valores sensibles.
    extractor = LocalExtractor(DEFAULT_AGENT_URL, "qwen2.5:3b", 5.0)

    def _raise(*args, **kwargs):
        raise AIRequestError("HTTP 401: unauthorized")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert "secret" not in (outcome.error or "")


# --- Factory / configuración -------------------------------------------------


def test_factory_builds_local():
    extractor = build_extractor("local", _settings())
    assert isinstance(extractor, LocalExtractor)
    assert extractor.provider == "local"
    assert extractor.model == DEFAULT_MODEL
    assert extractor.base_url == DEFAULT_AGENT_URL


def test_factory_local_uses_configured_url_and_model():
    extractor = build_extractor(
        "local",
        _settings(local_ai_agent_url="http://127.0.0.1:9999/",
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
