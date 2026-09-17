"""Gold set V8 (offline y determinista) a partir de la auditoría v2→v7.

Alcance real de esta prueba:

- El proyecto NO tiene un extractor local determinista que reproduzca las
  etiquetas de un LLM sin llamar a un proveedor. Por eso las etiquetas del
  gold set (por ejemplo CONV-00048 -> solicitud_cotizacion=true) NO se pueden
  evaluar aquí sin una llamada a proveedor. Este archivo NO inventa esos
  resultados: (a) fija que el prompt V8 contiene explícitamente las reglas y
  ejemplos que cubren cada caso gold y (b) fija con el validador determinista
  las invariantes verificables sin modelo (evidencia del asesor no vale, monto
  de la inicial presente en la evidencia literal del cliente).
"""

from __future__ import annotations

import re

from app.ai.prompt import EXTRACTION_PROMPT_VERSION, SYSTEM_PROMPT
from app.ai.schema import SCHEMA_VERSION, ExtractionResult
from app.ai.validation import validate_extraction

GOLD_V8: list[dict[str, object]] = [
    {"id": "CONV-00048", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Sí porfa, mándemela"},
    {"id": "CONV-00050", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Sí porfa, mándemela"},
    {"id": "CONV-00060", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Sí porfa, mándemela"},
    {"id": "CONV-00065", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Bueno, mándela y yo le digo"},
    {"id": "CONV-00071", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Sí porfa, mándemela"},
    {"id": "CONV-00075", "signal": "solicitud_cotizacion",
     "expected": True, "evidence": "Sí porfa, mándemela"},
    {"id": "CONV-00031", "signal": "solicitud_cita",
     "expected": True, "evidence": "Voy esta tarde para allá"},
    {"id": "CONV-00062", "signal": "solicitud_cita",
     "expected": True, "evidence": "¿Mañana los visito?"},
    {"id": "CONV-00058", "signal": "intencion_compra",
     "expected": "alta", "evidence": "Esa sí me sirve"},
    {"id": "CONV-00061", "signal": "intencion_compra",
     "expected": "alta", "evidence": "Hágale pues, ya voy en camino"},
    {"id": "CONV-00063", "signal": "intencion_compra",
     "expected": "baja", "evidence": "Estoy es comparando por ahora"},
    {"id": "CONV-00068", "signal": "presupuesto",
     "expected": None, "evidence": "tengo como 3 millonzitos para la inicial"},
    {"id": "CONV-00073", "signal": "presupuesto",
     "expected": None, "evidence": "Tengo como 2 millonzitos para la inicial"},
    {"id": "CONV-00038", "signal": "cuota_inicial",
     "expected": 1000000.0, "evidence": "Esa sí me sirve. Tengo 1 palos de inicial"},
    {"id": "CONV-00046", "signal": "cuota_inicial",
     "expected": 1000000.0, "evidence": "Tengo como 1 millones para la inicial"},
    {"id": "CONV-00066", "signal": "cuota_inicial",
     "expected": 1200000.0, "evidence": "Tengo como 1200mil para la inicial"},
    {"id": "CONV-00069", "signal": "cuota_inicial",
     "expected": 1200000.0, "evidence": "Tengo como 1200 mil para la inicial"},
    {"id": "CONV-00073", "signal": "cuota_inicial",
     "expected": 2000000.0, "evidence": "Tengo como 2 millonzitos para la inicial"},
]

REQUIRED_COTIZACION = {"CONV-00048", "CONV-00050", "CONV-00060",
                       "CONV-00065", "CONV-00071", "CONV-00075"}
REQUIRED_CITA = {"CONV-00031", "CONV-00062"}
REQUIRED_INTENCION = {"CONV-00058", "CONV-00061", "CONV-00063"}
REQUIRED_PRESUPUESTO = {"CONV-00068", "CONV-00073"}
REQUIRED_CUOTA_INICIAL = {"CONV-00038", "CONV-00046", "CONV-00066",
                          "CONV-00069", "CONV-00073"}

ADVISOR_MONTHLY_QUOTA = "La cuota le queda alrededor de $480.000 al mes."
ADVISOR_PRICE = "Esa moto cuesta 18 millones."
ADVISOR_DOWN_PAYMENT_HINT = "Con esa inicial la cuota le queda en $320.000."


def _cases(signal: str) -> list[dict[str, object]]:
    return [case for case in GOLD_V8 if case["signal"] == signal]


def _flat_prompt() -> str:
    return re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()


def _validate(signal: str, value: float | None, evidence: str | None,
              client_messages: list[str],
              advisor_messages: list[str] | None = None):
    field = "cuota_inicial" if signal == "cuota_inicial" else "presupuesto"
    extraction = ExtractionResult(**{field: value, f"{field}_evidence": evidence})
    return validate_extraction(extraction, client_messages, advisor_messages or [])


# --- Versionado ------------------------------------------------------------


def test_v8_prompt_version_and_schema_unchanged():
    assert EXTRACTION_PROMPT_VERSION == "v8"
    assert SCHEMA_VERSION == "v1"


# --- Cobertura del prompt (determinista) -----------------------------------


def test_v8_prompt_covers_cotizacion_acceptance():
    flat = _flat_prompt()
    for phrase in ("sí porfa, mándemela", "listo, envíemela",
                   "bueno, mándela y yo le digo", "mándela y yo le digo"):
        assert phrase in flat, phrase
    assert "oferta del asesor por sí sola" in flat
    assert "genérico sin contexto de cotización no basta" in flat


def test_v8_prompt_covers_cita_colloquial_confirmation():
    flat = _flat_prompt()
    for phrase in ("¿mañana los visito?", "voy esta tarde para allá",
                   "ya voy en camino", "sí por favor, voy saliendo",
                   "listo, sepáremela"):
        assert phrase in flat, phrase
    assert "no los degraden a null por ser coloquiales" in flat


def test_v8_prompt_covers_strong_intent_and_courtesy_guard():
    flat = _flat_prompt()
    for phrase in ("esa sí me sirve", "la necesito esta semana", "la necesito ya",
                   "solo estaba mirando", "estoy comparando"):
        assert phrase in flat, phrase
    assert '"ok", "dale" o "hágale" aislados' in flat
    assert "sin contexto comercial suficiente" in flat


def test_v8_prompt_covers_presupuesto_is_not_down_payment():
    flat = _flat_prompt()
    assert "tengo 3 millones para la inicial" in flat
    assert "presupuesto debe quedar en null" in flat


def test_v8_prompt_covers_strict_down_payment():
    flat = _flat_prompt()
    for phrase in ("tengo 1 palo de inicial", "tengo 1200 mil para la inicial",
                   "tengo 3 millones para la inicial"):
        assert phrase in flat, phrase
    assert "cuota mensual" in flat
    assert "valor de cuota ofrecido por el asesor" in flat
    assert "precio total de la moto" in flat


def test_v8_prompt_requires_client_evidence():
    flat = _flat_prompt()
    assert "un mensaje cuyo emisor sea el cliente" in flat
    assert "nunca uses un mensaje del asesor como evidencia" in flat


def test_v8_gold_evidence_is_single_literal_message():
    for conversation_id, expected in (("CONV-00058", "Esa sí me sirve"),
                                      ("CONV-00061", "Hágale pues, ya voy en camino")):
        case = next(c for c in GOLD_V8
                    if c["id"] == conversation_id and c["signal"] == "intencion_compra")
        assert case["evidence"] == expected, conversation_id
        assert "inicial" not in str(case["evidence"]).lower(), conversation_id
        assert "\n" not in str(case["evidence"]), conversation_id


# --- Gold set: invariantes deterministas (sin modelo) ----------------------


def test_gold_advisor_monthly_quota_is_not_down_payment():
    outcome = _validate(
        "cuota_inicial", 480000.0, ADVISOR_MONTHLY_QUOTA,
        ["Hola, buenas"],
        [ADVISOR_MONTHLY_QUOTA, ADVISOR_DOWN_PAYMENT_HINT],
    )
    assert outcome.extraction.cuota_inicial is None
    assert outcome.invalidated["cuota_inicial"] == "advisor_evidence"


def test_gold_advisor_price_is_not_budget():
    outcome = _validate(
        "presupuesto", 18000000.0, "18 millones",
        ["Estoy mirando opciones"],
        [ADVISOR_PRICE],
    )
    assert outcome.extraction.presupuesto is None
    assert outcome.invalidated["presupuesto"] == "advisor_evidence"


def test_gold_client_down_payment_amounts_are_conserved():
    for case in _cases("cuota_inicial"):
        conversation_id = str(case["id"])
        evidence = str(case["evidence"])
        expected = float(case["expected"])
        outcome = _validate("cuota_inicial", expected, f"cliente: {evidence}",
                            [evidence])
        assert outcome.extraction.cuota_inicial == expected, conversation_id
        assert "cuota_inicial" in outcome.validated, conversation_id


def test_gold_spec_covers_required_conversations():
    assert {str(c["id"]) for c in _cases("solicitud_cotizacion")} == REQUIRED_COTIZACION
    assert {str(c["id"]) for c in _cases("solicitud_cita")} == REQUIRED_CITA
    assert {str(c["id"]) for c in _cases("intencion_compra")} == REQUIRED_INTENCION
    assert {str(c["id"]) for c in _cases("presupuesto")} == REQUIRED_PRESUPUESTO
    assert {str(c["id"]) for c in _cases("cuota_inicial")} == REQUIRED_CUOTA_INICIAL


def test_gold_spec_expected_labels():
    labels = {(str(case["id"]), str(case["signal"])): case["expected"]
              for case in GOLD_V8}
    assert labels[("CONV-00048", "solicitud_cotizacion")] is True
    assert labels[("CONV-00031", "solicitud_cita")] is True
    assert labels[("CONV-00062", "solicitud_cita")] is True
    assert labels[("CONV-00058", "intencion_compra")] == "alta"
    assert labels[("CONV-00061", "intencion_compra")] == "alta"
    assert labels[("CONV-00063", "intencion_compra")] == "baja"
    assert labels[("CONV-00068", "presupuesto")] is None
    assert labels[("CONV-00073", "presupuesto")] is None
    assert labels[("CONV-00038", "cuota_inicial")] == 1000000.0
    assert labels[("CONV-00073", "cuota_inicial")] == 2000000.0


def test_gold_model_labels_are_not_offline_verifiable():
    """Las etiquetas del gold dependen del LLM: no se verifican aquí."""
    model_dependent = {
        (str(case["id"]), str(case["signal"])) for case in GOLD_V8
        if case["signal"] in {"solicitud_cotizacion", "solicitud_cita",
                              "intencion_compra", "presupuesto"}
    }
    expected_model_dependent = {(cid, "solicitud_cotizacion")
                                for cid in REQUIRED_COTIZACION}
    expected_model_dependent |= {(cid, "solicitud_cita") for cid in REQUIRED_CITA}
    expected_model_dependent |= {(cid, "intencion_compra") for cid in REQUIRED_INTENCION}
    expected_model_dependent |= {(cid, "presupuesto") for cid in REQUIRED_PRESUPUESTO}
    assert model_dependent == expected_model_dependent
