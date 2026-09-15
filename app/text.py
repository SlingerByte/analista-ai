"""Utilidades de texto deterministas compartidas.

Centran las operaciones de normalización de texto que antes vivían en
``app.ingestion.normalizers`` para poder reutilizarlas desde la capa de
canonicalización sin dependencias circulares.
"""

from __future__ import annotations

import re
import unicodedata


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_key(value: str | None) -> str:
    """Clave de comparación: minúsculas, sin acentos y con espacios colapsados."""
    if value is None:
        return ""
    text = strip_accents(str(value).strip().lower())
    return re.sub(r"\s+", " ", text)


def clean_display(value: str | None) -> str | None:
    """Limpieza segura para mostrar: trim + espacios repetidos.

    No cambia mayúsculas ni acentos ni el orden de las palabras: no altera la
    identidad del valor.
    """
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None
