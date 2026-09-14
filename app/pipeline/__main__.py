"""Trigger CLI del pipeline completo.

Uso:
    uv run python -m app.pipeline --run-date 2026-09-14 --ai-limit 10
    uv run python -m app.pipeline --no-ai
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app.ingestion import loaders
from app.pipeline.service import run_pipeline


def main(argv: list[str] | None = None, *, run_ai: bool | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the end-to-end lead pipeline")
    parser.add_argument("--run-date", type=date.fromisoformat, default=None)
    parser.add_argument("--ai-limit", type=int, default=None)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=loaders.DATA_DIR)
    args = parser.parse_args(argv)

    from app.db import SessionLocal

    resolved_ai = not args.no_ai if run_ai is None else run_ai
    with SessionLocal() as session:
        report = run_pipeline(
            session,
            run_date=args.run_date,
            data_dir=args.data_dir,
            run_ai=resolved_ai,
            ai_limit=args.ai_limit,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "completed":
        raise SystemExit(1)


def main_no_ai(argv: list[str] | None = None) -> None:
    """Entry point `uv run pipeline`: pipeline normal sin IA."""
    main(argv, run_ai=False)


if __name__ == "__main__":
    main()
