"""Conexión extracción → scoring → persistencia por lead.

``prepare_lead_signals`` arma ``LeadSignals`` desde las tablas (Lead +
catálogo + conversaciones + extracciones vigentes). ``score_and_persist_lead``
calcula con ``score_lead`` (pesos v1 intactos) y guarda en ``LeadScore`` de
forma idempotente con el patrón ``is_current``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.service import lead_extractions
from app.scoring.consolidation import consolidate_lead_extractions
from app.scoring.engine import (
    SCORE_V1_PARAMS,
    ScoreResult,
    score_lead,
    to_lead_score_kwargs,
)
from app.scoring.signals import LeadSignals
from app.models import CatalogItem, Conversation, Lead, LeadScore


@dataclass(frozen=True)
class ScoredLead:
    lead_id: str
    result: ScoreResult
    score_id: int
    reused: bool


def _reference_date(session: Session, explicit: datetime | None) -> datetime:
    if explicit is not None:
        return explicit.replace(tzinfo=None)
    latest = session.scalar(
        sa.select(sa.func.max(Lead.registration_at)).where(
            Lead.registration_at.is_not(None)
        )
    )
    if latest is not None:
        return latest.replace(tzinfo=None)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def prepare_lead_signals(
    session: Session,
    lead_id: str,
    *,
    reference_date: datetime | None = None,
) -> LeadSignals:
    """Arma las señales de un lead. Sin conversación → IA en None."""
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise ValueError(f"lead not found: {lead_id}")

    list_price: float | None = None
    if lead.sku:
        item = session.get(CatalogItem, lead.sku)
        if item is not None and item.list_price is not None:
            list_price = float(item.list_price)

    has_conversation = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(Conversation)
            .where(Conversation.lead_id == lead_id)
        )
        > 0
    )
    consolidated = consolidate_lead_extractions(lead_extractions(session, lead_id))

    reference = _reference_date(session, reference_date)
    registration = lead.registration_at
    trustworthy = registration is not None
    days = None
    if trustworthy:
        days = (reference - registration.replace(tzinfo=None)).days

    return LeadSignals(
        lead_id=lead_id,
        list_price=list_price,
        model_resolved=lead.sku is not None,
        presupuesto=consolidated.presupuesto,
        cuota_inicial=consolidated.cuota_inicial,
        forma_pago=consolidated.forma_pago,
        intencion_compra=consolidated.intencion_compra,
        objecion=consolidated.objecion,
        solicitud_cita=consolidated.solicitud_cita,
        solicitud_cotizacion=consolidated.solicitud_cotizacion,
        has_conversation=has_conversation,
        phone_valid=lead.phone_normalized is not None,
        email_present=lead.email_normalized is not None,
        city_present=lead.city_raw is not None,
        registration_trustworthy=trustworthy,
        estado_gestion=lead.status,
        days_since_registration=days,
        has_first_contact=lead.first_contact_at is not None,
    )


def _same_score(current: LeadScore, result: ScoreResult) -> bool:
    return (
        current.score_version == result.score_version
        and float(current.priority_score or 0) == result.commercial
        and float(current.urgency_score or 0) == result.urgency
        and float(current.queue_score or 0) == result.queue
        and (current.band or "") == result.band
        and (current.params_snapshot or {}) == result.params
    )


def score_and_persist_lead(
    session: Session,
    lead_id: str,
    *,
    reference_date: datetime | None = None,
    run_id: int | None = None,
    params: dict | None = None,
) -> ScoredLead:
    """Calcula y persiste el score de un lead. Idempotente. Hace commit."""
    signals = prepare_lead_signals(session, lead_id, reference_date=reference_date)
    result = score_lead(signals, params if params is not None else dict(SCORE_V1_PARAMS))

    current = list(
        session.scalars(
            sa.select(LeadScore)
            .where(LeadScore.lead_id == lead_id, LeadScore.is_current.is_(True))
            .order_by(LeadScore.score_id.desc())
        ).all()
    )
    for row in current:
        if _same_score(row, result):
            return ScoredLead(lead_id=lead_id, result=result, score_id=row.score_id, reused=True)

    for row in current:
        row.is_current = False
    stored = LeadScore(**to_lead_score_kwargs(result, lead_id, run_id=run_id))
    session.add(stored)
    session.flush()
    session.commit()
    return ScoredLead(lead_id=lead_id, result=result, score_id=stored.score_id, reused=False)
