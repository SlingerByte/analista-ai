"""Batch productivo mínimo: procesa conversaciones pendientes (secuencial).

Uso:
    uv run python -m app.ai --limit 10
    uv run python -m app.ai --conversation CONV-00001 --conversation CONV-00002
"""

from __future__ import annotations

import argparse
import json

from app.ai.factory import (
    AIProviderConfigError,
    build_extractor,
    validate_ai_configuration,
)
from app.ai.service import process_pending
from app.config import get_settings
from app.db import SessionLocal


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Process pending AI extractions")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--conversation", action="append", default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    # Misma política que el arranque web: fallar antes de procesar si la
    # configuración de IA no es válida para el entorno (p. ej. producción).
    try:
        validate_ai_configuration(settings)
    except AIProviderConfigError as exc:
        print(f"Configuración de IA inválida: {exc}")
        raise SystemExit(1)
    extractor = build_extractor(settings=settings)
    available, reason = extractor.availability()
    if not available:
        print(f"Extractor not available: {reason}")
        raise SystemExit(1)

    with SessionLocal() as session:
        report = process_pending(
            session, extractor, limit=args.limit, conversation_ids=args.conversation
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
