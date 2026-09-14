from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ingestion import loaders
from app.ingestion.conversations import ingest_conversations
from app.ingestion.leads import ingest_leads
from app.models import PipelineRun


def run_ingestion(
    session: Session,
    data_dir: Path = loaders.DATA_DIR,
    trigger: str = "ingestion",
) -> dict:
    leads_path = data_dir / loaders.LEADS_FILE
    conversations_path = data_dir / loaders.CONVERSATIONS_FILE

    source_hashes = {
        loaders.LEADS_FILE: loaders.sha256_file(leads_path),
        loaders.CONVERSATIONS_FILE: loaders.sha256_file(conversations_path),
    }

    run = PipelineRun(trigger=trigger, status="running", source_hashes=source_hashes)
    session.add(run)
    session.flush()

    failure: Exception | None = None
    steps: dict | None = None

    try:
        with session.begin_nested():
            leads_report = ingest_leads(session, run.run_id, data_dir)
            conversations_report = ingest_conversations(session, run.run_id, data_dir)
        steps = {"leads": leads_report, "conversations": conversations_report}
    except Exception as exc:  # noqa: BLE001
        failure = exc

    run.finished_at = datetime.now(timezone.utc)
    if failure is None:
        run.status = "completed"
        run.steps = steps
    else:
        run.status = "failed"
        run.error = f"{type(failure).__name__}: {failure}"
    session.commit()

    if failure is not None:
        raise failure

    return {
        "run_id": run.run_id,
        "trigger": run.trigger,
        "status": run.status,
        "source_hashes": source_hashes,
        "steps": steps,
    }
