"""Etiquetas de presentación para la UI.

Los códigos internos (razones del score) **no cambian**: siguen siendo la
identidad persistida en `lead_scores.reasons` y usada por el scoring. Aquí solo
se traducen a texto humano para mostrarlos. Si un código no tiene traducción, se
genera un fallback legible en lugar de exponer un identificador técnico crudo.
"""

from __future__ import annotations

import re

_NAME_WS = re.compile(r"\s+")
# Tras estos separadores se capitaliza la letra siguiente (María-José, O'Neill).
_NAME_CAPITALIZE_AFTER = ("'", "-")

# Etiquetas humanas de los códigos de razón del scoring v1.
SCORE_REASON_LABELS: dict[str, str] = {
    # Dimensión comercial
    "BASE_GESTIONABLE": "Base gestionable",
    "INTENCION_ALTA": "Intención de compra alta",
    "INTENCION_MEDIA": "Intención de compra media",
    "INTENCION_BAJA": "Intención de compra baja",
    "INTENCION_INFORMATIVA": "Intención informativa",
    "CLIENTE_PIDIO_CITA": "El cliente pidió cita",
    "CLIENTE_PIDIO_COTIZACION": "El cliente pidió cotización",
    "PRESUPUESTO_COMPATIBLE": "Presupuesto compatible",
    "PRESUPUESTO_INSUFICIENTE": "Presupuesto insuficiente",
    "CUOTA_SUFICIENTE": "Cuota inicial suficiente",
    "FORMA_PAGO_DECLARADA": "Forma de pago declarada",
    "OBJECION_PRECIO": "Objeción: precio",
    "OBJECION_CUOTA": "Objeción: cuota",
    "OBJECION_FINANCIACION": "Objeción: financiación",
    "OBJECION_DISPONIBILIDAD": "Objeción: disponibilidad",
    "OBJECION_TIEMPO": "Objeción: tiempo",
    "OBJECION_MODELO": "Objeción: modelo",
    "OBJECION_UBICACION": "Objeción: ubicación",
    "OBJECION_OTRA": "Objeción: otra",
    "TICKET_REGLA_NEGOCIO": "Regla de ticket",
    # Calidad del dato
    "TELEFONO_VALIDO": "Teléfono contactable",
    "MODELO_RESUELTO": "Modelo identificado",
    "EMAIL_PRESENTE": "Email registrado",
    "CIUDAD_PRESENTE": "Ciudad registrada",
    "FECHA_CONFIABLE": "Fecha de registro confiable",
    # Urgencia operativa
    "ESTADO_OPERATIVO": "Estado operativo",
    "ESTADO_DESCONOCIDO": "Estado de gestión desconocido",
    "URGENCIA_HOY_CITA": "Urgencia: cita hoy",
    "SIN_CONTACTO_MAS_48H": "Sin contacto por más de 48 h",
    "SIN_CONTACTO_24_48H": "Sin contacto entre 24 y 48 h",
    "SIN_GESTION_MAS_48H": "Sin gestión por más de 48 h",
    "FECHA_NO_CONFIABLE": "Fecha no confiable",
    # Informativo (documentado; puede no emitirse hoy)
    "DUPLICADO_PROBABLE": "Duplicado probable",
}

DIMENSION_LABELS: dict[str, str] = {
    "commercial": "Comercial",
    "quality": "Calidad",
    "urgency": "Urgencia",
}

SENDER_LABELS: dict[str, str] = {
    "cliente": "Cliente",
    "asesor": "Asesor",
}


def score_reason_label(code: str | None) -> str:
    """Traduce un código de razón a texto humano. Nunca devuelve el crudo."""
    if not code:
        return "Razón"
    text = str(code).strip()
    if text in SCORE_REASON_LABELS:
        return SCORE_REASON_LABELS[text]
    # Fallback legible: SOME_UNKNOWN_CODE -> "Some unknown code".
    return text.replace("_", " ").strip().lower().capitalize() or "Razón"


def dimension_label(dimension: str | None) -> str:
    if not dimension:
        return ""
    return DIMENSION_LABELS.get(str(dimension).strip().lower(), str(dimension).strip())


def sender_label(sender: str | None) -> str:
    """Etiqueta del emisor sin asumir cliente/asesor para valores desconocidos."""
    text = (sender or "").strip()
    if not text:
        return "Emisor desconocido"
    return SENDER_LABELS.get(text.lower(), text)


def sender_class(sender: str | None) -> str:
    """Clase CSS segura (no proviene del dato)."""
    key = (sender or "").strip().lower()
    return key if key in SENDER_LABELS else "otro"


def _capitalize_name_word(word: str) -> str:
    """Capitaliza la primera letra y baja el resto, conservando separadores."""
    out: list[str] = []
    capitalize_next = True
    for char in word:
        if char.isalpha():
            out.append(char.upper() if capitalize_next else char.lower())
            capitalize_next = False
        else:
            out.append(char)
            capitalize_next = char in _NAME_CAPITALIZE_AFTER
    return "".join(out)


def _normalize_name_word(word: str) -> str:
    """Normaliza solo palabras homogéneas (TODO mayúsculas o todo minúsculas).

    Si la palabra ya tiene capitalización mixta (p. ej. "McDonald", "MismoPos")
    se deja **intacta**: no inventamos ni corregimos la capitalización del dato.
    """
    has_upper = any(char.isupper() for char in word)
    has_lower = any(char.islower() for char in word)
    if has_upper and has_lower:
        return word
    return _capitalize_name_word(word)


def display_name(value: str | None) -> str | None:
    """Nombre listo para mostrar, de forma consistente.

    - ``strip`` externo y colapsa espacios internos repetidos;
    - normaliza la capitalización **solo** de palabras todo-mayúsculas o
      todo-minúsculas (p. ej. "BRAYAN TORRES OSORIO" → "Brayan Torres Osorio",
      "vanessa ramírez quintero" → "Vanessa Ramírez Quintero");
    - deja **intactas** las palabras con capitalización mixta ("Brayan TORRES
      Osorio" → "Brayan Torres Osorio"; "MismoPos" → "MismoPos");
    - **conserva tildes y Unicode** y no elimina caracteres válidos;
    - **no** corrige ortografía, **no** traduce, **no** reordena y **no** usa IA;
    - devuelve ``None`` si no hay contenido.

    No altera el valor almacenado: es una capa de **presentación**.
    """
    if value is None:
        return None
    text = _NAME_WS.sub(" ", str(value).strip())
    if not text:
        return None
    return " ".join(_normalize_name_word(word) for word in text.split(" "))
