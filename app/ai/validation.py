"""Validación determinista de la evidencia extraída por el LLM.

Principio: la IA interpreta, el sistema valida. El modelo puede proponer un
valor, pero solo se persiste y llega al scoring si su evidencia es una cita
literal de un mensaje **del cliente** y, en campos monetarios, si la cita
contiene realmente el monto.

La validación es 100% determinista (sin otro LLM, sin red): normaliza texto y
compara subcadenas, y parsea expresiones monetarias simples.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.ai.schema import EXTRACTION_FIELDS, ExtractionResult

# Campos monetarios: además de pertenecer al cliente, la evidencia debe
# contener el monto declarado (no basta una frase genérica).
AMOUNT_FIELDS = frozenset({"presupuesto", "cuota_inicial"})

# Respuestas de cortesía/ambiguas: no son evidencia suficiente por sí solas.
NON_INFORMATIVE_REPLIES = frozenset(
    {
        "dale",
        "ok",
        "okay",
        "bueno",
        "buena",
        "buenas",
        "listo",
        "lista",
        "si",
        "claro",
        "gracias",
        "de acuerdo",
        "perfecto",
        "entendido",
        "vale",
        "hola",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "ya",
        "esta bien",
        "muchas gracias",
    }
)

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_AMOUNT_MILLIONS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(millones|millon|palo|palos)", re.IGNORECASE
)
_AMOUNT_THOUSANDS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mil|k)\b", re.IGNORECASE
)
_AMOUNT_DOLLAR_RE = re.compile(r"\$\s*([\d.,]+)")
_AMOUNT_PLAIN_RE = re.compile(r"\b(\d{5,})\b")
_AMOUNT_GROUPED_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d{3})+)\b")

# El modelo suele citar con el emisor delante ("cliente: ..."). Se reconoce el
# prefijo para no rechazar evidencia válida, pero el emisor se valida: una
# cita atribuida al asesor nunca cuenta como evidencia del cliente.
_SENDER_ALIASES = {
    "cliente": "cliente",
    "client": "cliente",
    "customer": "cliente",
    "usuario": "cliente",
    "asesor": "asesor",
    "advisor": "asesor",
    "agent": "asesor",
    "agente": "asesor",
    "vendedor": "asesor",
}
_PREFIX_RE = re.compile(r"^\s*([^\s:]+)\s*:\s*(.*)$", re.DOTALL)


@dataclass(frozen=True)
class EvidenceValidation:
    """Resultado de validar una extracción contra la conversación."""

    extraction: ExtractionResult
    # campo -> motivo de invalidación (el campo quedó en null)
    invalidated: dict[str, str] = field(default_factory=dict)
    # campos con valor y evidencia válida del cliente
    validated: tuple[str, ...] = ()


def _strip_accents_lower(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _normalize_for_match(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _PUNCT_RE.sub(" ", _strip_accents_lower(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _evidence_in(evidence: str, messages: Sequence[str]) -> bool:
    needle = _normalize_for_match(evidence)
    if not needle:
        return False
    return any(needle in _normalize_for_match(message) for message in messages)


def _is_non_informative(evidence: str) -> bool:
    return _normalize_for_match(evidence) in NON_INFORMATIVE_REPLIES


def _split_evidence(evidence: str) -> tuple[str | None, str]:
    """Separa un prefijo de emisor conocido del cuerpo de la cita.

    Devuelve ``(emisor_canónico | None, cuerpo)``. Solo reconoce prefijos de
    emisor conocidos para no confundir dos puntos legítimos dentro de la cita.
    """
    match = _PREFIX_RE.match(evidence)
    if match:
        token = _strip_accents_lower(match.group(1)).strip()
        if token in _SENDER_ALIASES:
            return _SENDER_ALIASES[token], match.group(2)
    return None, evidence


def _to_float(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    if "," in token:
        # Formato local: coma decimal, punto de miles.
        token = token.replace(".", "").replace(",", ".")
    elif "." in token:
        parts = token.split(".")
        if len(parts) >= 2 and all(len(part) == 3 for part in parts[1:]):
            token = "".join(parts)
    try:
        return float(token)
    except ValueError:
        return None


def amounts_in_text(text: str) -> list[float]:
    """Extrae montos plausibles en pesos de un texto (determinista)."""
    cleaned = _strip_accents_lower(text)
    amounts: list[float] = []
    for match in _AMOUNT_MILLIONS_RE.finditer(cleaned):
        value = _to_float(match.group(1))
        if value is not None:
            amounts.append(value * 1_000_000)
    for match in _AMOUNT_THOUSANDS_RE.finditer(cleaned):
        value = _to_float(match.group(1))
        if value is not None:
            amounts.append(value * 1_000)
    for match in _AMOUNT_DOLLAR_RE.finditer(cleaned):
        value = _to_float(match.group(1))
        if value is not None:
            amounts.append(value)
    for match in _AMOUNT_GROUPED_RE.finditer(cleaned):
        value = _to_float(match.group(1))
        if value is not None:
            amounts.append(value)
    for match in _AMOUNT_PLAIN_RE.finditer(cleaned):
        amounts.append(float(match.group(1)))
    return amounts


def amount_matches_evidence(value: float, evidence: str) -> bool:
    target = float(value)
    for amount in amounts_in_text(evidence):
        if abs(amount - target) <= max(1.0, abs(target) * 1e-6):
            return True
    return False


def _invalidation_reason(
    name: str,
    value: object,
    evidence: str | None,
    client_messages: Sequence[str],
    advisor_messages: Sequence[str],
) -> str | None:
    if not isinstance(evidence, str) or not evidence.strip():
        return "missing_evidence"
    attributed_to, body = _split_evidence(evidence)
    if not body.strip():
        return "missing_evidence"
    if _is_non_informative(body):
        return "non_informative_evidence"
    # La evidencia debe corresponder a un mensaje del cliente. El prefijo
    # declarado se respeta: "asesor: ..." nunca valida un campo del cliente.
    if attributed_to == "asesor":
        return "advisor_evidence"
    if not _evidence_in(body, client_messages):
        if _evidence_in(body, advisor_messages):
            return "advisor_evidence"
        return "evidence_not_in_conversation"
    if name in AMOUNT_FIELDS and not amount_matches_evidence(value, body):
        return "amount_not_in_evidence"
    return None


def validate_extraction(
    extraction: ExtractionResult,
    client_messages: Sequence[str],
    advisor_messages: Sequence[str],
) -> EvidenceValidation:
    """Valida campo por campo la extracción contra la conversación.

    Un campo con valor pero sin evidencia válida del cliente se invalida a
    ``null``; el resto de la extracción se conserva. Nunca lanza por campos
    individuales.
    """
    data = extraction.model_dump()
    invalidated: dict[str, str] = {}
    validated: list[str] = []

    for name in EXTRACTION_FIELDS:
        value = data.get(name)
        if value is None:
            continue
        reason = _invalidation_reason(
            name,
            value,
            data.get(f"{name}_evidence"),
            client_messages,
            advisor_messages,
        )
        if reason is None:
            validated.append(name)
        else:
            data[name] = None
            data[f"{name}_evidence"] = None
            invalidated[name] = reason

    cleaned = ExtractionResult.model_validate(data)
    return EvidenceValidation(
        extraction=cleaned,
        invalidated=invalidated,
        validated=tuple(validated),
    )


def split_transcript_messages(messages: Iterable[dict]) -> tuple[list[str], list[str]]:
    """Separa textos de cliente y de contexto (asesor u otros)."""
    client: list[str] = []
    context: list[str] = []
    for message in messages:
        text = str(message.get("text") or "")
        if not text.strip():
            continue
        if str(message.get("sender") or "").strip() == "cliente":
            client.append(text)
        else:
            context.append(text)
    return client, context
