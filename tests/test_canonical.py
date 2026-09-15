from __future__ import annotations

import csv

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.canonical import (
    CITY_CANONICAL,
    STATUS_EMPTY,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    resolve_city,
)
from app.dashboard import _city_label
from app.db import Base
from app.ingestion.catalog import build_catalog_index, match_model
from app.ingestion.leads import ingest_leads
from app.ingestion.normalizers import normalize_city
from app.models import Company, Lead, PipelineRun, PointOfSale

LEAD_COLUMNS = [
    "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id",
    "nombre_cliente", "telefono", "email", "ciudad", "modelo_interes_texto",
    "estado_gestion", "fecha_primer_contacto", "campania",
]


# --- Ciudades: generalidad, no reglas de una sola ciudad -------------------


@pytest.mark.parametrize(
    "raw",
    ["MEDELLIN", "medellin", "medellín", "Medellín", " MEDELLÍN ", "  Medellin  "],
)
def test_medellin_variants_share_key_and_canonical(raw):
    result = resolve_city(raw)
    assert result.key == "medellin"
    assert result.canonical == "Medellín"
    assert result.status == STATUS_RESOLVED
    assert result.raw == raw.strip()


@pytest.mark.parametrize(
    "raw,key,canonical",
    [
        ("Bogotá", "bogota", "Bogotá"),
        ("BOGOTA", "bogota", "Bogotá"),
        ("bogota", "bogota", "Bogotá"),
        ("Bogotá D.C.", "bogota", "Bogotá"),
        ("Medellín", "medellin", "Medellín"),
        ("MEDELLIN", "medellin", "Medellín"),
        ("Rionegro", "rionegro", "Rionegro"),
        ("RIONEGRO", "rionegro", "Rionegro"),
        ("Rio Negro", "rionegro", "Rionegro"),
        ("Cali", "cali", "Cali"),
        ("CALI", "cali", "Cali"),
        ("Montería", "monteria", "Montería"),
        ("MONTERIA", "monteria", "Montería"),
        ("Itagüí", "itagui", "Itagüí"),
        ("ITAGUI", "itagui", "Itagüí"),
        ("B/quilla", "barranquilla", "Barranquilla"),
        ("Sta Marta", "santa marta", "Santa Marta"),
    ],
)
def test_city_variants_by_city(raw, key, canonical):
    result = resolve_city(raw)
    assert (result.key, result.canonical, result.status) == (
        key,
        canonical,
        STATUS_RESOLVED,
    )


def test_unknown_city_is_not_invented():
    result = resolve_city("SAN PEPITO DEL NORTE")
    assert result.raw == "SAN PEPITO DEL NORTE"
    assert result.key == "san pepito del norte"
    assert result.canonical is None
    assert result.status == STATUS_UNRESOLVED
    # No fuzzy: un valor parecido no se convierte en una ciudad conocida.
    near = resolve_city("Medellincita")
    assert near.canonical is None
    assert near.status == STATUS_UNRESOLVED
    # La API histórica conserva el contrato (None, key, False).
    assert normalize_city("SAN PEPITO DEL NORTE") == (
        None,
        "san pepito del norte",
        False,
    )


def test_empty_city():
    for value in (None, "", "   "):
        result = resolve_city(value)
        assert result.key == ""
        assert result.canonical is None
        assert result.status == STATUS_EMPTY
        assert result.raw in (None, "")


def test_city_resolution_is_idempotent():
    for raw in ("MEDELLIN", "Bogotá", "RIONEGRO", "Cali", "SAN PEPITO DEL NORTE"):
        first = resolve_city(raw)
        second = resolve_city(first.canonical or first.raw)
        assert (second.key, second.canonical, second.status) == (
            first.key,
            first.canonical,
            first.status,
        )


def test_city_catalog_is_general_and_consistent():
    # El catálogo es pequeño y cada clave resuelve a una representación estable.
    assert len(CITY_CANONICAL) >= 12
    for key, canonical in CITY_CANONICAL.items():
        assert resolve_city(canonical).canonical == canonical
        assert resolve_city(key).canonical == canonical


# --- Modelos: siguen resolviéndose contra el catálogo ----------------------


def test_models_still_resolve_against_catalog():
    index = build_catalog_index(
        [
            ("SKU-010", "Bajaj", "Pulsar RS 200"),
            ("SKU-001", "Honda", "CB 125F Twister"),
        ]
    )
    matched = match_model("bajai pulsar rs 200", index)
    assert matched["state"] == "matched"
    assert matched["sku"] == "SKU-010"
    # La identidad canónica del modelo proviene del catálogo (marca + línea).
    ambiguous = match_model("Bajaj", index)
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["sku"] is None


# --- Ingesta: la canonicalización corre en el pipeline ---------------------


@pytest.fixture()
def maker(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'canonical.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Company(company_id="EMP-01", name="Empresa 1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1"))
        session.add(
            PipelineRun(trigger="test", status="running")
        )
        session.commit()
    yield factory
    engine.dispose()


def test_ingestion_persists_canonical_city_and_preserves_raw(maker, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    row = {
        "lead_id": "LD-0001", "fecha_registro": "2026-09-01 10:00:00",
        "canal": "WhatsApp", "empresa_id": "EMP-01",
        "punto_venta_id": "PV-001", "nombre_cliente": "  Ana   María  ",
        "telefono": "3001234567", "email": "", "ciudad": "  MEDELLÍN ",
        "modelo_interes_texto": "Honda Navi", "estado_gestion": "Sin gestión",
        "fecha_primer_contacto": "", "campania": "",
    }
    with open(data_dir / "leads.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    (data_dir / "conversaciones.json").write_text("[]", encoding="utf-8")

    with maker() as session:
        run = session.scalar(sa.select(PipelineRun))
        report = ingest_leads(session, run.run_id, data_dir)
        assert report["inserted"] == 1
        lead = session.get(Lead, "LD-0001")

    assert lead.city_raw == "MEDELLÍN"          # original preservado (trim)
    assert lead.city_normalized == "Medellín"   # canónico para mostrar/comparar
    meta_city = lead.normalization_meta["city"]
    assert meta_city["key"] == "medellin"
    assert meta_city["canonical"] == "Medellín"
    assert meta_city["status"] == "resolved"
    # Nombre: limpieza segura (espacios colapsados), sin alterar identidad.
    assert lead.customer_name == "Ana María"


# --- UI: prioriza el canónico y conserva el original -----------------------


def test_city_label_prefers_canonical():
    canonical = Lead(
        lead_id="L1", company_id="EMP-01", point_of_sale_id="PV-001",
        raw_payload={}, record_hash="h",
        city_raw="MEDELLIN", city_normalized="Medellín",
    )
    assert _city_label(canonical) == "Medellín"

    unknown = Lead(
        lead_id="L2", company_id="EMP-01", point_of_sale_id="PV-001",
        raw_payload={}, record_hash="h",
        city_raw="SAN PEPITO DEL NORTE", city_normalized=None,
    )
    assert _city_label(unknown) == "SAN PEPITO DEL NORTE"

    missing = Lead(
        lead_id="L3", company_id="EMP-01", point_of_sale_id="PV-001",
        raw_payload={}, record_hash="h",
    )
    assert _city_label(missing) == "Desconocido"


def test_templates_render_canonical_city_not_raw():
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / "app" / "templates"
    dashboard = (templates / "dashboard.html").read_text(encoding="utf-8")
    detail = (templates / "lead_detail.html").read_text(encoding="utf-8")
    assert "{{ row.city }}" in dashboard
    assert "city_raw" not in dashboard
    assert "{{ city }}" in detail
    assert "city_raw" not in detail
