from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.ai.base import ExtractionOutcome
from app.ai.prompt import EXTRACTION_PROMPT_VERSION
from app.ai.schema import SCHEMA_VERSION, ExtractionResult
from app.ai.service import (
    STATUS_ERROR,
    STATUS_SUCCESS,
    build_transcript,
    compute_input_hash,
    get_current_extraction,
    lead_extractions,
    process_conversation,
    process_pending,
)
from app.db import Base
from app.models import AIExtraction, Company, Conversation, Lead, PointOfSale


class FakeSuccessExtractor:
    provider = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = 0

    def availability(self):
        return True, "ok"

    def extract(self, conversation):
        self.calls += 1
        result = ExtractionResult(
            model_interes="Honda Navi",
            model_interes_evidence="me interesa la Honda Navi",
            solicitud_cotizacion=True,
            solicitud_cotizacion_evidence="me la puede cotizar",
        )
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=5,
            result=result,
        )


class FakeFailExtractor(FakeSuccessExtractor):
    def extract(self, conversation):
        self.calls += 1
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=False,
            schema_valid=False,
            latency_ms=5,
            error="network error: URLError",
        )


class FakeInvalidExtractor(FakeSuccessExtractor):
    def extract(self, conversation):
        self.calls += 1
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=False,
            latency_ms=5,
            error="schema validation failed: 1 error(s)",
            raw_text='{"objecion": true}',
        )


@pytest.fixture()
def factory(tmp_path):
    db_path = tmp_path / "ai_service.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="Empresa 1"))
        session.add(
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1")
        )
        session.add(
            Lead(
                lead_id="LD-00001",
                company_id="EMP-01",
                point_of_sale_id="PV-001",
                raw_payload={"lead_id": "LD-00001"},
                record_hash="abc",
            )
        )
        session.add(
            Conversation(
                conversation_id="CONV-00001",
                lead_id="LD-00001",
                company_id="EMP-01",
                channel="WhatsApp",
                status="linked",
                messages=[
                    {"seq": 1, "sender": "cliente", "hour": "", "text": "Me interesa la Honda Navi"},
                    {"seq": 2, "sender": "asesor", "hour": "", "text": "Con gusto"},
                    {"seq": 3, "sender": "cliente", "hour": "", "text": "Me la puede cotizar?"},
                ],
            )
        )
        session.add(
            Conversation(
                conversation_id="CONV-9ORPHAN",
                lead_id=None,
                company_id=None,
                channel="WhatsApp",
                status="orphan",
                messages=[
                    {"seq": 1, "sender": "cliente", "hour": "", "text": "Hola, info por favor"},
                ],
            )
        )
        session.commit()
    yield maker
    engine.dispose()


