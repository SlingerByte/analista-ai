from __future__ import annotations

import csv

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db import Base
from app.ingestion.leads import ingest_leads
from app.integrity import (
    OrgIntegrityError,
    validate_assignment_organization,
    validate_lead_organization,
)
from app.models import (
    Advisor,
    Company,
    Lead,
    PipelineRun,
    PointOfSale,
)

LEAD_COLUMNS = [
    "lead_id",
    "fecha_registro",
    "canal",
    "empresa_id",
    "punto_venta_id",
    "nombre_cliente",
    "telefono",
    "email",
    "ciudad",
    "modelo_interes_texto",
    "estado_gestion",
    "fecha_primer_contacto",
    "campania",
]


@pytest.fixture()
def maker(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'integrity.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Company(company_id="EMP-01", name="Empresa 1"),
                Company(company_id="EMP-02", name="Empresa 2"),
            ]
        )
        session.add_all(
            [
                PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1"),
                PointOfSale(point_of_sale_id="PV-002", company_id="EMP-01", name="PV 2"),
                PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="PV 6"),
            ]
        )
        session.add_all(
            [
                Advisor(advisor_id="AS-01", company_id="EMP-01", point_of_sale_id="PV-001",
                        name="Uno", daily_capacity=5, active=True),
                Advisor(advisor_id="AS-02", company_id="EMP-01", point_of_sale_id="PV-001",
                        name="Dos", daily_capacity=5, active=True),
                Advisor(advisor_id="AS-03", company_id="EMP-01", point_of_sale_id="PV-002",
                        name="Tres", daily_capacity=5, active=True),
                Advisor(advisor_id="AS-09", company_id="EMP-02", point_of_sale_id="PV-006",
                        name="Nueve", daily_capacity=5, active=True),
            ]
        )
        session.commit()
    yield factory
    engine.dispose()


def test_lead_organization_valid_passes(maker):
    with maker() as session:
        validate_lead_organization(
            session, company_id="EMP-01", point_of_sale_id="PV-001"
        )


def test_lead_organization_rejects_foreign_point_of_sale(maker):
    with maker() as session:
        with pytest.raises(OrgIntegrityError):
            validate_lead_organization(
                session, company_id="EMP-01", point_of_sale_id="PV-006"
            )


def test_lead_organization_rejects_unknown_point_of_sale(maker):
    with maker() as session:
        with pytest.raises(OrgIntegrityError):
            validate_lead_organization(
                session, company_id="EMP-01", point_of_sale_id="PV-999"
            )


def test_assignment_organization_valid_passes(maker):
    with maker() as session:
        validate_assignment_organization(
            session, company_id="EMP-01", point_of_sale_id="PV-001", advisor_id="AS-01"
        )
        # overflow: sin asesor, POS válido.
        validate_assignment_organization(
            session, company_id="EMP-01", point_of_sale_id="PV-001", advisor_id=None
        )


def test_assignment_organization_rejects_advisor_of_other_company(maker):
    with maker() as session:
        with pytest.raises(OrgIntegrityError):
            validate_assignment_organization(
                session,
                company_id="EMP-01",
                point_of_sale_id="PV-001",
                advisor_id="AS-09",
            )


def test_assignment_organization_rejects_advisor_of_other_pos(maker):
    with maker() as session:
        # AS-03 es de EMP-01 pero de PV-002, no de PV-001.
        with pytest.raises(OrgIntegrityError):
            validate_assignment_organization(
                session,
                company_id="EMP-01",
                point_of_sale_id="PV-001",
                advisor_id="AS-03",
            )


def test_assignment_organization_rejects_unknown_advisor(maker):
    with maker() as session:
        with pytest.raises(OrgIntegrityError):
            validate_assignment_organization(
                session,
                company_id="EMP-01",
                point_of_sale_id="PV-001",
                advisor_id="AS-404",
            )


def test_ingestion_skips_lead_with_foreign_point_of_sale(maker, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rows = [
        {"lead_id": "LD-0001", "fecha_registro": "2026-09-01 10:00:00",
         "canal": "WhatsApp", "empresa_id": "EMP-01", "punto_venta_id": "PV-001",
         "nombre_cliente": "Valido", "telefono": "3001234567", "email": "",
         "ciudad": "Bogotá", "modelo_interes_texto": "Honda Navi",
         "estado_gestion": "Sin gestión", "fecha_primer_contacto": "", "campania": ""},
        {"lead_id": "LD-0002", "fecha_registro": "2026-09-01 10:00:00",
         "canal": "WhatsApp", "empresa_id": "EMP-01", "punto_venta_id": "PV-006",
         "nombre_cliente": "Cruzado", "telefono": "3009999999", "email": "",
         "ciudad": "Bogotá", "modelo_interes_texto": "Honda Navi",
         "estado_gestion": "Sin gestión", "fecha_primer_contacto": "", "campania": ""},
    ]
    with open(data_dir / "leads.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (data_dir / "conversaciones.json").write_text("[]", encoding="utf-8")

    with maker() as session:
        run = PipelineRun(trigger="test", status="running")
        session.add(run)
        session.flush()
        report = ingest_leads(session, run.run_id, data_dir)

        assert report["read"] == 2
        assert report["inserted"] == 1
        assert report["invalid_references"] == 1
        assert session.get(Lead, "LD-0001") is not None
        assert session.get(Lead, "LD-0002") is None
