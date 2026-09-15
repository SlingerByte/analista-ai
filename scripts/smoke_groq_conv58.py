"""Smoke test Groq (NO producción): una conversación real, sin BD ni persistencia.

Uso:
    uv run python scripts/smoke_groq_conv58.py [--conversation CONV-00058]

Lee el transcript del Gold Set (`reports/gold_set.json`), lo pasa por el
`GroqExtractor` con el prompt v2 / schema v1 actuales, aplica la validación
determinista de producción en memoria y compara contra el gold. Solo stdout;
no escribe en la base de datos ni modifica producción.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.groq import GroqExtractor  # noqa: E402
from app.ai.validation import split_transcript_messages, validate_extraction  # noqa: E402
from app.config import get_settings  # noqa: E402
from scripts.run_ai_benchmark_openrouter import _build_input  # noqa: E402

GOLD = ROOT / "reports" / "gold_set.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Groq smoke test (single conversation)")
    parser.add_argument("--conversation", default="CONV-00058")
    args = parser.parse_args()

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    record = next(
        (r for r in gold["records"] if r.get("conversation_id") == args.conversation), None
    )
    if record is None:
        raise SystemExit(f"conversation not in gold set: {args.conversation}")

    settings = get_settings()
    extractor = GroqExtractor(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        base_url=settings.groq_base_url,
        timeout=settings.ai_timeout_seconds,
    )
    available, reason = extractor.availability()
    # La razón nunca contiene la API key (ver tests/test_ai_groq.py).
    print(f"provider={extractor.provider} model={extractor.model} available={available} ({reason})")
    if not available:
        raise SystemExit("extractor no disponible")

    conversation, transcript = _build_input(record)
    outcome = extractor.extract(conversation)
    print(f"success={outcome.success} schema_valid={outcome.schema_valid} "
          f"latency_ms={outcome.latency_ms}")
    if outcome.error:
        print(f"error={outcome.error}")
    if not outcome.success or outcome.result is None:
        raise SystemExit("smoke test sin resultado del modelo")

    client, advisor = split_transcript_messages(transcript)
    validation = validate_extraction(outcome.result, client, advisor)
    final = validation.extraction.model_dump()

    print(f"{'field':<22}{'gold':<22}{'groq_validated':<22}")
    for field in ("model_interes", "intencion_compra", "presupuesto", "cuota_inicial",
                  "forma_pago", "objecion", "solicitud_cita", "solicitud_cotizacion"):
        print(f"{field:<22}{str(record.get(f'gold_{field}')):<22}{str(final.get(field)):<22}")
    if validation.invalidated:
        print(f"invalidated={validation.invalidated}")


if __name__ == "__main__":
    main()
