"""Proveedor `local`: habla con el Local AI Agent (127.0.0.1) que reenvía a Ollama.

Reutiliza exactamente el mismo `SYSTEM_PROMPT` (`build_messages`), el mismo
`schema` (`ExtractionResult.model_json_schema`) y la misma validación que
Groq/Ollama/OpenRouter: aquí solo se resuelve el transporte HTTP.

Flujo:
    LocalExtractor -> POST {url}/analyze (messages + format) -> Local AI Agent
        -> Ollama /api/chat -> JSON estructurado -> _validate_content()

El agente es un proxy tonto; el prompt, el schema y la validación viven en la
app. No expone Ollama directamente.
"""

from __future__ import annotations

from app.ai.base import AIRequestError, BaseHTTPExtractor
from app.ai.prompt import build_messages
from app.ai.schema import ConversationInput, ExtractionResult

DEFAULT_AGENT_URL = "http://127.0.0.1:8765"
DEFAULT_MODEL = "qwen2.5:3b"


class LocalExtractor(BaseHTTPExtractor):
    provider = "local"

    def __init__(self, base_url: str, model: str | None, timeout: float) -> None:
        super().__init__(model=model, timeout=timeout)
        self.base_url = (base_url or DEFAULT_AGENT_URL).rstrip("/")

    def availability(self) -> tuple[bool, str]:
        if not self.model:
            return False, "LOCAL_AI_MODEL not configured"
        try:
            data = self._request_json("GET", f"{self.base_url}/health")
        except AIRequestError as exc:
            return False, f"local agent unreachable: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"local agent unreachable: {type(exc).__name__}"
        if data.get("status") != "ok":
            return False, "local agent unhealthy"
        if data.get("ollama") is not True:
            return False, f"ollama not available: {data.get('ollama')}"
        return True, "ok"

    def _call(self, conversation: ConversationInput) -> str:
        payload = {
            "messages": build_messages(conversation),
            "format": ExtractionResult.model_json_schema(),
            "model": self.model,
        }
        data = self._request_json(
            "POST", f"{self.base_url}/analyze", payload)
        if data.get("ok") is not True:
            raise AIRequestError(
                f"agent error: {data.get('error') or 'unknown'}")
        return data.get("result") or ""


__all__ = ["LocalExtractor", "DEFAULT_AGENT_URL", "DEFAULT_MODEL"]
