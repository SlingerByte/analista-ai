"""Contrato del Local AI Agent (aditivo): `messages`/`format` y modo `text`."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import scripts.local_ai_agent as agent


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers: dict = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _client(monkeypatch, captured: dict, reply: dict) -> TestClient:
    def _urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8")) \
            if request.data else None
        return _FakeResponse(reply)

    monkeypatch.setattr(agent.urllib.request, "urlopen", _urlopen)
    return TestClient(agent.build_app("http://127.0.0.1:11434", "qwen2.5:3b"))


def test_health_reports_ollama(monkeypatch):
    captured: dict = {}
    client = _client(monkeypatch, captured, {"models": []})
    body = client.get("/health").json()
    assert body == {"status": "ok", "ollama": True, "model": "qwen2.5:3b"}


def test_analyze_messages_uses_chat_and_forwards_format(monkeypatch):
    captured: dict = {}
    client = _client(monkeypatch, captured,
                     {"message": {"content": '{"model_interes": null}'}})
    res = client.post("/analyze", json={
        "messages": [{"role": "system", "content": "sys"},
                     {"role": "user", "content": "usr"}],
        "format": {"type": "object"},
        "model": "qwen2.5:3b",
    })
    body = res.json()
    assert body["ok"] is True
    assert body["result"] == '{"model_interes": null}'
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["messages"][0]["content"] == "sys"
    assert captured["body"]["format"] == {"type": "object"}


def test_analyze_text_mode_still_works(monkeypatch):
    captured: dict = {}
    client = _client(monkeypatch, captured, {"response": "respuesta libre"})
    res = client.post("/analyze", json={"text": "De contado, la pago de contado."})
    body = res.json()
    assert body["ok"] is True
    assert body["result"] == "respuesta libre"
    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["prompt"] == "De contado, la pago de contado."


def test_analyze_without_input_is_controlled_error(monkeypatch):
    captured: dict = {}
    client = _client(monkeypatch, captured, {})
    body = client.post("/analyze", json={}).json()
    assert body["ok"] is False
    assert "text" in body["error"] and "messages" in body["error"]
