from __future__ import annotations

import json

import pytest

from app.ai.base import AIRequestError
from app.ai.factory import UnknownProviderError, build_extractor
from app.ai.ollama import OllamaExtractor
from app.ai.openrouter import OpenRouterExtractor
from app.ai.schema import ConversationInput, Message
from app.config import Settings


def _conversation() -> ConversationInput:
    return ConversationInput(
        conversation_id="CONV-1",
        messages=[Message(sender="cliente", text="Me interesa la XRE, manejan financiación?")],
    )


def _settings(**overrides) -> Settings:
    base = {"ai_provider": "ollama", "ai_timeout_seconds": 5.0}
    base.update(overrides)
    return Settings(**base)


def test_factory_unknown_provider_raises():
    with pytest.raises(UnknownProviderError):
        build_extractor("unknown", _settings())


def test_factory_builds_ollama():
    extractor = build_extractor(
        "ollama", _settings(ollama_model="llama3.2", ollama_base_url="http://localhost:11434")
    )
    assert isinstance(extractor, OllamaExtractor)
    assert extractor.model == "llama3.2"


def test_factory_builds_openrouter():
    extractor = build_extractor(
        "openrouter", _settings(openrouter_api_key="k", openrouter_model="m")
    )
    assert isinstance(extractor, OpenRouterExtractor)
    assert extractor.model == "m"


def test_ollama_availability_without_model():
    extractor = OllamaExtractor("http://localhost:11434", None, 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert "OLLAMA_MODEL" in reason


def test_ollama_availability_when_unreachable(monkeypatch):
    extractor = OllamaExtractor("http://localhost:11434", "llama3.2", 5.0)

    def _raise(*args, **kwargs):
        raise AIRequestError("network error: URLError")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    available, reason = extractor.availability()
    assert available is False
    assert "unreachable" in reason


def test_ollama_availability_with_model_pulled(monkeypatch):
    extractor = OllamaExtractor("http://localhost:11434", "llama3.2", 5.0)
    monkeypatch.setattr(
        extractor, "_request_json", lambda *a, **k: {"models": [{"name": "llama3.2:latest"}]}
    )
    assert extractor.availability() == (True, "ok")


def test_ollama_extract_handles_transport_error(monkeypatch):
    extractor = OllamaExtractor("http://localhost:11434", "llama3.2", 5.0)

    def _raise(*args, **kwargs):
        raise AIRequestError("HTTP 500: server error")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert outcome.schema_valid is False
    assert "HTTP 500" in outcome.error


def test_openrouter_availability_requires_key():
    extractor = OpenRouterExtractor(None, "m", "https://openrouter.ai/api/v1", 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert reason == "OPENROUTER_API_KEY not configured"


def test_openrouter_availability_requires_model():
    extractor = OpenRouterExtractor("secret", None, "https://openrouter.ai/api/v1", 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert reason == "OPENROUTER_MODEL not configured"


def test_openrouter_missing_key_never_leaks(monkeypatch):
    extractor = OpenRouterExtractor("super-secret-key", None, "https://openrouter.ai/api/v1", 5.0)
    available, reason = extractor.availability()
    assert "super-secret-key" not in reason

    def _raise(*args, **kwargs):
        raise AIRequestError("HTTP 401: unauthorized")

    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert "super-secret-key" not in (outcome.error or "")


def test_openrouter_extract_parses_valid_json(monkeypatch):
    extractor = OpenRouterExtractor("k", "free-model", "https://openrouter.ai/api/v1", 5.0)
    payload = {
        "model_interes": "XRE",
        "model_interes_evidence": "me interesa la XRE",
        "forma_pago": "financiacion",
        "forma_pago_evidence": "manejan financiacion",
    }
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda *a, **k: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True
    assert outcome.result.model_interes == "XRE"
    assert outcome.result.forma_pago == "financiacion"


def test_openrouter_extract_invalid_json_is_failure(monkeypatch):
    extractor = OpenRouterExtractor("k", "free-model", "https://openrouter.ai/api/v1", 5.0)
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda *a, **k: {"choices": [{"message": {"content": "not a json"}}]},
    )
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert outcome.schema_valid is False
    assert "invalid JSON" in outcome.error


def test_openrouter_extract_schema_invalid(monkeypatch):
    extractor = OpenRouterExtractor("k", "free-model", "https://openrouter.ai/api/v1", 5.0)
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda *a, **k: {"choices": [{"message": {"content": '{"forma_pago": "crypto"}'}}]},
    )
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is False
    assert "schema validation failed" in outcome.error
    assert outcome.result is None


def test_ollama_sends_json_schema_format(monkeypatch):
    from app.ai.ollama import structured_format

    extractor = OllamaExtractor("http://localhost:11434", "llama3.2", 5.0)
    captured = {}

    def _capture(method, url, payload=None, headers=None):
        captured["payload"] = payload
        return {"message": {"content": json.dumps({"model_interes": None})}}

    monkeypatch.setattr(extractor, "_request_json", _capture)
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True

    schema = structured_format()
    assert schema.get("type") == "object"
    assert "objecion" in schema.get("properties", {})
    sent_format = captured["payload"]["format"]
    assert isinstance(sent_format, dict)
    assert sent_format == schema


def test_openrouter_list_free_models(monkeypatch):
    extractor = OpenRouterExtractor("k", "m", "https://openrouter.ai/api/v1", 5.0)
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda *a, **k: {
            "data": [
                {"id": "free/one", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "paid/two", "pricing": {"prompt": "0.5", "completion": "1"}},
            ]
        },
    )
    assert extractor.list_free_models() == ["free/one"]
