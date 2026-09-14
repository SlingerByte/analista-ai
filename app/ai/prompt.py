from __future__ import annotations

from app.ai.schema import (
    EXTRACTION_FIELDS,
    FORMA_PAGO_VALUES,
    INTENCION_VALUES,
    OBJECION_VALUES,
    ConversationInput,
)

EXTRACTION_PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
Eres un extractor de información estructurada de conversaciones comerciales de WhatsApp
entre clientes y asesores de una empresa de motos en Colombia.

Reglas obligatorias:
- Responde ÚNICAMENTE con un objeto JSON válido que siga el esquema indicado. Sin texto adicional.
- NO inventes datos. Si no hay evidencia explícita en la conversación, usa null.
- Distingue al CLIENTE del ASESOR. Extrae información aportada por el CLIENTE, no
  preguntas ni afirmaciones del asesor.
- No confundas una pregunta del asesor ("¿de contado o financiada?") con una
  declaración del cliente.
- Cada campo con valor debe incluir su evidencia: una cita CORTA y LITERAL tomada de
  la conversación (máximo ~120 caracteres). Si el valor es null, la evidencia es null.
- Para montos de dinero, devuelve NÚMEROS (ej. 15000000), no texto. No inventes
  presupuesto ni cuota inicial: si el cliente no los menciona, van en null.
- No transformes una intención débil en intención alta. Si el cliente solo consulta
  precios, la intención es "informativa" o "baja".
- No uses conocimiento externo ni completes datos por sentido común.
- Usa exactamente los valores permitidos en los campos controlados.
- Si la conversación es ambigua o no aporta evidencia, devuelve null en los campos
  correspondientes.
"""


def _field_spec() -> str:
    return f"""\
Devuelve un JSON con esta estructura exacta:

{{
  "model_interes": string | null,        // modelo o línea de moto mencionada por el cliente
  "model_interes_evidence": string | null,
  "presupuesto": number | null,          // presupuesto explícito del cliente
  "presupuesto_evidence": string | null,
  "cuota_inicial": number | null,        // cuota inicial explícita del cliente
  "cuota_inicial_evidence": string | null,
  "forma_pago": {" | ".join(FORMA_PAGO_VALUES)} | null,
  "forma_pago_evidence": string | null,
  "intencion_compra": {" | ".join(INTENCION_VALUES)} | null,
  "intencion_compra_evidence": string | null,
  "objecion": {" | ".join(OBJECION_VALUES)} | null,
  "objecion_evidence": string | null,
  "solicitud_cita": true | false | null,
  "solicitud_cita_evidence": string | null,
  "solicitud_cotizacion": true | false | null,
  "solicitud_cotizacion_evidence": string | null
}}

Notas:
- "forma_pago": no la infieras; solo si el cliente la declara.
- "solicitud_cita" / "solicitud_cotizacion": usa false si la conversación deja claro
  que NO lo solicitó; null si no es concluyente.
- Campos requeridos: {", ".join(EXTRACTION_FIELDS)}.
"""


def build_messages(conversation: ConversationInput) -> list[dict[str, str]]:
    user_prompt = (
        f"{_field_spec()}\n"
        "Conversación (cliente/asesor):\n"
        "-----\n"
        f"{conversation.transcript()}\n"
        "-----\n"
        "Responde solo con el JSON."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
