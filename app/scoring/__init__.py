"""Motor de scoring explicable de leads (v1).

Determinista, sin ML ni dependencias nuevas. Ver ``engine.score_lead``.
"""

from app.scoring.engine import (
    SCORE_V1_PARAMS,
    SCORE_VERSION,
    ScoreResult,
    score_lead,
    to_lead_score_kwargs,
)
from app.scoring.signals import LeadSignals

__all__ = [
    "LeadSignals",
    "ScoreResult",
    "SCORE_VERSION",
    "SCORE_V1_PARAMS",
    "score_lead",
    "to_lead_score_kwargs",
]
