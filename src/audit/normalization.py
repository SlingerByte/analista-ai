from __future__ import annotations

import datetime as _dt
import re
import unicodedata


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_key(value: str | None) -> str:
    if value is None:
        return ""
    text = strip_accents(str(value).strip().lower())
    text = re.sub(r"\s+", " ", text)
    return text


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
    return value.strip()


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
    return ESTADO_CANONICAL.get(key, value.strip())


CIUDAD_ALIASES = {
    "bogota d.c.": "bogota",
    "bogota dc": "bogota",
    "cartagena de indias": "cartagena",
    "sta marta": "santa marta",
    "rio negro": "rionegro",
    "b/quilla": "barranquilla",
    "itagui": "itagui",
}


def normalize_ciudad(value: str | None) -> str | None:
    key = normalize_key(value)
    if not key:
        return None
    return CIUDAD_ALIASES.get(key, key)


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


def phone_format(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "vacio"
    if re.fullmatch(r"\d{10}", text):
        return "plano_10"
    if re.fullmatch(r"57\d{10}", text):
        return "prefijo_57_sin_signo"
    if re.fullmatch(r"\+57\d{10}", text):
        return "prefijo_57_con_signo"
    if re.fullmatch(r"\+?57[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{4}", text):
        return "prefijo_57_separado"
    if re.fullmatch(r"\d{3}[\s-]\d{3}[\s-]\d{4}", text):
        return "separado_10"
    if re.fullmatch(r"\(\d{3}\)[\s-]?\d{3}[\s-]?\d{4}", text):
        return "parentesis"
    return "otro"


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
    text = re.sub(r"\br 3\b", "r3", text)
    return text
