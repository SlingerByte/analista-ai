from __future__ import annotations

from app.ai.base import AIRequestError, BaseHTTPExtractor
from app.ai.prompt import build_messages
from app.ai.schema import ConversationInput


class OpenRouterExtractor(BaseHTTPExtractor):
    provider = "openrouter"

    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        base_url: str,
        timeout: float,
    ) -> None:
        super().__init__(model=model, timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def availability(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENROUTER_API_KEY not configured"
        if not self.model:
            return False, "OPENROUTER_MODEL not configured"
        return True, "ok"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _call(self, conversation: ConversationInput) -> str:
        payload = {
            "model": self.model,
            "messages": build_messages(conversation),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        data = self._request_json(
            "POST",
            f"{self.base_url}/chat/completions",
            payload,
            self._headers(),
        )
        choices = data.get("choices") or []
        if not choices:
            raise AIRequestError("response has no choices")
        return choices[0].get("message", {}).get("content") or ""

    def list_free_models(self) -> list[str]:
        data = self._request_json("GET", f"{self.base_url}/models")
        free_models = []
        for item in data.get("data", []):
            pricing = item.get("pricing") or {}
            if pricing.get("prompt") in ("0", "0.0") and pricing.get("completion") in (
                "0",
                "0.0",
            ):
                free_models.append(item.get("id"))
        return free_models
