"""Capa general de canonicalización de valores categóricos.

Regla: **normalizar para comparar, conservar el original para trazabilidad y
mostrar una representación canónica cuando exista una resolución confiable**.

- ``raw``: el valor original recibido (nunca se modifica).
- ``key``: clave normalizada para comparar (minúsculas, sin acentos, espacios
  colapsados, alias aplicado si corresponde).
- ``canonical``: representación canónica a mostrar, o ``None`` si el valor no
  es resoluble de forma confiable.
- ``status``: ``empty`` | ``resolved`` | ``unresolved``.

El catálogo es pequeño y mantenible (solo valores conocidos). Un valor
desconocido conserva su ``key`` y queda ``unresolved``: **no se inventa** una
equivalencia ni se hace fuzzy matching.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.text import normalize_key

STATUS_EMPTY = "empty"
STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CanonicalValue:
    raw: str | None
    key: str
    canonical: str | None
    status: str
    method: str

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED


# Catálogo de ciudades conocidas: clave normalizada → representación canónica.
# Fuente pequeña y mantenible (ciudades presentes en los datos + ejemplos del
# alcance). No es un GIS ni un geocoder.
CITY_CANONICAL: dict[str, str] = {
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
    "cali": "Cali",
}

# Alias basados en evidencia: clave normalizada alternativa → clave canónica.
CITY_ALIASES: dict[str, str] = {
    "bogota d.c.": "bogota",
    "bogota dc": "bogota",
    "cartagena de indias": "cartagena",
    "sta marta": "santa marta",
    "rio negro": "rionegro",
    "b/quilla": "barranquilla",
    "itagui": "itagui",
}


def resolve(
    value: object | None,
    catalog: dict[str, str],
    aliases: dict[str, str] | None = None,
    *,
    method: str,
) -> CanonicalValue:
    """Resuelve un valor contra un catálogo canónico. Determinista y sin fuzzy."""
    raw = None if value is None else str(value).strip() or None
    key = normalize_key(None if value is None else str(value))
    if not key:
        return CanonicalValue(
            raw=raw, key="", canonical=None, status=STATUS_EMPTY, method=method
        )
    resolved_key = (aliases or {}).get(key, key)
    canonical = catalog.get(resolved_key)
    if canonical is None:
        return CanonicalValue(
            raw=raw,
            key=resolved_key,
            canonical=None,
            status=STATUS_UNRESOLVED,
            method=method,
        )
    return CanonicalValue(
        raw=raw,
        key=resolved_key,
        canonical=canonical,
        status=STATUS_RESOLVED,
        method=method,
    )


def resolve_city(value: object | None) -> CanonicalValue:
    return resolve(value, CITY_CANONICAL, CITY_ALIASES, method="city_canonical")
