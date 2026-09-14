from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from typing import Any


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_key(value: str | None) -> str:
    if value is None:
        return ""
    text = strip_accents(str(value).strip().lower())
    return re.sub(r"\s+", " ", text)


def pick(mapping: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


CANAL_CANONICAL = {
    "whatsapp": "WhatsApp",
    "meta ads": "Meta Ads",
    "formulario web": "Formulario Web",
}


def normalize_canal(value: str | None) -> str | None:
    key = normalize_key(value)
    if not key:
        return None
    if key in CANAL_CANONICAL:
        return CANAL_CANONICAL[key]
    if "whats" in key:
        return "WhatsApp"
    if "meta" in key:
        return "Meta Ads"
    if "form" in key:
        return "Formulario Web"
    return str(value).strip()


ESTADO_CANONICAL = {
    "contactado": "Contactado",
    "sin gestion": "Sin gestión",
    "cotizacion enviada": "Cotización enviada",
    "en proceso": "En proceso",
    "no contesta": "No contesta",
    "descartado": "Descartado",
}


def normalize_estado(value: str | None) -> str | None:
    key = normalize_key(value)
    if not key:
        return None
    return ESTADO_CANONICAL.get(key, str(value).strip())


CITY_CANONICAL = {
    "bogota": "Bogotá",
    "medellin": "Medellín",
    "bello": "Bello",
    "monteria": "Montería",
    "soacha": "Soacha",
    "soledad": "Soledad",
    "cartagena": "Cartagena",
    "barranquilla": "Barranquilla",
    "santa marta": "Santa Marta",
    "itagui": "Itagüí",
    "rionegro": "Rionegro",
}

CITY_ALIASES = {
    "bogota d.c.": "bogota",
    "bogota dc": "bogota",
    "cartagena de indias": "cartagena",
    "sta marta": "santa marta",
    "rio negro": "rionegro",
    "b/quilla": "barranquilla",
}


def normalize_city(value: str | None) -> tuple[str | None, str, bool]:
    key = normalize_key(value)
    if not key:
        return None, "", False
    resolved = CITY_ALIASES.get(key, key)
    label = CITY_CANONICAL.get(resolved)
    if label is None:
        return None, resolved, False
    return label, resolved, True


PHONE_SPLIT_RE = re.compile(r"[^\d]")


def phone_digits(value: str | None) -> str:
    return PHONE_SPLIT_RE.sub("", value or "")


def normalize_phone(value: str | None) -> str | None:
    digits = phone_digits(value)
    if not digits:
        return None
    if len(digits) == 12 and digits.startswith("57"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("57"):
        digits = digits[2:]
    return digits


def is_valid_phone(value: str | None) -> bool:
    normalized = normalize_phone(value)
    return normalized is not None and len(normalized) == 10


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str | None) -> bool:
    text = (value or "").strip()
    return bool(text) and bool(EMAIL_RE.match(text))


def normalize_email(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    return text or None


ISO_FORMATS = [
    ("%Y-%m-%dT%H:%M:%S", "ISO_T"),
    ("%Y-%m-%d %H:%M:%S", "ISO_SPACE"),
    ("%Y-%m-%d", "ISO_DATE"),
]

SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+\d{1,2}:\d{2})?$")
DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?:\s+\d{1,2}:\d{2})?$")


def _parse(text: str, fmt: str):
    try:
        return _dt.datetime.strptime(text, fmt)
    except ValueError:
        return None


def classify_date(value: str | None) -> dict:
    text = (value or "").strip()
    if not text:
        return {"format": "vacio", "ambiguous": False, "parsed": None}

    for fmt, label in ISO_FORMATS:
        parsed = _parse(text, fmt)
        if parsed is not None:
            return {"format": label, "ambiguous": False, "parsed": parsed}

    match = SLASH_RE.match(text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        has_time = " " in text
        if first > 12:
            parsed = _parse(text, "%d/%m/%Y %H:%M" if has_time else "%d/%m/%Y")
            return {"format": "DD/MM/YYYY", "ambiguous": False, "parsed": parsed}
        if second > 12:
            parsed = _parse(text, "%m/%d/%Y %H:%M" if has_time else "%m/%d/%Y")
            return {"format": "MM/DD/YYYY", "ambiguous": False, "parsed": parsed}
        parsed = _parse(text, "%d/%m/%Y %H:%M" if has_time else "%d/%m/%Y")
        return {"format": "DD/MM/YYYY vs MM/DD/YYYY", "ambiguous": True, "parsed": parsed}

    match = DASH_RE.match(text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        has_time = " " in text
        ambiguous = first <= 12 and second <= 12
        parsed = _parse(text, "%d-%m-%Y %H:%M" if has_time else "%d-%m-%Y")
        return {"format": "DD-MM-YYYY", "ambiguous": ambiguous, "parsed": parsed}

    return {"format": "desconocido", "ambiguous": False, "parsed": None}


def normalized_date_value(info: dict) -> _dt.datetime | None:
    """Return the value to persist: NULL for genuinely ambiguous slash dates.

    Dash dates are parsed as DD-MM-YYYY by the convention documented in the
    audit and flagged as ambiguous-by-convention in normalization metadata.
    """
    parsed = info.get("parsed")
    if parsed is None:
        return None
    if info.get("format") == "DD-MM-YYYY":
        return parsed
    if info.get("ambiguous"):
        return None
    return parsed


def date_reason(info: dict) -> str:
    fmt = info.get("format")
    if fmt == "vacio":
        return "empty value"
    if info.get("parsed") is None:
        return "unrecognized or impossible date"
    if fmt == "DD/MM/YYYY vs MM/DD/YYYY":
        return "slash date ambiguous between DD/MM and MM/DD"
    if fmt == "DD-MM-YYYY" and info.get("ambiguous"):
        return "dash date with day and month <= 12, parsed as DD-MM by documented convention"
    return "unambiguous"


BRAND_TYPOS = {
    "bajai": "bajaj",
    "hnda": "honda",
    "heroo": "hero",
    "suzuky": "suzuki",
    "akt": "akt",
}


def normalize_model_text(value: str | None) -> str:
    text = normalize_key(value)
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = text.replace(".", " ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = [BRAND_TYPOS.get(token, token) for token in text.split()]
    text = " ".join(tokens)
    text = text.replace("a k t", "akt")
    return re.sub(r"\br 3\b", "r3", text)


SENDER_ALIASES = {
    "cliente": "cliente",
    "client": "cliente",
    "customer": "cliente",
    "asesor": "asesor",
    "advisor": "asesor",
    "agent": "asesor",
    "agente": "asesor",
}


def normalize_sender(value: str | None) -> str:
    key = normalize_key(value)
    return SENDER_ALIASES.get(key, str(value or "").strip())


def normalize_messages(raw_messages: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_messages, list):
        return []
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_messages, start=1):
        if not isinstance(raw, dict):
            continue
        messages.append(
            {
                "seq": index,
                "sender": normalize_sender(
                    pick(raw, ["emisor", "sender", "rol", "role", "tipo"])
                ),
                "hour": str(pick(raw, ["hora", "hour", "time"], "") or ""),
                "text": str(pick(raw, ["texto", "text", "mensaje", "message"], "") or ""),
            }
        )
    return messages
