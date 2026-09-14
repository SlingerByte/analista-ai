"""Asignación determinista por empresa y punto de venta (estrategia v1).

Dos capas separadas:

- :func:`plan_assignments`: función pura. Recibe candidatos y capacidades y
  produce decisiones. Testeable sin base de datos.
- :func:`run_assignment`: consulta Lead/LeadScore/Identity/Advisor, invoca la
  lógica pura, versiona las filas vigentes del mismo ``run_date`` y persiste.

Reglas v1:

- Grupos estrictos ``(company_id, point_of_sale_id)``. Nunca se mezclan
  empresas ni se mueve un lead de POS para llenar capacidad.
- Orden por ``queue_score DESC, lead_id ASC`` (determinista, sin azar).
- Solo asesores ``active=True`` del mismo grupo; reparto greedy por capacidad
  restante con desempate ``advisor_id ASC``.
- Sin capacidad: fila ``overflow`` con ``advisor_id=NULL``.
- Defensa de dominio: cada decisión asignada verifica
  ``lead.company_id == advisor.company_id`` y mismo POS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Advisor, Assignment, IdentityCluster, IdentityMember, Lead, LeadScore

STRATEGY_VERSION = "v1"
STATUS_ASSIGNED = "assigned"
STATUS_OVERFLOW = "overflow"
OVERFLOW_REASON = "sin_capacidad"
DISCARDED_STATUS = "Descartado"
REVIEWED_DISCARDED = "reviewed_discarded"


@dataclass(frozen=True)
class LeadCandidate:
    lead_id: str
    company_id: str
    point_of_sale_id: str
    queue: float


@dataclass(frozen=True)
class AdvisorCapacity:
    advisor_id: str
    company_id: str
    point_of_sale_id: str
    daily_capacity: int
    active: bool = True


@dataclass(frozen=True)
class AssignmentDecision:
    lead_id: str
    company_id: str
    point_of_sale_id: str
    advisor_id: str | None
    priority_rank: int
    status: str
    reason: str


def _pick_advisor(
    pool: list[AdvisorCapacity], remaining: dict[str, int]
) -> AdvisorCapacity | None:
    eligible = [advisor for advisor in pool if remaining[advisor.advisor_id] > 0]
    if not eligible:
        return None
    return min(eligible, key=lambda a: (-remaining[a.advisor_id], a.advisor_id))


def plan_assignments(
    candidates: list[LeadCandidate],
    advisors: list[AdvisorCapacity],
    *,
    strategy_version: str = STRATEGY_VERSION,
) -> list[AssignmentDecision]:
    """Decisiones de asignación. Pura y determinista."""
    _ = strategy_version
    by_group: dict[tuple[str, str], list[LeadCandidate]] = {}
    for candidate in candidates:
        by_group.setdefault((candidate.company_id, candidate.point_of_sale_id), []).append(
            candidate
        )

    decisions: list[AssignmentDecision] = []
    for company_id, point_of_sale_id in sorted(by_group):
        group = sorted(by_group[(company_id, point_of_sale_id)],
                       key=lambda c: (-c.queue, c.lead_id))
        # Defensa de dominio: el pool solo admite asesores activos del grupo.
        pool = sorted(
            (
                advisor
                for advisor in advisors
                if advisor.active
                and advisor.company_id == company_id
                and advisor.point_of_sale_id == point_of_sale_id
                and advisor.daily_capacity > 0
            ),
            key=lambda a: a.advisor_id,
        )
        remaining = {advisor.advisor_id: advisor.daily_capacity for advisor in pool}
        for rank, candidate in enumerate(group, start=1):
            chosen = _pick_advisor(pool, remaining)
            if chosen is None:
                decisions.append(
                    AssignmentDecision(
                        lead_id=candidate.lead_id,
                        company_id=company_id,
                        point_of_sale_id=point_of_sale_id,
                        advisor_id=None,
                        priority_rank=rank,
                        status=STATUS_OVERFLOW,
                        reason=OVERFLOW_REASON,
                    )
                )
            else:
                remaining[chosen.advisor_id] -= 1
                decisions.append(
                    AssignmentDecision(
                        lead_id=candidate.lead_id,
                        company_id=company_id,
                        point_of_sale_id=point_of_sale_id,
                        advisor_id=chosen.advisor_id,
                        priority_rank=rank,
                        status=STATUS_ASSIGNED,
                        reason=(
                            f"rank {rank} por prioridad en {company_id}/{point_of_sale_id}; "
                            f"asesor con mayor capacidad restante"
                        ),
                    )
                )

    # Validación final: ningún asesor recibe leads de otra empresa o POS.
    valid_advisors = {
        (a.advisor_id, a.company_id, a.point_of_sale_id) for a in advisors if a.active
    }
    for decision in decisions:
        if decision.status == STATUS_ASSIGNED and (
            decision.advisor_id,
            decision.company_id,
            decision.point_of_sale_id,
        ) not in valid_advisors:
            raise ValueError(f"asignación inválida entre grupos: {decision}")
    return decisions


def _eligible_candidates(session: Session) -> list[LeadCandidate]:
    """Leads gestionables con score vigente, sin Descartado ni miembros no canónicos."""
    scores = session.scalars(
        sa.select(LeadScore).where(LeadScore.is_current.is_(True))
    ).all()
    latest: dict[str, LeadScore] = {}
    for score in scores:
        current = latest.get(score.lead_id)
        if current is None or score.score_id > current.score_id:
            latest[score.lead_id] = score

    non_canonical = set(
        session.scalars(
            sa.select(IdentityMember.lead_id)
            .join(IdentityCluster, IdentityCluster.cluster_id == IdentityMember.cluster_id)
            .where(
                IdentityMember.role != "canonical",
                IdentityCluster.status != REVIEWED_DISCARDED,
            )
        ).all()
    )

    leads = session.scalars(
        sa.select(Lead).where(
            Lead.lead_id.in_(latest),
            Lead.status != DISCARDED_STATUS,
        )
    ).all()
    return [
        LeadCandidate(
            lead_id=lead.lead_id,
            company_id=lead.company_id,
            point_of_sale_id=lead.point_of_sale_id,
            queue=float(latest[lead.lead_id].queue_score)
            if latest[lead.lead_id].queue_score is not None
            else float("-inf"),
        )
        for lead in leads
        if lead.lead_id not in non_canonical
    ]


def run_assignment(
    session: Session,
    run_date: date,
    *,
    strategy_version: str = STRATEGY_VERSION,
) -> dict:
    """Ejecuta la foto diaria: versiona el día, persiste decisiones, commit."""
    candidates = _eligible_candidates(session)
    advisors = [
        AdvisorCapacity(
            advisor_id=row.advisor_id,
            company_id=row.company_id,
            point_of_sale_id=row.point_of_sale_id,
            daily_capacity=row.daily_capacity,
            active=row.active,
        )
        for row in session.scalars(sa.select(Advisor)).all()
    ]
    decisions = plan_assignments(
        candidates, advisors, strategy_version=strategy_version
    )

    session.execute(
        sa.update(Assignment)
        .where(Assignment.run_date == run_date, Assignment.is_current.is_(True))
        .values(is_current=False)
    )
    for decision in decisions:
        session.add(
            Assignment(
                lead_id=decision.lead_id,
                advisor_id=decision.advisor_id,
                company_id=decision.company_id,
                point_of_sale_id=decision.point_of_sale_id,
                run_id=None,
                run_date=run_date,
                strategy_version=strategy_version,
                priority_rank=decision.priority_rank,
                status=decision.status,
                reason=decision.reason,
                is_current=True,
            )
        )
    session.commit()

    assigned = sum(1 for d in decisions if d.status == STATUS_ASSIGNED)
    per_advisor: dict[str, int] = {}
    for decision in decisions:
        if decision.advisor_id is not None:
            per_advisor[decision.advisor_id] = per_advisor.get(decision.advisor_id, 0) + 1
    return {
        "run_date": run_date.isoformat(),
        "strategy_version": strategy_version,
        "groups": len({(d.company_id, d.point_of_sale_id) for d in decisions}),
        "candidates": len(decisions),
        "assigned": assigned,
        "overflow": len(decisions) - assigned,
        "per_advisor": per_advisor,
    }
