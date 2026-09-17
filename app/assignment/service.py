"""Asignación determinista por empresa y punto de venta (estrategia v1).

Dos capas separadas:

- :func:`plan_assignments`: función pura. Recibe candidatos y capacidades y
  produce decisiones. Testeable sin base de datos.
- :func:`run_assignment`: consulta Lead/LeadScore/Identity/Advisor, invoca la
  lógica pura, versiona las filas vigentes del mismo ``run_date`` y persiste.
- :func:`retry_assignment`: reintenta con el mismo algoritmo pero solo escribe
  si el plan cambió (idempotente), opcionalmente acotado por empresa.

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

from app.integrity import (
    advisor_organizations,
    check_assignment_organization,
    point_of_sale_owners,
)
from app.lead_status import is_lead_terminal
from app.models import Advisor, Assignment, IdentityCluster, IdentityMember, Lead, LeadScore

STRATEGY_VERSION = "v1"
STATUS_ASSIGNED = "assigned"
STATUS_OVERFLOW = "overflow"
OVERFLOW_REASON = "sin_capacidad"
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
    occupied_by_advisor: dict[str, int] | None = None,
    existing_advisor: dict[str, str] | None = None,
) -> list[AssignmentDecision]:
    """Decisiones de asignación. Pura y determinista.

    ``occupied_by_advisor``: leads abiertos que ya ocupan cupo del asesor
    (asignación operativa vigente). ``existing_advisor``: asesor vigente por
    lead abierto, para conservar continuidad (no reasignar por capacidad).
    """
    _ = strategy_version
    occupied = dict(occupied_by_advisor or {})
    existing = dict(existing_advisor or {})
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
        pool_ids = {advisor.advisor_id for advisor in pool}
        # Capacidad disponible = cupo diario − leads abiertos que ya ocupan.
        remaining = {
            advisor.advisor_id: max(
                0, advisor.daily_capacity - occupied.get(advisor.advisor_id, 0)
            )
            for advisor in pool
        }
        for rank, candidate in enumerate(group, start=1):
            keep = existing.get(candidate.lead_id)
            if keep in pool_ids:
                # Continuidad: un lead abierto conserva a su asesor vigente.
                decisions.append(
                    AssignmentDecision(
                        lead_id=candidate.lead_id,
                        company_id=company_id,
                        point_of_sale_id=point_of_sale_id,
                        advisor_id=keep,
                        priority_rank=rank,
                        status=STATUS_ASSIGNED,
                        reason="continuidad: conserva el asesor vigente",
                    )
                )
                continue
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


def _eligible_candidates(
    session: Session, company_ids: set[str] | None = None
) -> list[LeadCandidate]:
    """Leads gestionables con score vigente: sin estados terminales ni
    miembros no canónicos de identidad."""
    scores = session.scalars(
        sa.select(LeadScore).where(LeadScore.is_current.is_(True))
    ).all()
    latest: dict[str, LeadScore] = {}
    for score in scores:
        current = latest.get(score.lead_id)
        if current is None or score.score_id > current.score_id:
            latest[score.lead_id] = score
    if not latest:
        return []

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

    statement = sa.select(Lead).where(Lead.lead_id.in_(latest))
    if company_ids:
        statement = statement.where(Lead.company_id.in_(company_ids))
    leads = session.scalars(statement).all()
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
        if lead.lead_id not in non_canonical and not is_lead_terminal(lead.status)
    ]


def _advisor_capacities(
    session: Session, company_ids: set[str] | None = None
) -> list[AdvisorCapacity]:
    statement = sa.select(Advisor)
    if company_ids:
        statement = statement.where(Advisor.company_id.in_(company_ids))
    return [
        AdvisorCapacity(
            advisor_id=row.advisor_id,
            company_id=row.company_id,
            point_of_sale_id=row.point_of_sale_id,
            daily_capacity=row.daily_capacity,
            active=row.active,
        )
        for row in session.scalars(statement).all()
    ]


def _operative_assignments(
    session: Session, company_ids: set[str] | None = None
) -> dict[str, Assignment]:
    """Asignación operativa vigente por lead: la última ``is_current``.

    Convención del proyecto: la vigente es ``is_current=True``; si coexisten
    varias fechas, la más reciente (``run_date`` y luego ``assignment_id``).
    """
    statement = sa.select(Assignment).where(Assignment.is_current.is_(True))
    if company_ids:
        statement = statement.where(Assignment.company_id.in_(company_ids))
    latest: dict[str, Assignment] = {}
    for row in session.scalars(
        statement.order_by(Assignment.run_date.asc(), Assignment.assignment_id.asc())
    ).all():
        latest[row.lead_id] = row
    return latest


def _open_load_by_advisor(
    session: Session, operative: dict[str, Assignment]
) -> dict[str, int]:
    """Cupo ocupado por asesor = leads ABIERTOS con asignación operativa vigente.

    Los leads terminales (Cerrado/Perdido/Descartado) no ocupan capacidad.
    """
    lead_ids = [
        lead_id
        for lead_id, row in operative.items()
        if row.status == STATUS_ASSIGNED and row.advisor_id is not None
    ]
    statuses: dict[str, str | None] = {}
    if lead_ids:
        statuses = {
            lead_id: status
            for lead_id, status in session.execute(
                sa.select(Lead.lead_id, Lead.status).where(Lead.lead_id.in_(lead_ids))
            ).all()
        }
    load: dict[str, int] = {}
    for lead_id, row in operative.items():
        if row.status != STATUS_ASSIGNED or row.advisor_id is None:
            continue
        if is_lead_terminal(statuses.get(lead_id)):
            continue
        load[row.advisor_id] = load.get(row.advisor_id, 0) + 1
    return load


def advisor_open_load(session: Session, advisor_id: str) -> int:
    """Leads abiertos con asignación vigente del asesor (ocupa capacidad)."""
    return _open_load_by_advisor(session, _operative_assignments(session)).get(advisor_id, 0)


def advisor_available_capacity(session: Session, advisor: Advisor) -> int:
    """Cupo disponible = daily_capacity − leads abiertos asignados vigentes."""
    return max(0, advisor.daily_capacity - advisor_open_load(session, advisor.advisor_id))


def _assert_decisions_organization(
    session: Session, decisions: list[AssignmentDecision]
) -> None:
    """Defensa de escritura: ninguna decisión cruza empresa/POS/asesor."""
    pos_owner = point_of_sale_owners(session)
    advisor_org = advisor_organizations(session)
    for decision in decisions:
        check_assignment_organization(
            pos_owner,
            advisor_org,
            company_id=decision.company_id,
            point_of_sale_id=decision.point_of_sale_id,
            advisor_id=decision.advisor_id,
        )


def _decision_signature(decision: AssignmentDecision) -> tuple:
    return (
        decision.lead_id,
        decision.advisor_id,
        decision.status,
        decision.priority_rank,
    )


def _current_signatures(
    session: Session, run_date: date, company_ids: set[str] | None
) -> list[tuple]:
    statement = sa.select(Assignment).where(
        Assignment.run_date == run_date,
        Assignment.is_current.is_(True),
    )
    if company_ids:
        statement = statement.where(Assignment.company_id.in_(company_ids))
    return sorted(
        (row.lead_id, row.advisor_id, row.status, row.priority_rank)
        for row in session.scalars(statement).all()
    )


def _persist_decisions(
    session: Session,
    run_date: date,
    decisions: list[AssignmentDecision],
    strategy_version: str,
    company_ids: set[str] | None,
) -> None:
    statement = sa.update(Assignment).where(
        Assignment.run_date == run_date, Assignment.is_current.is_(True)
    )
    if company_ids:
        statement = statement.where(Assignment.company_id.in_(company_ids))
    session.execute(statement.values(is_current=False))

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


def _summary(
    decisions: list[AssignmentDecision], run_date: date, strategy_version: str
) -> dict:
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


def run_assignment(
    session: Session,
    run_date: date,
    *,
    strategy_version: str = STRATEGY_VERSION,
    company_ids: set[str] | None = None,
) -> dict:
    """Ejecuta la foto diaria: versiona el día, persiste decisiones, commit."""
    scope = set(company_ids) if company_ids else None
    candidates = _eligible_candidates(session, company_ids=scope)
    advisors = _advisor_capacities(session, company_ids=scope)
    operative = _operative_assignments(session, company_ids=scope)
    occupied = _open_load_by_advisor(session, operative)
    existing = {
        lead_id: row.advisor_id
        for lead_id, row in operative.items()
        if row.status == STATUS_ASSIGNED and row.advisor_id is not None
    }
    decisions = plan_assignments(
        candidates,
        advisors,
        strategy_version=strategy_version,
        occupied_by_advisor=occupied,
        existing_advisor=existing,
    )
    _assert_decisions_organization(session, decisions)
    _persist_decisions(session, run_date, decisions, strategy_version, scope)
    return _summary(decisions, run_date, strategy_version)


def retry_assignment(
    session: Session,
    run_date: date,
    *,
    strategy_version: str = STRATEGY_VERSION,
    company_ids: set[str] | None = None,
) -> dict:
    """Reintenta la asignación con el mismo algoritmo. Idempotente.

    Recalcula las decisiones con el score/empresa/POS/capacidad/asesores
    vigentes y solo escribe si el plan cambió respecto del vigente del día.
    """
    scope = set(company_ids) if company_ids else None
    candidates = _eligible_candidates(session, company_ids=scope)
    advisors = _advisor_capacities(session, company_ids=scope)
    operative = _operative_assignments(session, company_ids=scope)
    occupied = _open_load_by_advisor(session, operative)
    existing = {
        lead_id: row.advisor_id
        for lead_id, row in operative.items()
        if row.status == STATUS_ASSIGNED and row.advisor_id is not None
    }
    decisions = plan_assignments(
        candidates,
        advisors,
        strategy_version=strategy_version,
        occupied_by_advisor=occupied,
        existing_advisor=existing,
    )
    _assert_decisions_organization(session, decisions)

    current_signature = _current_signatures(session, run_date, scope)
    new_signature = sorted(_decision_signature(d) for d in decisions)
    if current_signature == new_signature:
        summary = _summary(decisions, run_date, strategy_version)
        summary["reused"] = True
        return summary

    _persist_decisions(session, run_date, decisions, strategy_version, scope)
    summary = _summary(decisions, run_date, strategy_version)
    summary["reused"] = False
    return summary
