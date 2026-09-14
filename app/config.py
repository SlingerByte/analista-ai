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
