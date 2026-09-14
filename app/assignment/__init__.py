"""Asignación determinista de leads a asesores (estrategia v1).

Sin ML, sin endpoints, sin dependencias nuevas. Ver ``service.plan_assignments``.
"""

from app.assignment.service import (
    STRATEGY_VERSION,
    AdvisorCapacity,
    AssignmentDecision,
    LeadCandidate,
    plan_assignments,
    run_assignment,
)

__all__ = [
    "STRATEGY_VERSION",
    "AdvisorCapacity",
    "AssignmentDecision",
    "LeadCandidate",
    "plan_assignments",
    "run_assignment",
]
