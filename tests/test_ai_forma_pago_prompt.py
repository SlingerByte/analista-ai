"""Reglas semánticas de `forma_pago` en el prompt v7 (contenido, no LLM).

Fija las instrucciones sin ejecutar modelos: declaraciones explícitas que
deben mapear, preguntas/dinero/asesor que deben quedar en null, y evidencia
exclusivamente del cliente. La verificación conductual vive en sondas
aisladas fuera de la suite.
"""

from __future__ import annotations

import re

from app.ai.prompt import SYSTEM_PROMPT


def _flat() -> str:
    return re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()


def test_forma_pago_contado_declarations():
    flat = _flat()
    for phrase in ("de contado", "la pago de contado", "la quiero de contado",
                   "voy a pagar de contado"):
        assert phrase in flat, phrase


def test_forma_pago_financiacion_declarations():
    flat = _flat()
    for phrase in ("la quiero financiada", "la quiero financiar",
                   "la voy a sacar financiada", "sería financiada",
                   "la voy a comprar a crédito"):
        assert phrase in flat, phrase


def test_forma_pago_questions_stay_null():
    flat = _flat()
    for phrase in ("¿cómo sería financiada?", "¿se puede financiar?",
                   "¿cómo es el proceso a crédito?", "¿cuánto queda la cuota?"):
        assert phrase in flat, phrase


def test_forma_pago_money_is_not_payment_method():
    flat = _flat()
    for phrase in ("tengo 2 millones para la inicial", "ya tengo la plata",
                   "tengo 5 millones disponibles",
                   "tengo 1 millón para la inicial"):
        assert phrase in flat, phrase


def test_forma_pago_advisor_only_stays_null():
    flat = _flat()
    assert "la puede sacar financiada." in flat
    assert "déjeme pensarlo." in flat
    assert "nunca del asesor" in flat


def test_forma_pago_evidence_must_be_client_quote():
    flat = _flat()
    assert "cita breve y literal del cliente" in flat
