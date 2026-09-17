"""Proveedor `local`: IA local vía Ollama directo (mismo equipo).

Preferimos FastAPI → Ollama → qwen2.5:3b, sin exigir levantar manualmente el
Local AI Agent. Reutiliza `OllamaExtractor` (mismo `SYSTEM_PROMPT`, schema y
validación); aquí solo se añade un diagnóstico amigable de disponibilidad.

    LocalExtractor -> Ollama /api/chat -> JSON estructurado -> _validate_content()

Estados amigables (nunca exponen URLError/traceback):
- Ollama no disponible (no instalado o no en ejecución).
- Ollama instalado pero no en ejecución.
- Modelo local no instalado (con la instrucción `ollama pull <modelo>`).

El agente `scripts/local_ai_agent.py` se mantiene para el escenario de
navegador/publicación; el backend no lo necesita.
"""

from __future__ import annotations

import shutil

from app.ai.base import AIRequestError
from app.ai.ollama import OllamaExtractor

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"


class LocalExtractor(OllamaExtractor):
    """Ollama local con mensajes de disponibilidad orientados al usuario."""

    provider = "local"

    def availability(self) -> tuple[bool, str]:
        if not self.model:
            return False, "IA local no configurada: falta LOCAL_AI_MODEL."
        try:
            data = self._request_json("GET", f"{self.base_url}/api/tags")
        except AIRequestError:
            if shutil.which("ollama"):
                return False, (
                    "Ollama está instalado pero no está en ejecución. "
                    "Inícialo para usar IA local."
                )
            return False, (
                "IA local no disponible: Ollama no está disponible en este "
                "equipo. Instala Ollama o inicia el servicio para usar IA local."
            )
        except Exception:  # noqa: BLE001 - diagnóstico, nunca propaga el detalle
            return False, "IA local no disponible en este equipo."

        names = {item.get("name") for item in data.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return False, (
                f"Modelo local no disponible: el modelo {self.model} no está "
                f"instalado. Ejecuta: ollama pull {self.model}"
            )
        return True, "ok"


__all__ = ["LocalExtractor", "DEFAULT_OLLAMA_URL", "DEFAULT_MODEL"]
