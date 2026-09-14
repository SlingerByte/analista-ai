from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.identity.service import run_identity
from app.ingestion import loaders
from app.ingestion.service import run_ingestion


def run_pipeline(session: Session, data_dir: Path = loaders.DATA_DIR) -> dict:
    ingestion = run_ingestion(session, data_dir)
    identity = run_identity(session)
    return {"ingestion": ingestion, "identity": identity}


def main() -> None:
    with SessionLocal() as session:
        result = run_pipeline(session)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
