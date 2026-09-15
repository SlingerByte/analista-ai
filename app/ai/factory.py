from __future__ import annotations

from app.ai.base import AIExtractor
from app.ai.groq import GroqExtractor
from app.ai.ollama import OllamaExtractor
from app.ai.openrouter import OpenRouterExtractor
from app.config import Settings, get_settings, is_production

# Proveedores admitidos por la factory. Producción solo acepta proveedores
# remotos: un Ollama local no es una configuración válida de despliegue.
KNOWN_PROVIDERS = frozenset({"ollama", "openrouter", "groq"})
PRODUCTION_PROVIDERS = frozenset({"openrouter", "groq"})


class UnknownProviderError(ValueError):
    pass


class AIProviderConfigError(RuntimeError):
    """Configuración de IA inválida. El mensaje nunca contiene secretos."""


def resolve_provider(settings: Settings) -> str:
    return (settings.ai_provider or "").strip().lower()


def validate_ai_configuration(settings: Settings) -> None:
    """Valida la configuración de IA según el entorno.

    En desarrollo (por defecto) cualquier proveedor conocido es válido. En
    producción se exige un proveedor remoto configurado; si algo falta, se
    levanta ``AIProviderConfigError`` con el nombre de la variable, jamás su
    valor.
    """
    provider = resolve_provider(settings)

    if provider and provider not in KNOWN_PROVIDERS:
        raise AIProviderConfigError(
            "AI_PROVIDER desconocido: "
            f"{provider!r}. Proveedores válidos: {sorted(KNOWN_PROVIDERS)}."
        )

    if not is_production(settings):
        return

    if not provider:
        raise AIProviderConfigError(
            "APP_ENV=production requiere AI_PROVIDER configurado con un "
            "proveedor remoto (p. ej. openrouter o groq)."
        )
    if provider not in PRODUCTION_PROVIDERS:
        raise AIProviderConfigError(
            f"AI_PROVIDER={provider!r} no está permitido en producción; "
            "configure un proveedor remoto (openrouter o groq) y sus credenciales."
        )
    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise AIProviderConfigError(
                "OPENROUTER_API_KEY es obligatoria cuando "
                "AI_PROVIDER=openrouter en producción."
            )
        if not settings.openrouter_model:
            raise AIProviderConfigError(
                "OPENROUTER_MODEL es obligatorio cuando "
                "AI_PROVIDER=openrouter en producción."
            )
    if provider == "groq":
        if not settings.groq_api_key:
            raise AIProviderConfigError(
                "GROQ_API_KEY es obligatoria cuando "
                "AI_PROVIDER=groq en producción."
            )
        if not settings.groq_model:
            raise AIProviderConfigError(
                "GROQ_MODEL es obligatorio cuando "
                "AI_PROVIDER=groq en producción."
            )


def build_extractor(
    provider: str | None = None, settings: Settings | None = None
) -> AIExtractor:
    settings = settings or get_settings()
    resolved = (provider or resolve_provider(settings)).strip().lower()

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
    if resolved == "groq":
        return GroqExtractor(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            base_url=settings.groq_base_url,
            timeout=settings.ai_timeout_seconds,
        )
    raise UnknownProviderError(f"unknown AI_PROVIDER: {resolved!r}")
