from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.ai.base import ExtractionOutcome
from app.ai.prompt import EXTRACTION_PROMPT_VERSION
from app.ai.schema import SCHEMA_VERSION, ExtractionResult
from app.ai.service import build_transcript, compute_input_hash, process_conversation
from app.ai.validation import amounts_in_text, validate_extraction
from app.db import Base
from app.models import AIExtraction, Company, Conversation, Lead, PointOfSale
from app.scoring.service import prepare_lead_signals

ADVISOR_QUOTA = "La cuota quedaría en 480 mil."


# --- Reglas de evidencia (casos A–F de la fase) ----------------------------


def test_case_a_valid_down_payment_from_client():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="tengo 2 millones para la inicial",
        ),
        client_messages=["Tengo 2 millones para la inicial."],
        advisor_messages=[],
    )
    assert validation.extraction.cuota_inicial == 2000000.0
    assert "cuota_inicial" in validation.validated
    assert validation.invalidated == {}


def test_case_b_advisor_quota_is_not_down_payment():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=480000.0,
            cuota_inicial_evidence="la cuota quedaría en 480 mil",
        ),
        client_messages=["Hola, buenas"],
        advisor_messages=[ADVISOR_QUOTA],
    )
    assert validation.extraction.cuota_inicial is None
    assert validation.invalidated["cuota_inicial"] == "advisor_evidence"


def test_case_c_advisor_price_is_not_budget():
    validation = validate_extraction(
        ExtractionResult(
            presupuesto=18000000.0,
            presupuesto_evidence="la moto cuesta 18 millones",
        ),
        client_messages=["Estoy mirando opciones"],
        advisor_messages=["La moto cuesta 18 millones."],
    )
    assert validation.extraction.presupuesto is None
    assert validation.invalidated["presupuesto"] == "advisor_evidence"


def test_case_d_courtesy_reply_is_not_a_signal():
    validation = validate_extraction(
        ExtractionResult(
            solicitud_cotizacion=True,
            solicitud_cotizacion_evidence="Dale",
            solicitud_cita=True,
            solicitud_cita_evidence="Dale",
            intencion_compra="alta",
            intencion_compra_evidence="Dale",
        ),
        client_messages=["Dale."],
        advisor_messages=[],
    )
    assert validation.extraction.solicitud_cotizacion is None
    assert validation.extraction.solicitud_cita is None
    assert validation.extraction.intencion_compra is None
    assert set(validation.invalidated.values()) == {"non_informative_evidence"}


def test_case_e_invented_value_without_evidence_is_removed():
    validation = validate_extraction(
        ExtractionResult(presupuesto=12000000.0),
        client_messages=[],
        advisor_messages=[],
    )
    assert validation.extraction.presupuesto is None
    assert validation.extraction.presupuesto_evidence is None
    assert validation.invalidated["presupuesto"] == "missing_evidence"


def test_case_f_evidence_only_in_advisor_message_is_rejected():
    validation = validate_extraction(
        ExtractionResult(
            presupuesto=12000000.0,
            presupuesto_evidence="12 millones",
        ),
        client_messages=["Estoy buscando una moto."],
        advisor_messages=["Tengo una en 12 millones."],
    )
    assert validation.extraction.presupuesto is None
    assert validation.invalidated["presupuesto"] == "advisor_evidence"


# --- Matching determinista -------------------------------------------------


def test_evidence_matching_ignores_case_accents_and_spacing():
    validation = validate_extraction(
        ExtractionResult(
            model_interes="XRE",
            model_interes_evidence="ME INTERESA   la XRÉ!!!",
        ),
        client_messages=["Me interesa la xre"],
        advisor_messages=[],
    )
    assert validation.extraction.model_interes == "XRE"
    assert validation.invalidated == {}


def test_amount_field_requires_amount_in_evidence():
    validation = validate_extraction(
        ExtractionResult(
            presupuesto=12000000.0,
            presupuesto_evidence="quiero una moto",
        ),
        client_messages=["Quiero una moto"],
        advisor_messages=[],
    )
    assert validation.extraction.presupuesto is None
    assert validation.invalidated["presupuesto"] == "amount_not_in_evidence"


def test_invalid_field_does_not_discard_valid_ones():
    validation = validate_extraction(
        ExtractionResult(
            model_interes="Honda Navi",
            model_interes_evidence="me interesa la Honda Navi",
            presupuesto=12000000.0,
            presupuesto_evidence="12 millones",
        ),
        client_messages=["Me interesa la Honda Navi", "Estoy buscando una moto"],
        advisor_messages=["Tengo una en 12 millones."],
    )
    assert validation.extraction.model_interes == "Honda Navi"
    assert "model_interes" in validation.validated
    assert validation.extraction.presupuesto is None
    assert validation.invalidated == {"presupuesto": "advisor_evidence"}