def test_caso_1_exito_persiste_extraccion(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        result = process_conversation(session, "CONV-00001", extractor)
        assert result.reused is False
        row = result.extraction
        assert row.status == STATUS_SUCCESS
        assert row.lead_id == "LD-00001"
        assert row.provider == "fake"
        assert row.model_name == "fake-1"
        assert row.fields["model_interes"] == "Honda Navi"
        assert row.error is None
        assert row.is_current is True

        # Punto de integración scoring: lectura por conversación y por lead.
        assert get_current_extraction(session, "CONV-00001").extraction_id == row.extraction_id
        assert [e.extraction_id for e in lead_extractions(session, "LD-00001")] == [
            row.extraction_id
        ]


def test_caso_2_idempotencia_reutiliza_sin_llamar(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        first = process_conversation(session, "CONV-00001", extractor)
        second = process_conversation(session, "CONV-00001", extractor)
        assert second.reused is True
        assert second.extraction.extraction_id == first.extraction.extraction_id
        assert extractor.calls == 1
        count = session.scalar(
            sa.select(sa.func.count()).select_from(AIExtraction).where(
                AIExtraction.conversation_id == "CONV-00001"
            )
        )
        assert count == 1


def test_caso_3_cambio_de_input_genera_nueva_extraccion(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        first = process_conversation(session, "CONV-00001", extractor)
        conversation = session.get(Conversation, "CONV-00001")
        conversation.messages = [
            *conversation.messages,
            {"seq": 4, "sender": "cliente", "hour": "", "text": "Tengo 2 millones de inicial"},
        ]
        second = process_conversation(session, "CONV-00001", extractor)
        assert second.reused is False
        assert second.extraction.input_hash != first.extraction.input_hash
        assert extractor.calls == 2
        session.refresh(first.extraction)
        assert first.extraction.is_current is False
        assert second.extraction.is_current is True


def test_caso_4_error_del_proveedor_no_rompe_y_no_filtra_secretos(factory):
    extractor = FakeFailExtractor()
    with factory() as session:
        result = process_conversation(session, "CONV-00001", extractor)
        assert result.reused is False
        row = result.extraction
        assert row.status == STATUS_ERROR
        assert row.fields is None
        assert "URLError" in (row.error or "")
        assert "super-secret-key" not in (row.error or "")

        report = process_pending(session, FakeSuccessExtractor(), limit=10)
        assert report["processed"] >= 1  # el lote continúa tras errores


def test_caso_5_schema_invalido_queda_como_error_controlado(factory):
    extractor = FakeInvalidExtractor()
    with factory() as session:
        result = process_conversation(session, "CONV-00001", extractor)
        assert result.extraction.status == STATUS_ERROR
        assert "schema validation failed" in (result.extraction.error or "")
        assert result.extraction.raw_response == {"raw_text": '{"objecion": true}'}
        assert get_current_extraction(session, "CONV-00001") is None


def test_caso_6_huerfana_no_inventa_lead(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        result = process_conversation(session, "CONV-9ORPHAN", extractor)
        assert result.lead_id is None
        assert result.extraction.lead_id is None
        assert result.extraction.status == STATUS_SUCCESS


def test_caso_7_metadata_correcta(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        conversation = session.get(Conversation, "CONV-00001")
        expected_hash = compute_input_hash(
            build_transcript(conversation.messages),
            EXTRACTION_PROMPT_VERSION,
            SCHEMA_VERSION,
        )
        result = process_conversation(session, "CONV-00001", extractor)
        row = result.extraction
        assert row.schema_version == SCHEMA_VERSION
        assert row.prompt_version == EXTRACTION_PROMPT_VERSION
        assert row.provider == "fake"
        assert row.model_name == "fake-1"
        assert row.input_hash == expected_hash


def test_caso_8_evidencia_ai1a_se_conserva(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        result = process_conversation(session, "CONV-00001", extractor)
        fields = result.extraction.fields
        assert fields["model_interes_evidence"] == "me interesa la Honda Navi"
        assert fields["solicitud_cotizacion_evidence"] == "me la puede cotizar"
        assert fields["schema_version"] == SCHEMA_VERSION


def test_force_reprocesa_aunque_exista(factory):
    extractor = FakeSuccessExtractor()
    with factory() as session:
        first = process_conversation(session, "CONV-00001", extractor)
        result = process_conversation(session, "CONV-00001", extractor, force=True)
        assert result.reused is False
        assert extractor.calls == 2
        # Mismo input efectivo: actualiza la fila, no duplica (unique).
        assert result.extraction.extraction_id == first.extraction.extraction_id
        assert result.extraction.is_current is True


def test_force_tras_error_recupera_la_fila(factory):
    with factory() as session:
        failed = process_conversation(session, "CONV-00001", FakeFailExtractor())
        assert failed.extraction.status == STATUS_ERROR
        recovered = process_conversation(
            session, "CONV-00001", FakeSuccessExtractor(), force=True
        )
        assert recovered.extraction.extraction_id == failed.extraction.extraction_id
        assert recovered.extraction.status == STATUS_SUCCESS
        assert recovered.extraction.error is None
