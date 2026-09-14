"""Motor de scoring explicable de leads (v1).

Determinista, sin ML ni dependencias nuevas. Ver ``engine.score_lead``.
"""

from app.scoring.consolidation import ConsolidatedAI, consolidate_lead_extractions
from app.scoring.engine import (
    SCORE_V1_PARAMS,
    SCORE_VERSION,
    ScoreResult,
    score_lead,
    to_lead_score_kwargs,
)
from app.scoring.service import ScoredLead, prepare_lead_signals, score_and_persist_lead
from app.scoring.signals import LeadSignals

__all__ = [
    "ConsolidatedAI",
    "LeadSignals",
    "ScoreResult",
    "ScoredLead",
    "SCORE_VERSION",
    "SCORE_V1_PARAMS",
    "consolidate_lead_extractions",
    "score_lead",
    "prepare_lead_signals",
    "score_and_persist_lead",
    "to_lead_score_kwargs",
]
