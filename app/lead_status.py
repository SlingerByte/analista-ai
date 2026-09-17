"""Ciclo de vida del lead: estados abiertos/terminales y transición de cierre.

Única fuente de verdad para assignment, dashboard y acciones de gestión. No
introduce semántica de negocio nueva: clasifica los estados ya existentes de
``leads.status`` y agrega los terminales explícitos ``Cerrado``/``Perdido``.

Regla de clasificación: un lead es **terminal** si su estado está en
``TERMINAL_STATUSES``; en cualquier otro caso se considera **abierto**
(incluye estados desconocidos o nulos, para no dejar leads sin gestionar por
un valor inesperado). ``Descartado`` sigue siendo terminal.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.leads import Lead

OPEN_STATUSES: tuple[str, ...] = (
    "Sin gestión",
    "Contactado",
    "No contesta",
    "Cotización enviada",
    "En proceso",
)

TERMINAL_STATUSES: tuple[str, ...] = (
    "Cerrado",
    "Perdido",
    "Descartado",
)

CLOSE_REASONS: tuple[str, ...] = (
    "Venta realizada",
    "Cliente desistió",
    "No interesado",
    "Datos inválidos",
    "Otro",
)

DEFAULT_CLOSE_REASON = "Otro"

ALL_STATUSES: tuple[str, ...] = OPEN_STATUSES + TERMINAL_STATUSES

_OPEN_SET = frozenset(OPEN_STATUSES)
_TERMINAL_SET = frozenset(TERMINAL_STATUSES)
_CLOSE_REASON_SET = frozenset(CLOSE_REASONS)


class LeadTransitionError(ValueError):
    """Transición de estado inválida (p. ej. reabrir un lead terminal)."""


def is_lead_terminal(status: str | None) -> bool:
    return status in _TERMINAL_SET


def is_lead_open(status: str | None) -> bool:
    return not is_lead_terminal(status)


def is_known_status(status: str | None) -> bool:
    return status in _OPEN_SET or status in _TERMINAL_SET


def normalize_close_reason(reason: str | None) -> str | None:
    text = (reason or "").strip()
    return text if text in _CLOSE_REASON_SET else None


def update_lead_status(
    session: Session,
    lead: Lead,
    new_status: str,
    *,
    close_reason: str | None = None,
) -> Lead:
    """Aplica una transición de estado controlada y persiste (commit).

    - No permite reabrir un lead terminal (terminal → abierto).
    - Cerrar (estado terminal) fija ``closed_at`` y ``close_reason``.
    - Volver a un estado abierto limpia los campos de cierre.
    """
    if not is_known_status(new_status):
        raise LeadTransitionError(f"estado desconocido: {new_status!r}")
    if is_lead_terminal(lead.status) and is_lead_open(new_status):
        raise LeadTransitionError("no se permite reabrir un lead terminal")

    lead.status = new_status
    if is_lead_terminal(new_status):
        if lead.closed_at is None:
            lead.closed_at = datetime.now(timezone.utc)
        lead.close_reason = (
            normalize_close_reason(close_reason)
            or normalize_close_reason(lead.close_reason)
            or DEFAULT_CLOSE_REASON
        )
    else:
        lead.closed_at = None
        lead.close_reason = None

    session.add(lead)
    session.commit()
    return lead
