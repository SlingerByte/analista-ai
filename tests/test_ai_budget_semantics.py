"""Semántica de `presupuesto` en la capa determinista (regresión CONV-00028).

Límite documentado de la validación: es sintáctica (cita literal del cliente
+ monto presente en la cita), no semántica. Un `presupuesto` con evidencia
del cliente que contenga el monto PASA la validación aunque el dinero sea
disponible/inicial/mensual; impedir esa inferencia es trabajo del prompt v3
(ver tests/test_ai_prompt.py). Estos tests fijan el comportamiento de cada
capa para que ninguna regresse en silencio.
"""

from __future__ import annotations

from app.ai.prompt import EXTRACTION_PROMPT_VERSION, SYSTEM_PROMPT, build_messages
from app.ai.schema import ConversationInput, ExtractionResult, Message
from app.ai.validation import validate_extraction

CLIENT_CASH = "De contado, ya tengo la plata lista, 4900mil"
CLIENT_EXPLICIT = "Mi presupuesto máximo son 5 millones"
CLIENT_DOWN = "Tengo 2 millones de inicial"
CLIENT_MONTHLY = "Quiero pagar cuotas de 300 mil"
CLIENT_AMBIGUOUS = "Con 5 millones me alcanza?"


def _validate(value: float | None, evidence: str | None,
              client: list[str], advisor: list[str] | None = None):
    extraction = ExtractionResult(presupuesto=value,
                                  presupuesto_evidence=evidence)
    return validate_extraction(extraction, client, advisor or [])


def test_prompt_is_v3_with_budget_rule():
    assert EXTRACTION_PROMPT_VERSION == "v4"
    assert "presupuesto != dinero disponible" in SYSTEM_PROMPT


def test_dinero_disponible_pasa_validacion_por_diseno():
    """El validator conserva el valor: solo el prompt v3 evita extraerlo."""
    outcome = _validate(4900000.0, f"cliente: {CLIENT_CASH}", [CLIENT_CASH])
    assert "presupuesto" not in outcome.invalidated
    assert outcome.extraction.presupuesto == 4900000.0


def test_presupuesto_explicito_se_conserva():
    outcome = _validate(5000000.0, f"cliente: {CLIENT_EXPLICIT}", [CLIENT_EXPLICIT])
    assert "presupuesto" not in outcome.invalidated
    assert outcome.extraction.presupuesto == 5000000.0


def test_cuota_mensual_como_presupuesto_pasa_validacion_por_diseno():
    outcome = _validate(300000.0, f"cliente: {CLIENT_MONTHLY}", [CLIENT_MONTHLY])
    assert "presupuesto" not in outcome.invalidated


def test_precio_del_asesor_no_valida_presupuesto():
    advisor = ["La Hero Eco Deluxe 100 está en $4.990.000 más matrícula y SOAT."]
    outcome = _validate(4990000.0, "asesor: Está en 4.990.000",
                        ["Me interesa la moto"], advisor)
    assert outcome.invalidated.get("presupuesto") == "advisor_evidence"
    assert outcome.extraction.presupuesto is None


def test_evidencia_sin_monto_se_invalida_conv00028():
    """Regresión del caso persistido: evidencia real sin el monto."""
    client = [
        "Buenas tardes, estoy averiguando por la Hero Eco Deluxe 100",
        CLIENT_CASH,
        "Sí, soy independiente pero tengo extractos",
        "Voy esta tarde para allá, ¿hasta qué hora abren?",
        "Sí por favor, voy saliendo",
    ]
    outcome = _validate(4900000.0,
                        "cliente: Sí, soy independiente pero tengo extractos",
                        client)
    assert outcome.invalidated.get("presupuesto") == "amount_not_in_evidence"
    assert outcome.extraction.presupuesto is None


def test_cuota_inicial_no_se_deteriora():
    extraction = ExtractionResult(
        cuota_inicial=2000000.0,
        cuota_inicial_evidence=f"cliente: {CLIENT_DOWN}",
        presupuesto=None,
        presupuesto_evidence=None,
    )
    outcome = validate_extraction(extraction, [CLIENT_DOWN], [])
    assert "cuota_inicial" not in outcome.invalidated
    assert outcome.extraction.cuota_inicial == 2000000.0
    assert outcome.extraction.presupuesto is None


def test_forma_pago_contado_no_se_deteriora():
    extraction = ExtractionResult(
        forma_pago="contado",
        forma_pago_evidence=f"cliente: {CLIENT_CASH}",
    )
    outcome = validate_extraction(extraction, [CLIENT_CASH], [])
    assert "forma_pago" not in outcome.invalidated
    assert outcome.extraction.forma_pago == "contado"


def test_conv00028_transcript_llega_al_prompt_v3():
    conversation = ConversationInput(
        conversation_id="CONV-00028",
        lead_id="LD-01341",
        channel="WhatsApp",
        messages=[
            Message(sender="cliente",
                    text="Estoy averiguando por la Hero Eco Deluxe 100"),
            Message(sender="cliente", text=CLIENT_CASH),
            Message(sender="cliente", text="Voy esta tarde para allá"),
            Message(sender="cliente", text="Sí por favor, voy saliendo"),
        ],
    )
    user_prompt = build_messages(conversation)[1]["content"]
    assert CLIENT_CASH in user_prompt
    assert "presupuesto" in user_prompt
