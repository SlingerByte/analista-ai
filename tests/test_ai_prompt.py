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
    assert EXTRACTION_PROMPT_VERSION == "v1"


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


def test_user_prompt_includes_transcript_and_schema_fields():
    user_prompt = build_messages(_conversation())[1]["content"]
    assert "cliente: Estoy mirando la XRE" in user_prompt
    assert "model_interes" in user_prompt
    assert "presupuesto_evidence" in user_prompt
    assert "solicitud_cotizacion" in user_prompt
