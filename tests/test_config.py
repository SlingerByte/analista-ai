"""Normalización de DATABASE_URL para el driver psycopg 3."""

from __future__ import annotations

from app.config import Settings


def test_postgres_scheme_normalizada_a_psycopg():
    assert Settings(database_url="postgres://u:p@h:5432/d").database_url.startswith(
        "postgresql+psycopg://")
    assert Settings(database_url="postgresql://u:p@h:5432/d").database_url.startswith(
        "postgresql+psycopg://")


def test_driver_explicito_y_sqlite_no_se_tocan():
    assert (Settings(database_url="postgresql+psycopg://u:p@h/d").database_url
            == "postgresql+psycopg://u:p@h/d")
    assert (Settings(database_url="sqlite+pysqlite:///:memory:").database_url
            == "sqlite+pysqlite:///:memory:")
