from __future__ import annotations

import time

from app.ai.base import AIRequestError, BaseHTTPExtractor
from app.ai.prompt import build_messages
from app.ai.schema import ConversationInput

DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# Política de reintentos del proveedor: como máximo UN reintento ante errores
# transitorios (429 / 5xx / fallo de red), nunca más. Límite superior fijo para
# no bloquear el pipeline si el servidor pide una espera larga.
DEFAULT_RETRY_DELAY_S = 2.0
MAX_RETRY_DELAY_S = 30.0

_TRANSIENT_HTTP = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")


def _is_transient(message: str | None) -> bool:
    """¿Merece el error un único reintento? Función pura (testeable)."""
    if not message:
        return False
    if any(marker in message for marker in _TRANSIENT_HTTP):
        return True
    lowered = message.lower()
    return "network error" in lowered or "timeout" in lowered or "timed out" in lowered


def _retry_delay_s(headers: dict[str, str] | None, default: float = DEFAULT_RETRY_DELAY_S,
                   cap: float = MAX_RETRY_DELAY_S) -> float:
    """Espera antes del único reintento. Respeta `Retry-After` (segundos) con tope.

    Función pura (testeable). Si el header falta o no es numérico (p. ej. fecha
    HTTP), usa el default. Siempre acotado a [0, cap].
    """
    raw = (headers or {}).get("retry-after")
    try:
        delay = float(str(raw).strip()) if raw is not None else default
    except (TypeError, ValueError):
        delay = default
    return max(0.0, min(delay, cap))


class GroqExtractor(BaseHTTPExtractor):
    provider = "groq"

    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        base_url: str,
        timeout: float,
    ) -> None:
        super().__init__(model=model, timeout=timeout)
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def availability(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GROQ_API_KEY not configured"
        if not self.model:
            return False, "GROQ_MODEL not configured"
        return True, "ok"

    def _headers(self) -> dict:
        # Nota de compatibilidad (solo Groq): el edge rechaza el User-Agent por
        # defecto de urllib (`Python-urllib/*`, HTTP 403 code 1010). Se envía un
        # User-Agent neutro de aplicación; no toca a Ollama/OpenRouter.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "analista-ia/1.0",
        }

    def _post_chat(self, conversation: ConversationInput) -> str:
        # Mismo contrato que OpenRouter: JSON mode genérico (`json_object`) y la
        # validación estricta la hace nuestro Pydantic (`_validate_content`).
        # No se usa `json_schema`/strict del proveedor para no acoplar el
        # schema propio al subconjunto de modelos que lo soportan.
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

    def _call(self, conversation: ConversationInput) -> str:
        try:
            return self._post_chat(conversation)
        except AIRequestError as exc:
            # Un único reintento ante errores transitorios; cualquier otro
            # fallo (4xx no-429, respuesta sin choices, etc.) se propaga tal
            # cual y `extract()` lo convierte en error controlado.
            if not _is_transient(str(exc)):
                raise
            time.sleep(_retry_delay_s(self.last_response_headers))
            return self._post_chat(conversation)