def test_amounts_in_text_parses_local_formats():
    assert 2000000.0 in amounts_in_text("tengo 2,0 millones")
    assert 480000.0 in amounts_in_text("cuota de $480.000")
    assert 18000000.0 in amounts_in_text("18 millones")
    assert 1500000.0 in amounts_in_text("1.500.000")
    assert 2000000.0 in amounts_in_text("2000000")
    assert amounts_in_text("quiero una moto") == []


# --- Integración: la validación ocurre antes del scoring -------------------


class _FakeExtractor:
    provider = "fake"
    model = "fake-1"

    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.calls = 0

    def availability(self):
        return True, "ok"

    def extract(self, conversation):
        self.calls += 1
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=1,
            result=self.result,
        )


@pytest.fixture()
def factory(tmp_path):
    db_path = tmp_path / "ai_validation.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="Empresa 1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1"))
        session.add_all(
            [
                Lead(lead_id="LD-1", company_id="EMP-01", point_of_sale_id="PV-001",
                     raw_payload={"lead_id": "LD-1"}, record_hash="a"),
                Lead(lead_id="LD-2", company_id="EMP-01", point_of_sale_id="PV-001",
                     raw_payload={"lead_id": "LD-2"}, record_hash="b"),
                Lead(lead_id="LD-3", company_id="EMP-01", point_of_sale_id="PV-001",
                     raw_payload={"lead_id": "LD-3"}, record_hash="c"),
            ]
        )
        session.add_all(
            [
                Conversation(
                    conversation_id="CONV-1", lead_id="LD-1", company_id="EMP-01",
                    channel="WhatsApp", status="linked",
                    messages=[
                        {"seq": 1, "sender": "cliente", "hour": "", "text": "Hola, buenas"},
                        {"seq": 2, "sender": "asesor", "hour": "", "text": ADVISOR_QUOTA},
                    ],
                ),
                Conversation(
                    conversation_id="CONV-2", lead_id="LD-2", company_id="EMP-01",
                    channel="WhatsApp", status="linked",
                    messages=[
                        {"seq": 1, "sender": "cliente", "hour": "",
                         "text": "Tengo 2 millones para la inicial"},
                    ],
                ),
                Conversation(
                    conversation_id="CONV-3", lead_id="LD-3", company_id="EMP-01",
                    channel="WhatsApp", status="linked",
                    messages=[
                        {"seq": 1, "sender": "cliente", "hour": "",
                         "text": "tengo 12 millones disponibles"},
                    ],
                ),
            ]
        )
        session.commit()
    yield maker
    engine.dispose()


def test_unvalidated_field_does_not_reach_scoring(factory):
    extractor = _FakeExtractor(
        ExtractionResult(
            cuota_inicial=480000.0,
            cuota_inicial_evidence="la cuota quedaría en 480 mil",
        )
    )
    with factory() as session:
        process_conversation(session, "CONV-1", extractor)
        signals = prepare_lead_signals(session, "LD-1")
        assert signals.has_conversation is True
        assert signals.cuota_inicial is None

        row = session.scalar(
            sa.select(AIExtraction).where(AIExtraction.conversation_id == "CONV-1")
        )
        assert row.fields["cuota_inicial"] is None
        assert row.fields["validation"]["invalidated"]["cuota_inicial"] == "advisor_evidence"


def test_validated_field_reaches_scoring(factory):
    extractor = _FakeExtractor(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="tengo 2 millones para la inicial",
        )
    )
    with factory() as session:
        process_conversation(session, "CONV-2", extractor)
        signals = prepare_lead_signals(session, "LD-2")
        assert signals.cuota_inicial == 2000000.0

        row = session.scalar(
            sa.select(AIExtraction).where(AIExtraction.conversation_id == "CONV-2")
        )
        assert "validation" not in row.fields
        assert row.fields["cuota_inicial"] == 2000000.0


# --- Evidencia con prefijo del hablante (Phase 1.6) ------------------------


def test_evidence_with_client_prefix_is_valid():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="cliente: tengo 2,0 millones para la inicial",
        ),
        client_messages=["tengo 2,0 millones para la inicial"],
        advisor_messages=[],
    )
    assert validation.extraction.cuota_inicial == 2000000.0
    assert validation.invalidated == {}


def test_evidence_with_advisor_prefix_is_rejected():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="asesor: tengo 2,0 millones para la inicial",
        ),
        client_messages=[],
        advisor_messages=["tengo 2,0 millones para la inicial"],
    )
    assert validation.extraction.cuota_inicial is None
    assert validation.invalidated["cuota_inicial"] == "advisor_evidence"


def test_client_prefix_does_not_validate_advisor_message():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="cliente: tengo 2,0 millones para la inicial",
        ),
        client_messages=[],
        advisor_messages=["tengo 2,0 millones para la inicial"],
    )
    assert validation.extraction.cuota_inicial is None
    assert validation.invalidated["cuota_inicial"] == "advisor_evidence"


