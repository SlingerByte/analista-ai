from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
