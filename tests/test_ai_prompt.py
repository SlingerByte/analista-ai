from __future__ import annotations

from app.ai.prompt import EXTRACTION_PROMPT_VERSION, SYSTEM_PROMPT, build_messages
from app.ai.schema import ConversationInput, Message


def _conversation() -> ConversationInput:
    return ConversationInput(
        conversation_id="CONV-1",
        messages=[
            Message(sender="cliente", text="Estoy mirando la XRE y quisiera saber si manejan financiación."),
            Message(sender="asesor", text="¿La busca de contado o financiada?"),
        ],
    )


def test_prompt_version_is_defined():
    assert EXTRACTION_PROMPT_VERSION == "v8"


def test_prompt_has_system_and_user_messages():
    messages = build_messages(_conversation())
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT


def test_system_prompt_states_key_rules():
    lowered = SYSTEM_PROMPT.lower()
    assert "no inventes" in lowered
    assert "null" in lowered
    assert "cliente" in lowered and "asesor" in lowered
    assert "evidencia" in lowered


def test_system_prompt_requires_client_only_literal_evidence():
    lowered = SYSTEM_PROMPT.lower()
    assert "literal" in lowered
    assert "del cliente" in lowered
    assert "nunca" in lowered and "asesor" in lowered


def test_system_prompt_forbids_common_hallucinations():
    lowered = SYSTEM_PROMPT.lower()
    assert "cuota_inicial" in lowered
    assert "cuota mensual" in lowered or "cuotas de" in lowered
    assert "cotizaci" in lowered
    assert "cita" in lowered
    assert "dale" in lowered


def test_system_prompt_defines_purchase_intent_levels():
    lowered = SYSTEM_PROMPT.lower()
    assert "intencion_compra" in lowered
    assert '"alta"' in lowered
    assert '"media"' in lowered
    assert '"baja"' in lowered


def test_system_prompt_calibrates_financing_signals():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    for phrase in ("¿cuánto queda la cuota?", "¿alcanza para la inicial?",
                   "financiada.", "tengo 500 mil de inicial."):
        assert phrase in flat, phrase
    assert "no implican por sí solas" in flat


def test_system_prompt_weights_dampeners():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    for phrase in ("no tengo con qué dar la inicial",
                   "tengo que hablarlo con mi esposa",
                   "solo estaba mirando", "estoy comparando",
                   "quiero una usada más barata"):
        assert phrase in flat, phrase


def test_system_prompt_recognizes_strong_buying_signals():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    for phrase in ("esa sí me sirve.", "sí, esa es la que quiero.",
                   "voy a separarla.", "la necesito esta semana",
                   "la necesito ya"):
        assert phrase in flat, phrase


def test_system_prompt_does_not_auto_high_courtesy_replies():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    assert '"hágale" aislados' in flat


def _flat_prompt() -> str:
    import re
    return re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()


def test_objecion_positive_examples():
    flat = _flat_prompt()
    for phrase in ("muy costosa.", "está muy cara", "la cuota me queda muy alta",
                   "el interés está muy caro", "no tengo inicial",
                   "la inicial es muy alta", "no me sirve esa financiación"):
        assert phrase in flat, phrase


def test_objecion_questions_stay_null():
    flat = _flat_prompt()
    for phrase in ("¿cuánto queda la cuota?", "¿cómo sería financiada?",
                   "¿cuánto vale?", "¿cuánto es la inicial?",
                   "financiada.", "quiero financiarla."):
        assert phrase in flat, phrase
    assert "pregunta informativa no es objeción" in flat


def test_objecion_survives_later_advance():
    flat = _flat_prompt()
    assert "sigue siendo objeción aunque el cliente después" in flat
    assert "esa sí me sirve, voy esta tarde" in flat
    assert "no uses el último mensaje" in flat


def test_objecion_requires_semantic_barrier():
    flat = _flat_prompt()
    assert "barrera o fricción" in flat
    assert "no toda mención de precio da" in flat


def test_system_prompt_forbids_boolean_objecion():
    lowered = SYSTEM_PROMPT.lower()
    assert "objecion" in lowered
    assert "boolean" in lowered


def test_system_prompt_defines_cita_visit_rule():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    for phrase in ("¿puedo pasar mañana?", "¿a qué hora los puedo visitar?",
                   "voy esta tarde para allá", "voy saliendo",
                   "ya voy en camino", "me paso más tarde",
                   "sí, sepáremela", "sí por favor, voy saliendo"):
        assert phrase in flat, phrase


def test_system_prompt_rejects_non_visit_voy_phrases():
    import re
    flat = re.sub(r"\s+", " ", SYSTEM_PROMPT).lower()
    for phrase in ("voy a consultar en la casa", "voy a hablarlo con mi esposo",
                   "voy a mirar otras opciones", "voy a pensarlo",
                   "¿hasta qué hora abren?", "¿le separo la moto?"):
        assert phrase in flat, phrase


def test_system_prompt_defines_presupuesto_as_explicit_limit():
    lowered = SYSTEM_PROMPT.lower()
    assert "presupuesto" in lowered
    assert "límite" in lowered or "limite" in lowered
    assert "mi presupuesto es de 5 millones" in lowered
    assert "tengo máximo 6 millones" in lowered
    assert "no me puedo pasar de 7 millones" in lowered
    assert "entre 5 y 6 millones" in lowered


def test_system_prompt_rejects_cash_as_budget():
    lowered = SYSTEM_PROMPT.lower()
    assert "dinero disponible" in lowered
    assert "ya tengo la plata lista" in lowered
    assert "cuota inicial" in lowered
    assert "cuota mensual" in lowered
    assert "precio de la moto" in lowered
    assert "me alcanza" in lowered
    assert "presupuesto = null" in lowered
    assert "valor máximo del rango" in lowered


def test_user_prompt_includes_transcript_and_schema_fields():
    user_prompt = build_messages(_conversation())[1]["content"]
    assert "cliente: Estoy mirando la XRE" in user_prompt
    assert "model_interes" in user_prompt
    assert "presupuesto_evidence" in user_prompt
    assert "solicitud_cotizacion" in user_prompt