def test_evidence_without_prefix_is_valid_for_client():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=2000000.0,
            cuota_inicial_evidence="tengo 2,0 millones para la inicial",
        ),
        client_messages=["tengo 2,0 millones para la inicial"],
        advisor_messages=[],
    )
    assert validation.extraction.cuota_inicial == 2000000.0
    assert validation.invalidated == {}


def test_amount_with_prefix_matches():
    validation = validate_extraction(
        ExtractionResult(
            cuota_inicial=480000.0,
            cuota_inicial_evidence="cliente: la inicial es de $480.000",
        ),
        client_messages=["la inicial es de $480.000"],
        advisor_messages=[],
    )
    assert validation.extraction.cuota_inicial == 480000.0
    assert validation.invalidated == {}


def test_prefixed_courtesy_is_not_a_signal():
    validation = validate_extraction(
        ExtractionResult(
            solicitud_cita=True,
            solicitud_cita_evidence="cliente: Dale",
        ),
        client_messages=["Dale"],
        advisor_messages=[],
    )
    assert validation.extraction.solicitud_cita is None
    assert validation.invalidated["solicitud_cita"] == "non_informative_evidence"


def test_prefix_tolerates_case_accents_and_punctuation():
    validation = validate_extraction(
        ExtractionResult(
            model_interes="XRE",
            model_interes_evidence="CLIENTE:  Me interesa la XRÉ!!!",
        ),
        client_messages=["me interesa la xre"],
        advisor_messages=[],
    )
    assert validation.extraction.model_interes == "XRE"
    assert validation.invalidated == {}


# --- Reutilización: nunca saltarse la validación (Phase 1.6) ---------------


class _NeverCalledExtractor:
    """Falla si el flujo de reutilización llama al LLM."""

    provider = "fake"
    model = "fake-1"

    def availability(self):
        return True, "ok"

    def extract(self, conversation):
        raise AssertionError("no debe llamarse al extractor en una reutilización")


def _insert_legacy_extraction(session, conversation_id, lead_id, **fields):
    conversation = session.get(Conversation, conversation_id)
    transcript = build_transcript(conversation.messages)
    input_hash = compute_input_hash(transcript, EXTRACTION_PROMPT_VERSION, SCHEMA_VERSION)
    row = AIExtraction(
        conversation_id=conversation_id,
        lead_id=lead_id,
        provider="fake",
        model_name="fake-1",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status="success",
        input_hash=input_hash,
        fields=ExtractionResult(**fields).model_dump(),
        is_current=True,
    )
    session.add(row)
    session.commit()
    return row


def test_reuse_revalidates_legacy_invalid_extraction(factory):
    with factory() as session:
        _insert_legacy_extraction(
            session, "CONV-2", "LD-2", presupuesto=12000000.0, presupuesto_evidence=None
        )
        result = process_conversation(session, "CONV-2", _NeverCalledExtractor())
        assert result.reused is True

        row = session.scalar(
            sa.select(AIExtraction).where(AIExtraction.conversation_id == "CONV-2")
        )
        assert row.fields["presupuesto"] is None
        assert row.fields["presupuesto_evidence"] is None
        assert row.fields["validation"]["invalidated"]["presupuesto"] == "missing_evidence"

        signals = prepare_lead_signals(session, "LD-2")
        assert signals.presupuesto is None


def test_reuse_preserves_legacy_valid_extraction(factory):
    with factory() as session:
        _insert_legacy_extraction(
            session,
            "CONV-3",
            "LD-3",
            presupuesto=12000000.0,
            presupuesto_evidence="cliente: tengo 12 millones disponibles",
        )
        result = process_conversation(session, "CONV-3", _NeverCalledExtractor())
        assert result.reused is True
        assert result.extraction.fields["presupuesto"] == 12000000.0
        assert "validation" not in result.extraction.fields

        signals = prepare_lead_signals(session, "LD-3")
        assert signals.presupuesto == 12000000.0


def test_reuse_revalidation_is_idempotent(factory):
    with factory() as session:
        legacy = _insert_legacy_extraction(
            session, "CONV-2", "LD-2", presupuesto=12000000.0, presupuesto_evidence=None
        )
        original_hash = legacy.input_hash
        first = process_conversation(session, "CONV-2", _NeverCalledExtractor())
        second = process_conversation(session, "CONV-2", _NeverCalledExtractor())

        rows = session.scalars(
            sa.select(AIExtraction).where(AIExtraction.conversation_id == "CONV-2")
        ).all()
        assert len(rows) == 1
        assert first.extraction.extraction_id == second.extraction.extraction_id
        assert first.reused is True and second.reused is True
        assert rows[0].input_hash == original_hash
        assert rows[0].fields["presupuesto"] is None
        assert rows[0].is_current is True
