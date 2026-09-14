from __future__ import annotations

import hashlib

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db import Base
from app.ingestion.loaders import DATA_DIR
from app.ingestion.normalizers import (
    is_valid_phone,
    normalize_city,
    normalize_phone,
)
from app.ingestion.service import run_ingestion
from app.models import Conversation, Lead, PipelineRun
from app.seed import seed

EXPECTED_FILE_HASHES = {
    "leads.csv": "b95c10b3106bc8f4b4a0d343f1e159e20df861fdd909b87fbd07c7dcf654bc2d",
    "catalogo_motos.csv": "1388ffa40ce57e51284aac0f79d0ad025f944baafa86ae4b4d714d75fa66f0ec",
    "asesores.csv": "55db5ae9a36cce6f338953e5edbf5a4760cafacd0bca578293251669679b6bb9",
    "historico_cierres.csv": "ce8e7fd93c3e00368c95e12b4a41f79c322951bd02b4f3608b962ee85682b244",
    "conversaciones.json": "e5f76c5548e7a432e9690251ffaccc4a55a5bd1f9f787883d282a5126eafb498",
    "LEEME.txt": "2aeef6aa0cee33565c8fe5bc0f035699cf8f20b9e1081e5904dbb62ae465257f",
}


@pytest.fixture(scope="module")
def ingestion(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("ingestion") / "ingestion.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        seed(session)
    with factory() as session:
        report = run_ingestion(session)

    yield engine, factory, report
    engine.dispose()


def _count(session, model) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model))


def _all_leads(factory) -> list[Lead]:
    with factory() as session:
        return list(session.scalars(sa.select(Lead)).all())


def test_files_are_read(ingestion):
    _, _, report = ingestion
    assert report["steps"]["leads"]["read"] == 1503
    assert report["steps"]["conversations"]["read"] == 677


def test_leads_persisted(ingestion):
    _, factory, _ = ingestion
    with factory() as session:
        assert _count(session, Lead) == 1501


def test_duplicate_lead_ids_are_detected(ingestion):
    _, _, report = ingestion
    leads = report["steps"]["leads"]
    assert leads["duplicate_count"] == 2
    assert set(leads["duplicate_ids"]) == {"LD-00011", "LD-00251"}
    assert all(item["identical"] for item in leads["duplicates_detail"])


def test_ambiguous_slash_dates_are_not_interpreted(ingestion):
    _, factory, report = ingestion
    leads = _all_leads(factory)
    ambiguous = [
        lead
        for lead in leads
        if lead.normalization_meta["registration_date"]["format"]
        == "DD/MM/YYYY vs MM/DD/YYYY"
    ]
    assert len(ambiguous) == report["steps"]["leads"]["ambiguous_registration_dates"] == 265
    assert all(lead.registration_at is None for lead in ambiguous)
    assert all(lead.normalization_meta["registration_date"]["raw"] for lead in ambiguous)


def test_dash_dates_use_documented_convention(ingestion):
    _, factory, _ = ingestion
    leads = _all_leads(factory)
    convention = [
        lead
        for lead in leads
        if lead.normalization_meta["registration_date"]["format"] == "DD-MM-YYYY"
        and lead.normalization_meta["registration_date"]["is_ambiguous"]
    ]
    assert len(convention) == 112
    assert all(lead.registration_at is not None for lead in convention)


def test_phones_are_normalized_and_invalid_marked(ingestion):
    _, factory, report = ingestion
    with factory() as session:
        first = session.get(Lead, "LD-00001")
        invalid = session.get(Lead, "LD-01501")
    assert first.phone_raw == "310 482 4081"
    assert first.phone_normalized == "3104824081"
    assert invalid.phone_normalized is None
    assert report["steps"]["leads"]["invalid_phones"] == 1


def test_city_normalization_rules(ingestion):
    _, _, report = ingestion
    assert normalize_city("bogota d.c.")[0] == "Bogotá"
    assert normalize_city("b/quilla")[0] == "Barranquilla"
    assert normalize_city("sta marta")[0] == "Santa Marta"
    assert normalize_city("rio negro")[0] == "Rionegro"
    assert normalize_city("MONTERIA")[0] == "Montería"
    assert report["steps"]["leads"]["cities_normalized"] == 1422
    assert report["steps"]["leads"]["cities_unmatched"] == 0


def test_models_match_catalog(ingestion):
    _, factory, report = ingestion
    with factory() as session:
        lead = session.get(Lead, "LD-00001")
    assert lead.sku == "SKU-010"
    assert report["steps"]["leads"]["models_matched"] == 1306
    assert report["steps"]["leads"]["models_unmatched"] == 0
    assert report["steps"]["leads"]["models_empty"] == 80


def test_ambiguous_models_do_not_get_sku(ingestion):
    _, factory, report = ingestion
    leads = _all_leads(factory)
    ambiguous = [
        lead for lead in leads if lead.normalization_meta["model"]["state"] == "ambiguous"
    ]
    assert report["steps"]["leads"]["models_ambiguous"] == 115
    assert len(ambiguous) == 115
    assert all(lead.sku is None for lead in ambiguous)


def test_conversations_are_linked(ingestion):
    _, _, report = ingestion
    conversations = report["steps"]["conversations"]
    assert conversations["read"] == 677
    assert conversations["linked"] == 665
    assert conversations["orphan"] == 12
    assert conversations["multiple_conversations_per_lead"] == 25


def test_orphan_conversations_do_not_create_leads(ingestion):
    _, factory, report = ingestion
    with factory() as session:
        assert _count(session, Lead) == 1501
        orphans = list(
            session.scalars(
                sa.select(Conversation).where(Conversation.status == "orphan")
            ).all()
        )
    assert len(orphans) == 12
    assert all(conversation.lead_id is None for conversation in orphans)
    assert all(conversation.company_id is None for conversation in orphans)
    assert len(report["steps"]["conversations"]["orphans"]) == 12
    assert all(item["source_lead_id"] for item in report["steps"]["conversations"]["orphans"])


def test_ingestion_is_idempotent(ingestion):
    _, factory, _ = ingestion
    with factory() as session:
        second = run_ingestion(session)

    assert second["steps"]["leads"]["inserted"] == 0
    assert second["steps"]["leads"]["unchanged"] == 1501
    assert second["steps"]["conversations"]["inserted"] == 0
    assert second["steps"]["conversations"]["unchanged"] == 677

    with factory() as session:
        assert _count(session, Lead) == 1501
        assert _count(session, Conversation) == 677
        assert _count(session, PipelineRun) == 2


def test_normalizer_units():
    assert normalize_phone("+57 350 2258611") == "3502258611"
    assert normalize_phone("322-624-9127") == "3226249127"
    assert is_valid_phone("300123") is False
    assert is_valid_phone("3104824081") is True


def test_original_files_remain_unchanged():
    for name, expected in EXPECTED_FILE_HASHES.items():
        digest = hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest()
        assert digest == expected, f"{name} cambió"
