from __future__ import annotations

from app.ai.base import AIRequestError, BaseHTTPExtractor
from app.ai.prompt import build_messages
from app.ai.schema import ConversationInput, ExtractionResult


def structured_format() -> dict:
    """JSON Schema (Pydantic) para el parámetro `format` de Ollama.

    Cambio aislado AI-1A: sin dependencias nuevas. Ollama acepta un objeto
    JSON Schema en `format` y restringe la salida a ese esquema.
    """
    return ExtractionResult.model_json_schema()


class OllamaExtractor(BaseHTTPExtractor):
    provider = "ollama"

    def __init__(self, base_url: str, model: str | None, timeout: float) -> None:
        super().__init__(model=model, timeout=timeout)
        self.base_url = base_url.rstrip("/")

    def availability(self) -> tuple[bool, str]:
        if not self.model:
            return False, "OLLAMA_MODEL not configured (set OLLAMA_MODEL to a local model)"
        try:
            data = self._request_json("GET", f"{self.base_url}/api/tags")
        except AIRequestError as exc:
            return False, f"ollama unreachable: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"ollama unreachable: {type(exc).__name__}"

        names = {item.get("name") for item in data.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return False, f"model not pulled: {self.model} (run: ollama pull {self.model})"
        return True, "ok"

    def _call(self, conversation: ConversationInput) -> str:
        payload = {
            "model": self.model,
            "messages": build_messages(conversation),
            "stream": False,
            "format": structured_format(),
            "options": {"temperature": 0},
        }
        data = self._request_json("POST", f"{self.base_url}/api/chat", payload)
        return data.get("message", {}).get("content") or ""
