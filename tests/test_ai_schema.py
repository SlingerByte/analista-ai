from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.schema import ConversationInput, ExtractionResult, Message


def test_valid_extraction_fields_and_evidence():
    result = ExtractionResult(
        model_interes="XRE 300",
        model_interes_evidence="me interesa la XRE 300",
        presupuesto="15.000.000",
        presupuesto_evidence="tengo 15 millones",
        forma_pago="Crédito",
        forma_pago_evidence="la quiero financiada",
        intencion_compra="Alto",
        intencion_compra_evidence="quiero comprarla ya",
        solicitud_cotizacion=True,
        solicitud_cotizacion_evidence="me la puede cotizar",
    )
    assert result.model_interes == "XRE 300"
    assert result.presupuesto == 15000000.0
    assert result.forma_pago == "credito"
    assert result.intencion_compra == "alta"
    assert result.solicitud_cotizacion is True
    assert result.fields_extracted() == 5
    assert result.fields_with_evidence() == 5


def test_null_when_no_evidence():
    result = ExtractionResult(model_interes=None, presupuesto=None, cuota_inicial=None)
    assert result.model_interes is None
    assert result.presupuesto is None
    assert result.cuota_inicial is None
    assert result.fields_extracted() == 0


def test_evidence_is_cleared_when_value_is_null():
    result = ExtractionResult(presupuesto_evidence="algo sin valor", objecion_evidence="x")
    assert result.presupuesto is None
    assert result.presupuesto_evidence is None
    assert result.objecion_evidence is None


def test_field_without_evidence_is_kept_but_not_counted():
    result = ExtractionResult(model_interes="Navi")
    assert result.model_interes == "Navi"
    assert result.model_interes_evidence is None
    assert result.fields_extracted() == 1
    assert result.fields_with_evidence() == 0


def test_controlled_values_reject_unknown():
    with pytest.raises(ValidationError):
        ExtractionResult(forma_pago="crypto")
    with pytest.raises(ValidationError):
        ExtractionResult(intencion_compra="altisima")
    with pytest.raises(ValidationError):
        ExtractionResult(objecion="clima")


def test_monetary_value_must_be_numeric():
    with pytest.raises(ValidationError):
        ExtractionResult(presupuesto="15 millones")


def test_boolean_variants():
    assert ExtractionResult(solicitud_cita="si").solicitud_cita is True
    assert ExtractionResult(solicitud_cita="no").solicitud_cita is False
    assert ExtractionResult(solicitud_cita=None).solicitud_cita is None
    with pytest.raises(ValidationError):
        ExtractionResult(solicitud_cita="tal vez")


def test_extra_fields_are_ignored():
    result = ExtractionResult(model_interes="Navi", razonamiento="ignorar")
    assert result.model_interes == "Navi"


def test_conversation_transcript():
    conversation = ConversationInput(
        conversation_id="CONV-1",
        lead_id="LD-1",
        messages=[
            Message(sender="cliente", text="Hola, me interesa la XRE"),
            Message(sender="asesor", text="Claro, con gusto"),
        ],
    )
    transcript = conversation.transcript()
    assert "cliente: Hola, me interesa la XRE" in transcript
    assert "asesor: Claro, con gusto" in transcript
