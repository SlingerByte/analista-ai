from __future__ import annotations

import re
from collections import Counter

from .normalization import classify_date, phone_digits

INT_RE = re.compile(r"^-?\d+$")
FLOAT_RE = re.compile(r"^-?\d+[.,]\d+$")
ID_RE = re.compile(r"^[A-Z]{2,4}-\d+$")
BOOL_VALUES = {"si", "no"}


def infer_type(values: list[str]) -> str:
    present = [v.strip() for v in values if v is not None and v.strip() != ""]
    if not present:
        return "vacio"
    if all(INT_RE.match(v) for v in present):
        return "entero"
    if all(FLOAT_RE.match(v) for v in present):
        return "decimal"
    if all(ID_RE.match(v) for v in present):
        return "identificador"
    if all(v.lower() in BOOL_VALUES for v in present):
        return "booleano"
    parsed_dates = sum(1 for v in present if classify_date(v)["parsed"] is not None)
    if parsed_dates / len(present) >= 0.95:
        return "fecha"
    digit_lengths = {len(phone_digits(v)) for v in present}
    if digit_lengths and all(9 <= n <= 12 for n in digit_lengths) and all(
        any(ch.isdigit() for ch in v) for v in present
    ):
        return "telefono"
    return "texto"


def column_profile(rows: list[dict[str, str]], column: str) -> dict:
    values = [row.get(column, "") for row in rows]
    present = [v for v in values if v is not None and v.strip() != ""]
    counter = Counter(v.strip() for v in present)
    return {
        "columna": column,
        "tipo_inferido": infer_type(values),
        "nulos": len(values) - len(present),
        "pct_nulos": round(100 * (len(values) - len(present)) / len(values), 2) if values else 0.0,
        "valores_unicos": len(counter),
        "top_valores": counter.most_common(5),
        "ejemplos": [v for v, _ in counter.most_common(5)],
    }


def profile_table(rows: list[dict[str, str]], columns: list[str] | None = None) -> dict:
    columns = columns or list(rows[0].keys())
    return {
        "registros": len(rows),
        "columnas": columns,
        "perfil_columnas": [column_profile(rows, col) for col in columns],
    }


def profile_conversations(conversations: list[dict]) -> dict:
    message_keys = set()
    conversation_keys = set()
    messages = 0
    for conv in conversations:
        conversation_keys.update(conv.keys())
        for message in conv.get("mensajes", []):
            messages += 1
            message_keys.update(message.keys())
    return {
        "registros": len(conversations),
        "columnas": sorted(conversation_keys),
        "columnas_mensaje": sorted(message_keys),
        "mensajes_totales": messages,
    }
