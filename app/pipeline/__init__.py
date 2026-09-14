"""Orquestación end-to-end (trigger único, sin orquestador externo).

Reutiliza las etapas existentes en orden; no reimplementa lógica.
Ver ``service.run_pipeline`` y ``uv run python -m app.pipeline --help``.
"""

from app.pipeline.service import STAGES, run_pipeline

__all__ = ["STAGES", "run_pipeline"]
