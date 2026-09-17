"""Clasificación técnica segura de errores de proveedores de IA.

Uso interno (diagnóstico/logs). Nunca contiene secretos y **nunca** se muestra
en crudo al usuario final: la UI usa :func:`humanize_ai_error_text`.
"""

from __future__ import annotations

PROVIDER_AUTH = "provider_auth"
PROVIDER_RATE_LIMIT = "provider_rate_limit"
PROVIDER_BAD_REQUEST = "provider_bad_request"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_TIMEOUT = "provider_timeout"
INVALID_MODEL_RESPONSE = "invalid_model_response"
SCHEMA_VALIDATION = "schema_validation"
EVIDENCE_VALIDATION = "evidence_validation"
UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"

_HUMAN = {
    PROVIDER_RATE_LIMIT: ("El proveedor de IA está temporalmente limitado. Intenta "
                          "nuevamente en unos minutos o selecciona otro proveedor."),
    PROVIDER_AUTH: "El proveedor de IA no está correctamente configurado.",
    PROVIDER_TIMEOUT: "El proveedor de IA tardó demasiado en responder.",
    PROVIDER_UNAVAILABLE: "No fue posible conectar con el proveedor de IA.",
    PROVIDER_BAD_REQUEST: "El proveedor de IA no pudo procesar esta conversación.",
    INVALID_MODEL_RESPONSE: "El proveedor de IA no pudo procesar esta conversación.",
    SCHEMA_VALIDATION: "El proveedor de IA no pudo procesar esta conversación.",
    EVIDENCE_VALIDATION: "El proveedor de IA no pudo procesar esta conversación.",
    UNKNOWN_PROVIDER_ERROR: "No fue posible completar el análisis.",
}


def classify_ai_error(text: str | None) -> str:
    """Categoría técnica segura a partir del mensaje sanitizado del proveedor."""
    token = (text or "").lower()
    if not token:
        return UNKNOWN_PROVIDER_ERROR
    if "429" in token or "rate limit" in token or "too many requests" in token:
        return PROVIDER_RATE_LIMIT
    if ("401" in token or "403" in token or "unauthorized" in token
            or "forbidden" in token or "invalid api key" in token
            or "authentication" in token):
        return PROVIDER_AUTH
    if "timeout" in token or "timed out" in token:
        return PROVIDER_TIMEOUT
    if ("500" in token or "502" in token or "503" in token or "504" in token
            or "unavailable" in token):
        return PROVIDER_UNAVAILABLE
    if "400" in token or "bad request" in token or "invalid_request" in token:
        return PROVIDER_BAD_REQUEST
    if ("no choices" in token or "invalid json" in token
            or "could not parse" in token):
        return INVALID_MODEL_RESPONSE
    if "schema" in token:
        return SCHEMA_VALIDATION
    if "evidence" in token:
        return EVIDENCE_VALIDATION
    if ("network" in token or "urlerror" in token or "connection" in token
            or "unreachable" in token or "refused" in token):
        return PROVIDER_UNAVAILABLE
    return UNKNOWN_PROVIDER_ERROR


def humanize_ai_error(code: str) -> str:
    """Mensaje amigable (sin detalles técnicos) para una categoría."""
    return _HUMAN.get(code, _HUMAN[UNKNOWN_PROVIDER_ERROR])


def humanize_ai_error_text(text: str | None) -> str:
    return humanize_ai_error(classify_ai_error(text))


__all__ = [
    "PROVIDER_AUTH", "PROVIDER_RATE_LIMIT", "PROVIDER_BAD_REQUEST",
    "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "INVALID_MODEL_RESPONSE",
    "SCHEMA_VALIDATION", "EVIDENCE_VALIDATION", "UNKNOWN_PROVIDER_ERROR",
    "classify_ai_error", "humanize_ai_error", "humanize_ai_error_text",
]
