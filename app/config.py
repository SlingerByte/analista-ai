from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENVS = frozenset({"production", "prod"})

# Valores que no son aceptables como SECRET_KEY real de producción.
INSECURE_SECRET_KEYS = frozenset(
    {
        "",
        "dev-insecure-change-me",
        "change-me-in-production",
        "changeme",
        "secret",
        "test-secret",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Analista IA - Priorizacion inteligente de leads"
    app_env: str = "development"
    secret_key: str = "dev-insecure-change-me"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/analista_ia"
    port: int = 8000

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Fuerza el driver psycopg 3 (`postgresql+psycopg://`).

        Supabase/Render entregan la URL como `postgres://` o `postgresql://`;
        sin normalizar, SQLAlchemy intentaría `psycopg2` (no instalado). Solo
        reescribe el esquema; no toca host, credenciales ni parámetros.
        """
        url = (value or "").strip()
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    # Usuarios demo (solo desarrollo). Las contraseñas pueden sobreescribirse
    # por entorno (ADVISOR_DEMO_PASSWORD, etc.); en la DB solo vive el hash.
    advisor_demo_email: str = "advisor.demo@motos.local"
    advisor_demo_password: str = "demo-asesor-123"
    advisor_demo_advisor_id: str = "AS-001"
    supervisor_demo_email: str = "supervisor.demo@motos.local"
    supervisor_demo_password: str = "demo-supervisor-123"
    admin_demo_email: str = "admin.demo@motos.local"
    admin_demo_password: str = "demo-admin-123"

    ai_provider: str = "ollama"
    ai_timeout_seconds: float = 60.0
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    groq_api_key: str | None = None
    groq_model: str | None = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    local_ai_agent_url: str = "http://127.0.0.1:8765"
    local_ai_model: str | None = "qwen2.5:3b"
    # Endpoint de Ollama para el proveedor `local` (mismo equipo).
    local_ai_ollama_url: str = "http://127.0.0.1:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_production(settings: Settings) -> bool:
    return (settings.app_env or "").strip().lower() in PRODUCTION_ENVS


def validate_startup_configuration(settings: Settings) -> None:
    """Fallar al arrancar si falta configuración obligatoria de producción."""
    if is_production(settings) and (settings.secret_key or "").strip() in INSECURE_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY insegura para producción: configure un valor aleatorio y "
            "secreto (p. ej. `uv run python -c \"from app.auth import fresh_secret; "
            "print(fresh_secret())\"`)."
        )
