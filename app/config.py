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


@lru_cache
def get_settings() -> Settings:
    return Settings()
