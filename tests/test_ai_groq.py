from __future__ import annotations

import json

import pytest

from app.ai.base import AIRequestError
from app.ai.factory import (
    AIProviderConfigError,
    build_extractor,
    validate_ai_configuration,
)
from app.ai.groq import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MAX_RETRY_DELAY_S,
    GroqExtractor,
    _is_transient,
    _retry_delay_s,
)
from app.ai.schema import ConversationInput, Message
from app.config import Settings

_TEST_KEY = "test-key-123"


def _conversation() -> ConversationInput:
    return ConversationInput(
        conversation_id="CONV-1",
        messages=[Message(sender="cliente", text="Me interesa la XRE, manejan financiación?")],
    )


def _settings(**overrides) -> Settings:
    base = {"ai_provider": "groq", "ai_timeout_seconds": 5.0}
    base.update(overrides)
    return Settings(**base)


def _ok_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _no_sleep(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr("time.sleep", lambda s: calls.append(s))
    return calls


# --- 1 y 2. Request exitoso + JSON válido ------------------------------------


def test_groq_extract_success_valid_json(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "openai/gpt-oss-20b", DEFAULT_BASE_URL, 5.0)
    payload = {
        "model_interes": "XRE",
        "model_interes_evidence": "me interesa la XRE",
        "forma_pago": "financiacion",
        "forma_pago_evidence": "manejan financiacion",
    }
    monkeypatch.setattr(extractor, "_request_json", lambda *a, **k: _ok_response(payload))
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is True
    assert outcome.provider == "groq"
    assert outcome.model == "openai/gpt-oss-20b"
    assert isinstance(outcome.latency_ms, int)
    assert outcome.result.model_interes == "XRE"
    assert outcome.result.forma_pago == "financiacion"


def test_groq_sends_json_mode_payload(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    captured = {}
    def _capture(method, url, payload=None, headers=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return _ok_response({"model_interes": None})
    monkeypatch.setattr(extractor, "_request_json", _capture)
    assert extractor.extract(_conversation()).success is True
    assert captured["url"] == f"{DEFAULT_BASE_URL}/chat/completions"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["temperature"] == 0
    assert captured["headers"]["Authorization"] == f"Bearer {_TEST_KEY}"
    # Compatibilidad: el edge de Groq bloquea el UA por defecto de urllib.
    assert captured["headers"]["User-Agent"] == "analista-ia/1.0"


# --- 3. JSON inválido ----------------------------------------------------------


def test_groq_extract_invalid_json_is_failure(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"choices": [{"message": {"content": "not a json"}}]},
    )
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert outcome.schema_valid is False
    assert "invalid JSON" in outcome.error


def test_groq_extract_schema_invalid(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: {"choices": [{"message": {"content": '{"forma_pago": "crypto"}'}}]},
    )
    outcome = extractor.extract(_conversation())
    assert outcome.success is True
    assert outcome.schema_valid is False
    assert "schema validation failed" in outcome.error


# --- 4. HTTP 429: un único retry y error controlado ----------------------------


def test_groq_429_retries_once_then_controlled_error(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    sleeps = _no_sleep(monkeypatch)
    calls = []
    def _raise(*args, **kwargs):
        calls.append(1)
        raise AIRequestError("HTTP 429: rate limit exceeded")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert len(calls) == 2  # intento inicial + exactamente 1 retry
    assert len(sleeps) == 1
    assert outcome.success is False
    assert "429" in outcome.error


def test_groq_429_retry_then_success(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    _no_sleep(monkeypatch)
    state = {"n": 0}
    def _flaky(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise AIRequestError("HTTP 429: slow down")
        return _ok_response({"model_interes": None})
    monkeypatch.setattr(extractor, "_request_json", _flaky)
    outcome = extractor.extract(_conversation())
    assert state["n"] == 2
    assert outcome.success is True
    assert outcome.schema_valid is True


def test_groq_429_honors_retry_after_with_cap(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    sleeps = _no_sleep(monkeypatch)
    extractor.last_response_headers = {"retry-after": "7"}
    monkeypatch.setattr(
        extractor, "_request_json",
        lambda *a, **k: (_ for _ in ()).throw(AIRequestError("HTTP 429: slow")),
    )
    extractor.extract(_conversation())
    assert sleeps == [7.0]

    extractor.last_response_headers = {"retry-after": "3600"}
    sleeps.clear()
    extractor.extract(_conversation())
    assert sleeps == [MAX_RETRY_DELAY_S]


def test_groq_non_transient_error_does_not_retry(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    sleeps = _no_sleep(monkeypatch)
    calls = []
    def _raise(*args, **kwargs):
        calls.append(1)
        raise AIRequestError("HTTP 400: bad request")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert len(calls) == 1
    assert sleeps == []
    assert outcome.success is False


# --- 5. Timeout ----------------------------------------------------------------


def test_groq_timeout_is_controlled_error(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    _no_sleep(monkeypatch)
    def _raise(*args, **kwargs):
        raise AIRequestError("network error: TimeoutError")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert outcome.success is False
    assert outcome.schema_valid is False


# --- 6. HTTP 5xx -----------------------------------------------------------------


def test_groq_5xx_retries_once_then_controlled_error(monkeypatch):
    extractor = GroqExtractor(_TEST_KEY, "m", DEFAULT_BASE_URL, 5.0)
    _no_sleep(monkeypatch)
    calls = []
    def _raise(*args, **kwargs):
        calls.append(1)
        raise AIRequestError("HTTP 503: overloaded")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert len(calls) == 2
    assert outcome.success is False
    assert "503" in outcome.error


# --- 7. API key ausente ------------------------------------------------------------


def test_groq_availability_requires_key():
    extractor = GroqExtractor(None, "m", DEFAULT_BASE_URL, 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert reason == "GROQ_API_KEY not configured"


def test_groq_availability_requires_model():
    extractor = GroqExtractor("secret", None, DEFAULT_BASE_URL, 5.0)
    available, reason = extractor.availability()
    assert available is False
    assert reason == "GROQ_MODEL not configured"


# --- 8 y 9. Modelo y base URL configurables ------------------------------------------


def test_groq_default_model_is_documented():
    assert DEFAULT_MODEL == "openai/gpt-oss-20b"


def test_groq_factory_builds_with_settings_model():
    extractor = build_extractor(
        "groq", _settings(groq_api_key="k", groq_model="llama-3.3-70b-versatile")
    )
    assert isinstance(extractor, GroqExtractor)
    assert extractor.provider == "groq"
    assert extractor.model == "llama-3.3-70b-versatile"


def test_groq_factory_uses_default_model():
    extractor = build_extractor("groq", _settings(groq_api_key="k"))
    assert extractor.model == DEFAULT_MODEL


def test_groq_default_base_url_is_official():
    assert DEFAULT_BASE_URL == "https://api.groq.com/openai/v1"
    extractor = GroqExtractor("k", "m", DEFAULT_BASE_URL, 5.0)
    assert extractor.base_url == "https://api.groq.com/openai/v1"


def test_groq_base_url_configurable_and_normalized():
    extractor = build_extractor(
        "groq",
        _settings(groq_api_key="k", groq_model="m", groq_base_url="https://proxy.local/v1/"),
    )
    assert extractor.base_url == "https://proxy.local/v1"


# --- 10. La API key nunca se expone ---------------------------------------------------


def test_groq_key_never_leaks(monkeypatch):
    secret = "super-secret-live-key"
    extractor = GroqExtractor(secret, None, DEFAULT_BASE_URL, 5.0)
    _, reason = extractor.availability()
    assert secret not in reason

    def _raise(*args, **kwargs):
        raise AIRequestError("HTTP 401: unauthorized")
    monkeypatch.setattr(extractor, "_request_json", _raise)
    outcome = extractor.extract(_conversation())
    assert secret not in (outcome.error or "")
    assert secret not in (outcome.raw_text or "")


# --- Helpers puros ---------------------------------------------------------------------


def test_is_transient():
    assert _is_transient("HTTP 429: slow") is True
    assert _is_transient("HTTP 503: busy") is True
    assert _is_transient("network error: URLError") is True
    assert _is_transient("network error: TimeoutError") is True
    assert _is_transient("HTTP 400: bad request") is False
    assert _is_transient("response has no choices") is False
    assert _is_transient(None) is False


def test_retry_delay_parsing():
    assert _retry_delay_s({"retry-after": "5"}) == 5.0
    assert _retry_delay_s({}) == 2.0
    assert _retry_delay_s(None) == 2.0
    assert _retry_delay_s({"retry-after": "not-a-date"}) == 2.0
    assert _retry_delay_s({"retry-after": "9999"}) == MAX_RETRY_DELAY_S


# --- Factory / validación de producción --------------------------------------------------


def test_factory_builds_groq():
    extractor = build_extractor("groq", _settings(groq_api_key="k", groq_model="m"))
    assert isinstance(extractor, GroqExtractor)


def test_production_groq_requires_api_key():
    with pytest.raises(AIProviderConfigError, match="GROQ_API_KEY"):
        validate_ai_configuration(
            _settings(app_env="production", ai_provider="groq",
                      groq_api_key=None, groq_model="m")
        )


def test_production_groq_requires_model():
    with pytest.raises(AIProviderConfigError, match="GROQ_MODEL"):
        validate_ai_configuration(
            _settings(app_env="production", ai_provider="groq",
                      groq_api_key="secret-value", groq_model=None)
        )


def test_production_groq_with_key_and_model_is_valid():
    validate_ai_configuration(
        _settings(app_env="production", ai_provider="groq",
                  groq_api_key="secret-value", groq_model="m")
    )


def test_production_groq_error_never_leaks_secret():
    with pytest.raises(AIProviderConfigError) as excinfo:
        validate_ai_configuration(
            _settings(app_env="production", ai_provider="groq",
                      groq_api_key="secret-value", groq_model=None)
        )
    assert "secret-value" not in str(excinfo.value)
