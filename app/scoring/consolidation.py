"""Consolidación determinista de extracciones IA por lead.

Transforma ``AIExtraction[]`` (una fila por conversación) en las señales IA de
``LeadSignals``. Función pura: mismo conjunto de filas → mismo resultado.

Reglas (conservadoras, sin invención):

- Solo filas con ``status == "success"`` y ``fields`` dict. Las filas `error`
  se ignoran como señal (quedan trazadas en ``had_error``).
- El precio/modelo NO sale de la IA: viene del pipeline (Lead.sku → catálogo).
  ``model_interes`` de la IA nunca se convierte en precio ni en presupuesto.
- Recencia = mayor ``extraction_id`` (orden de procesamiento, determinista).
- En conflictos se prefiere el valor más reciente; a igualdad, el que trae
  evidencia.
- La validez de la evidencia se garantiza **antes** de persistir, en
  ``app/ai/validation.py`` (evidencia literal del cliente + monto en campos
  monetarios). Aquí se consolida lo ya validado: un campo sin evidencia válida
  nunca llega a ``fields``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.service import STATUS_SUCCESS

INTENCION_RANK = {"alta": 4, "media": 3, "baja": 2, "informativa": 1}


@dataclass(frozen=True)
class ConsolidatedAI:
    intencion_compra: str | None = None
    solicitud_cita: bool | None = None
    solicitud_cotizacion: bool | None = None
    forma_pago: str | None = None
    presupuesto: float | None = None
    cuota_inicial: float | None = None
    objecion: str | None = None
    # Trazabilidad: campo → extraction_id que aportó el valor.
    sources: dict = field(default_factory=dict)
    # Hubo filas en error (informativo; nunca es señal).
    had_error: bool = False


def _norm_token(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    token = str(value).strip().lower()
    return token or None


def _has_evidence(fields: dict, name: str) -> bool:
    evidence = fields.get(f"{name}_evidence")
    return isinstance(evidence, str) and bool(evidence.strip())


def _to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_latest(candidates: list[tuple]) -> tuple | None:
    """Elige (has_evidence, extraction_id, value); None si vacío."""
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]))[-1]


def consolidate_lead_extractions(extractions: list) -> ConsolidatedAI:
    """Consolida las extracciones vigentes de un lead. Determinista."""
    rows = sorted(
        (
            row
            for row in extractions
            if row.status == STATUS_SUCCESS and isinstance(row.fields, dict)
        ),
        key=lambda row: row.extraction_id,
    )
    had_error = any(row.status != STATUS_SUCCESS for row in extractions)
    sources: dict[str, int] = {}

    intencion: str | None = None
    intencion_rank = 0
    intencion_source: int | None = None
    for row in rows:
        token = _norm_token(row.fields.get("intencion_compra"))
        rank = INTENCION_RANK.get(token, 0) if token else 0
        if rank > intencion_rank or (
            rank > 0 and rank == intencion_rank and row.extraction_id > (intencion_source or 0)
        ):
            intencion, intencion_rank, intencion_source = token, rank, row.extraction_id
    if intencion_source is not None:
        sources["intencion_compra"] = intencion_source

    def pick_bool(name: str) -> bool | None:
        picked = None
        for row in rows:
            value = row.fields.get(name)
            if value is True:
                picked = (True, row.extraction_id)
            elif value is False and picked is None:
                picked = (False, row.extraction_id)
        if picked is not None:
            sources[name] = picked[1]
            return picked[0]
        return None

    cita = pick_bool("solicitud_cita")
    cotizacion = pick_bool("solicitud_cotizacion")

    def pick_token(name: str) -> str | None:
        candidates = [
            (_has_evidence(row.fields, name), row.extraction_id, _norm_token(row.fields.get(name)))
            for row in rows
        ]
        candidates = [item for item in candidates if item[2] is not None]
        picked = _pick_latest(candidates)
        if picked is not None:
            sources[name] = picked[1]
            return picked[2]
        return None

    def pick_amount(name: str) -> float | None:
        candidates = [
            (_has_evidence(row.fields, name), row.extraction_id, _to_float(row.fields.get(name)))
            for row in rows
        ]
        candidates = [item for item in candidates if item[2] is not None]
        picked = _pick_latest(candidates)
        if picked is not None:
            sources[name] = picked[1]
            return picked[2]
        return None

    forma_pago = pick_token("forma_pago")
    objecion = pick_token("objecion")
    presupuesto = pick_amount("presupuesto")
    cuota_inicial = pick_amount("cuota_inicial")

    return ConsolidatedAI(
        intencion_compra=intencion,
        solicitud_cita=cita,
        solicitud_cotizacion=cotizacion,
        forma_pago=forma_pago,
        presupuesto=presupuesto,
        cuota_inicial=cuota_inicial,
        objecion=objecion,
        sources=sources,
        had_error=had_error,
    )
