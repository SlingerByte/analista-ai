"""Trigger único del flujo completo (orquestación simple, sin workers).

Orden fijo::

    reference → ingestion → identity → ai → scoring → assignment

``reference`` carga los datos maestros idempotentes (empresas, POS, asesores,
catálogo) que la ingesta necesita para validar. Cada etapa es una función
ordena, registra y propaga. Trazabilidad en una fila ``pipeline_runs`` con
``trigger="pipeline"``: inicio/fin, estado, resumen por etapa y, si algo
falla, qué etapa falló y con qué error (las etapas previas quedan
confirmadas; al re-ejecutar, cada etapa idempotente no repite trabajo).

Sin duplicados: scoring y assignment ya son idempotentes (reutilizan o
versionan); IA reusa por ``(conversation_id, input_hash)``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.factory import (
    AIProviderConfigError,
    build_extractor,
    validate_ai_configuration,
)
from app.ai.service import process_pending
from app.assignment.service import run_assignment
from app.config import get_settings
from app.identity.service import run_identity
from app.ingestion import loaders
from app.ingestion.service import run_ingestion
from app.models import Lead, PipelineRun
from app.scoring.service import score_and_persist_lead
from app.seed import seed

STAGES = ("reference", "ingestion", "identity", "ai", "scoring", "assignment")

# Listas de detalle recortadas en el resumen por etapa (los conteos quedan
# intactos). Evita que pipeline_runs.steps y el reporte CLI crezcan sin control
# (p. ej. la lista completa de huérfanas).
MAX_LIST_ITEMS = 25


def _trim(value):
    if isinstance(value, dict):
        return {key: _trim(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trim(item) for item in value[:MAX_LIST_ITEMS]]
    return value


def _jsonable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _run_scoring(session: Session, run_id: int) -> dict:
    scored = reused = 0
    lead_ids = list(session.scalars(sa.select(Lead.lead_id).order_by(Lead.lead_id)).all())
    for lead_id in lead_ids:
        result = score_and_persist_lead(session, lead_id, run_id=run_id)
        scored += 1
        if result.reused:
            reused += 1
    return {"leads": scored, "reused": reused, "created": scored - reused}


def run_pipeline(
    session: Session,
    *,
    run_date: date | None = None,
    data_dir: Path = loaders.DATA_DIR,
    run_ai: bool = True,
    ai_limit: int | None = None,
    trigger: str = "pipeline",
) -> dict:
    """Ejecuta el flujo completo. Siempre deja trazabilidad; no levanta."""
    resolved_date = run_date or date.today()
    run = PipelineRun(trigger=trigger, status="running", source_hashes={})
    session.add(run)
    session.flush()

    steps: dict = {}
    failure: tuple[str, Exception] | None = None

    def _record(stage: str, summary: dict) -> None:
        steps[stage] = {"status": "completed", **_jsonable(_trim(summary))}

    try:
        _record("reference", seed(session, data_dir))
        ingestion = run_ingestion(session, data_dir)
        run.source_hashes = ingestion.get("source_hashes")
        _record("ingestion", ingestion)

        identity = run_identity(session)
        _record("identity", identity)

        if run_ai:
            # Misma política que el arranque web: en producción no se admite
            # usar silenciosamente el Ollama local como proveedor.
            try:
                validate_ai_configuration(get_settings())
            except AIProviderConfigError as exc:
                raise RuntimeError(f"Configuración de IA inválida: {exc}") from exc
            extractor = build_extractor()
            available, reason = extractor.availability()
            if not available:
                steps["ai"] = {"status": "skipped", "reason": reason}
            else:
                _record("ai", process_pending(session, extractor, limit=ai_limit))
        else:
            steps["ai"] = {"status": "skipped", "reason": "run_ai=False"}

        _record("scoring", _run_scoring(session, run.run_id))
        _record("assignment", run_assignment(session, resolved_date))
    except Exception as exc:  # noqa: BLE001 - registrar etapa fallida y retornar
        for stage in STAGES:
            if stage not in steps:
                failure = (stage, exc)
                steps[stage] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                break

    run.finished_at = datetime.now(timezone.utc)
    run.steps = _jsonable(steps)
    if failure is None:
        run.status = "completed"
    else:
        run.status = "failed"
        run.error = f"{failure[0]}: {failure[1]}"
    session.commit()

    return {
        "run_id": run.run_id,
        "run_date": resolved_date.isoformat(),
        "trigger": run.trigger,
        "status": run.status,
        "stages": list(STAGES),
        "steps": steps,
    }
