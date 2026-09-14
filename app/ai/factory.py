from __future__ import annotations

from app.ai.base import AIExtractor
from app.ai.ollama import OllamaExtractor
from app.ai.openrouter import OpenRouterExtractor
from app.config import Settings, get_settings


class UnknownProviderError(ValueError):
    pass


def build_extractor(
    provider: str | None = None, settings: Settings | None = None
) -> AIExtractor:
    settings = settings or get_settings()
    resolved = (provider or settings.ai_provider or "").strip().lower()

    if resolved == "ollama":
        return OllamaExtractor(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.ai_timeout_seconds,
        )
    if resolved == "openrouter":
        return OpenRouterExtractor(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            timeout=settings.ai_timeout_seconds,
        )
    raise UnknownProviderError(f"unknown AI_PROVIDER: {resolved!r}")
