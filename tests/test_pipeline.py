from __future__ import annotations

import csv
import json
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
import app.pipeline.service as pipeline_service
from app.ai.base import ExtractionOutcome
from app.ai.schema import ExtractionResult
from app.dashboard import _load_rows
from app.db import Base
from app.models import Advisor, Assignment, CatalogItem, Company, LeadScore, PipelineRun, PointOfSale
from app.pipeline import STAGES, run_pipeline

DAY = date(2026, 9, 14)
LEAD_COLUMNS = ["lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id",
                "nombre_cliente", "telefono", "email", "ciudad", "modelo_interes_texto",
                "estado_gestion", "fecha_primer_contacto", "campania"]


class FakeExtractor:
    provider = "fake"
    model = "fake-1"
    available = True

    def __init__(self):
        self.calls = 0

    def availability(self):
        return (True, "ok") if self.available else (False, "not configured")

    def extract(self, conversation):
        self.calls += 1
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=5,
            result=ExtractionResult(
                model_interes="Honda Navi",
                model_interes_evidence="me interesa la Navi",
                intencion_compra="media",
                intencion_compra_evidence="lo estoy pensando",
            ),
        )


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="E1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"))
        session.add(Advisor(advisor_id="AS-001", company_id="EMP-01",
                            point_of_sale_id="PV-001", name="Demo",
                            daily_capacity=5, active=True))
        session.add(CatalogItem(sku="SKU-1", brand="Honda", line="Navi",
                                engine_cc=110, segment="scooter", list_price=7290000.0))
        session.commit()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with open(data_dir / "asesores.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "asesor_id", "nombre", "punto_venta_id", "empresa_id",
            "capacidad_diaria_leads", "activo", "fecha_ingreso"])
        writer.writeheader()
        writer.writerow({"asesor_id": "AS-001", "nombre": "Demo",
                         "punto_venta_id": "PV-001", "empresa_id": "EMP-01",
                         "capacidad_diaria_leads": "5", "activo": "SI",
                         "fecha_ingreso": "2024-01-01"})
    with open(data_dir / "catalogo_motos.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "sku", "marca", "linea", "cilindraje", "segmento", "precio_lista",
            "puntos_venta_disponibles", "unidades_disponibles"])
        writer.writeheader()
        writer.writerow({"sku": "SKU-1", "marca": "Honda", "linea": "Navi",
                         "cilindraje": "110", "segmento": "scooter",
                         "precio_lista": "7290000",
                         "puntos_venta_disponibles": "PV-001",
                         "unidades_disponibles": "10"})
    with open(data_dir / "leads.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_COLUMNS)
        writer.writeheader()
        for lead_id, name in (("LD-1", "Ana"), ("LD-2", "Beto"), ("LD-3", "Ceci")):
            writer.writerow({"lead_id": lead_id, "fecha_registro": "2026-09-10 10:00:00",
                             "canal": "WhatsApp", "empresa_id": "EMP-01",
                             "punto_venta_id": "PV-001", "nombre_cliente": name,
                             "telefono": "3001234567", "email": "", "ciudad": "Bogotá",
                             "modelo_interes_texto": "Honda Navi",
                             "estado_gestion": "Contactado",
                             "fecha_primer_contacto": "2026-09-11 10:00:00",
                             "campania": ""})
    with open(data_dir / "conversaciones.json", "w", encoding="utf-8") as handle:
        json.dump([{"conversacion_id": "CONV-1", "lead_id": "LD-1", "canal": "WhatsApp",
                    "mensajes": [{"emisor": "cliente", "texto": "Me interesa la Navi"}]}],
                  handle)

    extractor = FakeExtractor()
    monkeypatch.setattr(pipeline_service, "build_extractor", lambda: extractor)
    yield maker, data_dir, extractor
    engine.dispose()


def test_1_ejecucion_completa_y_pipeline_runs(setup):
    maker, data_dir, _ = setup
    with maker() as session:
        report = run_pipeline(session, run_date=DAY, data_dir=data_dir)
        assert report["status"] == "completed"
        assert report["stages"] == list(STAGES)
        run = session.get(PipelineRun, report["run_id"])
        assert run.status == "completed"
        assert run.started_at is not None and run.finished_at is not None
        assert run.finished_at >= run.started_at
        assert set(run.steps) == set(STAGES)
        assert all(step["status"] == "completed" for step in run.steps.values())
        assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == 3


def test_2_orden_de_etapas(setup, monkeypatch):
    maker, data_dir, _ = setup
    calls: list[str] = []
    for stage in ("seed", "run_ingestion", "run_identity", "process_pending",
                  "score_and_persist_lead", "run_assignment"):
        real = getattr(pipeline_service, stage)

        def _spy(*args, _real=real, _stage=stage, **kwargs):
            calls.append(_stage)
            return _real(*args, **kwargs)

        monkeypatch.setattr(pipeline_service, stage, _spy)
    with maker() as session:
        # score_and_persist_lead se invoca por lead; el orden de etapas se
        # verifica por primera aparición.
        run_pipeline(session, run_date=DAY, data_dir=data_dir)
    first = []
    for stage in calls:
        if stage not in first:
            first.append(stage)
    assert first == ["seed", "run_ingestion", "run_identity", "process_pending",
                     "score_and_persist_lead", "run_assignment"]


def test_3_rejecucion_sin_duplicados(setup):
    maker, data_dir, extractor = setup
    with maker() as session:
        first = run_pipeline(session, run_date=DAY, data_dir=data_dir)
        assert first["steps"]["scoring"]["created"] == 3
        second = run_pipeline(session, run_date=DAY, data_dir=data_dir)
        assert second["status"] == "completed"
        assert second["steps"]["scoring"]["reused"] == 3
        assert second["steps"]["scoring"]["created"] == 0
        assert second["steps"]["ai"]["processed"] == 1
        assert second["steps"]["ai"]["reused"] == 1
        current = session.scalars(
            sa.select(Assignment).where(Assignment.is_current.is_(True))).all()
        assert len(current) == 3
        assert extractor.calls == 1  # la IA no se rellamó


def test_4_error_de_etapa_queda_registrado(setup, monkeypatch):
    maker, data_dir, _ = setup

    def _boom(session):
        raise RuntimeError("identity caída")

    monkeypatch.setattr(pipeline_service, "run_identity", _boom)
    with maker() as session:
        report = run_pipeline(session, run_date=DAY, data_dir=data_dir)
        assert report["status"] == "failed"
        assert report["steps"]["ingestion"]["status"] == "completed"
        assert report["steps"]["identity"]["status"] == "failed"
        assert "identity" in report["steps"]["identity"]["error"]
        assert "ai" not in report["steps"]  # etapas posteriores no corren
        run = session.get(PipelineRun, report["run_id"])
        assert run.status == "failed"
        assert run.error.startswith("identity:")


def test_5_resultado_consumible_por_dashboard(setup):
    maker, data_dir, _ = setup
    with maker() as session:
        run_pipeline(session, run_date=DAY, data_dir=data_dir)
        advisor = session.get(Advisor, "AS-001")
        rows = _load_rows(session, advisor, DAY)
        assert len(rows) == 3
        assert [r["assignment"].priority_rank for r in rows] == [1, 2, 3]
        assert all(r["score"] is not None for r in rows)


def test_6_sin_ia_y_proveedor_no_disponible(setup):
    maker, data_dir, extractor = setup
    with maker() as session:
        report = run_pipeline(session, run_date=DAY, data_dir=data_dir, run_ai=False)
        assert report["status"] == "completed"
        assert report["steps"]["ai"]["status"] == "skipped"
        assert extractor.calls == 0

    extractor.available = False
    with maker() as session:
        report = run_pipeline(session, run_date=date(2026, 9, 15), data_dir=data_dir)
        assert report["status"] == "completed"
        assert report["steps"]["ai"]["status"] == "skipped"
        assert extractor.calls == 0
