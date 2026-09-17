"""Extracción ejecutada en el navegador (Ollama local) + replay en el backend.

El navegador del usuario ejecuta Ollama en su equipo (``127.0.0.1:11434``) y
devuelve el JSON estructurado. Este adaptador permite reutilizar TODA la lógica
existente de ``process_conversation`` (validación determinista de evidencia,
idempotencia por ``input_hash``, ``is_current``, persistencia y, aguas abajo,
scoring) sin duplicarla ni abrir un segundo camino de escritura.

El backend NUNCA llama a Ollama en este flujo; solo valida y persiste el
resultado que produjo el navegador.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.ai.base import ExtractionOutcome
from app.ai.schema import ConversationInput, ExtractionResult

# Proveedor registrado en ``ai_extractions`` para extracciones de Ollama
# ejecutadas en el navegador del usuario (mismo motor que el Ollama local).
BROWSER_PROVIDER = "ollama"


class BrowserOllamaReplay:
    """Extractor de un solo uso que reproduce un resultado ya calculado.

    Cumple el protocolo ``AIExtractor`` para poder pasarse a
    ``process_conversation`` sin cambios en el pipeline de persistencia.
    """

    provider = BROWSER_PROVIDER

    def __init__(self, model: str | None, result: ExtractionResult) -> None:
        self.model = model or None
        self._result = result

    def availability(self) -> tuple[bool, str]:
        return True, "ok"

    def extract(self, conversation: ConversationInput) -> ExtractionOutcome:
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=0,
            result=self._result,
        )


def parse_browser_result(payload) -> ExtractionResult:
    """Valida el JSON del navegador con el MISMO schema v1 de la aplicación.

    Lanza ``pydantic.ValidationError`` si no cumple el schema; el llamador
    decide cómo reportarlo de forma segura.
    """
    return ExtractionResult.model_validate(payload)


__all__ = ["BROWSER_PROVIDER", "BrowserOllamaReplay", "parse_browser_result",
           "ValidationError"]
