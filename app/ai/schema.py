from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.ingestion.normalizers import strip_accents

SCHEMA_VERSION = "v1"

FORMA_PAGO_VALUES = ["contado", "financiacion", "credito", "tarjeta", "transferencia", "otro"]
INTENCION_VALUES = ["alta", "media", "baja", "informativa"]
OBJECION_VALUES = [
    "precio",
    "cuota",
    "financiacion",
    "disponibilidad",
    "tiempo",
    "modelo",
    "ubicacion",
    "otra",
]

EXTRACTION_FIELDS = [
    "model_interes",
    "presupuesto",
    "cuota_inicial",
    "forma_pago",
    "intencion_compra",
    "objecion",
    "solicitud_cita",
    "solicitud_cotizacion",
]

_FORMA_PAGO_SYNONYMS = {
    "contado": "contado",
    "efectivo": "contado",
    "financiacion": "financiacion",
    "financiamiento": "financiacion",
    "financiado": "financiacion",
    "financiada": "financiacion",
    "credito": "credito",
    "tarjeta": "tarjeta",
    "transferencia": "transferencia",
    "otro": "otro",
}

_INTENCION_SYNONYMS = {
    "alta": "alta",
    "alto": "alta",
    "media": "media",
    "medio": "media",
    "baja": "baja",
    "bajo": "baja",
    "informativa": "informativa",
    "informativo": "informativa",
    "informacion": "informativa",
    "consulta": "informativa",
}

_OBJECION_SYNONYMS = {
    "precio": "precio",
    "precios": "precio",
    "cuota": "cuota",
    "cuotas": "cuota",
    "financiacion": "financiacion",
    "disponibilidad": "disponibilidad",
    "tiempo": "tiempo",
    "modelo": "modelo",
    "ubicacion": "ubicacion",
    "lugar": "ubicacion",
    "otra": "otra",
    "otro": "otra",
}

_TRUE_VALUES = {"true", "si", "yes", "1"}
_FALSE_VALUES = {"false", "no", "0"}


def _normalize_token(value) -> str | None:
    if value is None:
        return None
    token = strip_accents(str(value).strip().lower())
    return token or None


def _parse_amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("amount cannot be boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("$", "").replace(" ", "")
        if text == "":
            return None
        if not re.fullmatch(r"[\d.,]+", text):
            raise ValueError("amount must be numeric")
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            raise ValueError("amount must be numeric")
        return float(digits)
    raise ValueError("unsupported amount type")


def _parse_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = strip_accents(value.strip().lower())
        if token in _TRUE_VALUES:
            return True
        if token in _FALSE_VALUES:
            return False
    raise ValueError("boolean must be true/false/null")


def _parse_controlled(value, synonyms: dict[str, str]):
    token = _normalize_token(value)
    if token is None:
        return None
    if token not in synonyms:
        raise ValueError(f"value not allowed: {token}")
    return synonyms[token]


class ExtractionResult(BaseModel):
    """Versioned extraction schema (benchmark). Every value has a literal evidence quote."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = SCHEMA_VERSION

    model_interes: str | None = None
    model_interes_evidence: str | None = None

    presupuesto: float | None = None
    presupuesto_evidence: str | None = None

    cuota_inicial: float | None = None
    cuota_inicial_evidence: str | None = None

    forma_pago: Literal["contado", "financiacion", "credito", "tarjeta", "transferencia", "otro"] | None = None
    forma_pago_evidence: str | None = None

    intencion_compra: Literal["alta", "media", "baja", "informativa"] | None = None
    intencion_compra_evidence: str | None = None

    objecion: Literal[
        "precio",
        "cuota",
        "financiacion",
        "disponibilidad",
        "tiempo",
        "modelo",
        "ubicacion",
        "otra",
    ] | None = None
    objecion_evidence: str | None = None

    solicitud_cita: bool | None = None
    solicitud_cita_evidence: str | None = None

    solicitud_cotizacion: bool | None = None
    solicitud_cotizacion_evidence: str | None = None

    @field_validator("presupuesto", "cuota_inicial", mode="before")
    @classmethod
    def _validate_amount(cls, value):
        return _parse_amount(value)

    @field_validator("solicitud_cita", "solicitud_cotizacion", mode="before")
    @classmethod
    def _validate_bool(cls, value):
        return _parse_bool(value)

    @field_validator("forma_pago", mode="before")
    @classmethod
    def _validate_forma_pago(cls, value):
        return _parse_controlled(value, _FORMA_PAGO_SYNONYMS)

    @field_validator("intencion_compra", mode="before")
    @classmethod
    def _validate_intencion(cls, value):
        return _parse_controlled(value, _INTENCION_SYNONYMS)

    @field_validator("objecion", mode="before")
    @classmethod
    def _validate_objecion(cls, value):
        return _parse_controlled(value, _OBJECION_SYNONYMS)

    @field_validator(
        "model_interes_evidence",
        "presupuesto_evidence",
        "cuota_inicial_evidence",
        "forma_pago_evidence",
        "intencion_compra_evidence",
        "objecion_evidence",
        "solicitud_cita_evidence",
        "solicitud_cotizacion_evidence",
        mode="before",
    )
    @classmethod
    def _validate_evidence(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return str(value).strip() or None

    @model_validator(mode="after")
    def _clear_evidence_without_value(self):
        for field in EXTRACTION_FIELDS:
            if getattr(self, field) is None:
                setattr(self, f"{field}_evidence", None)
        return self

    def fields_with_evidence(self) -> int:
        return sum(
            1
            for field in EXTRACTION_FIELDS
            if getattr(self, field) is not None and getattr(self, f"{field}_evidence") is not None
        )

    def fields_extracted(self) -> int:
        return sum(1 for field in EXTRACTION_FIELDS if getattr(self, field) is not None)


class Message(BaseModel):
    sender: str
    text: str
    hour: str | None = None


class ConversationInput(BaseModel):
    conversation_id: str
    lead_id: str | None = None
    channel: str | None = None
    messages: list[Message]

    def transcript(self) -> str:
        lines = []
        for message in self.messages:
            lines.append(f"{message.sender}: {message.text}")
        return "\n".join(lines)
