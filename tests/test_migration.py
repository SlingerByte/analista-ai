from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "companies",
    "points_of_sale",
    "users",
    "catalog_items",
    "advisors",
    "pipeline_runs",
    "leads",
    "identity_clusters",
    "identity_members",
    "conversations",
    "ai_extractions",
    "lead_scores",
    "assignments",
}


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{db_path}")
    return config


def test_upgrade_downgrade_and_metadata_match(tmp_path, monkeypatch):
    from app.config import get_settings

    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    get_settings.cache_clear()

    try:
        config = _alembic_config(db_path)
        engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")

        command.upgrade(config, "head")
        tables_after_upgrade = set(sa.inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables_after_upgrade

        command.check(config)

        command.downgrade(config, "base")
        tables_after_downgrade = set(sa.inspect(engine).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)

        engine.dispose()
    finally:
        get_settings.cache_clear()
