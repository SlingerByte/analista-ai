from sqlalchemy.orm import configure_mappers

import app.models  # noqa: F401
from app.db import Base
from app.models import Lead, PointOfSale

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


def test_metadata_contains_the_13_expected_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_mappers_configure_without_errors():
    configure_mappers()


def test_core_relationships_are_declared():
    lead_relationships = {rel.key for rel in Lead.__mapper__.relationships}
    assert {
        "company",
        "point_of_sale",
        "catalog_item",
        "conversations",
        "identity_member",
        "scores",
        "assignments",
    } <= lead_relationships

    point_relationships = {rel.key for rel in PointOfSale.__mapper__.relationships}
    assert {"company", "advisors", "leads"} <= point_relationships
