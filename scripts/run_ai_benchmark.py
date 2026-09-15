"""Tooling de evaluación (NO producción): corre modelos sobre el gold set.

Uso:
    uv run python scripts/run_ai_benchmark.py --model qwen2.5:3b
    uv run python scripts/run_ai_benchmark.py --model qwen2.5:7b --model llama3.2:3b

Usa el mismo prompt y schema productivos (`app.ai.prompt`, `app.ai.schema`) sin
modificarlos, y la misma validación determinista (`app.ai.validation`). Escribe
`reports/ai_gold_benchmark.json` (merge por modelo). No escribe en la BD.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.ollama import OllamaExtractor  # noqa: E402
from app.ai.schema import ConversationInput, Message  # noqa: E402
from app.ai.validation import split_transcript_messages, validate_extraction  # noqa: E402
from app.ingestion.normalizers import normalize_sender  # noqa: E402

GOLD = ROOT / "reports" / "gold_set.json"
OUTPUT = ROOT / "reports" / "ai_gold_benchmark.json"
OLLAMA_URL = "http://localhost:11434"


def _input(record: dict) -> tuple[ConversationInput, list[dict]]:
    messages = [
        Message(sender=normalize_sender(m.get("emisor")), text=str(m.get("texto") or ""),
                hour=str(m.get("hora") or "") or None)
        for m in record["transcript"]
    ]
    conversation = ConversationInput(
        conversation_id=record["conversation_id"], lead_id=record.get("lead_id"),
        channel=record.get("channel"), messages=messages,
    )
    # `split_transcript_messages` espera claves sender/text.
    normalized = [{"sender": m.sender, "text": m.text} for m in messages]
    return conversation, normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Run extraction models on gold set")
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--base-url", default=OLLAMA_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    records = gold["records"][: args.limit] if args.limit else gold["records"]

    report = {}
    if OUTPUT.exists():
        report = json.loads(OUTPUT.read_text(encoding="utf-8"))
    report.setdefault("prompt_version", "v2")
    report.setdefault("schema_version", "v1")
    report.setdefault("gold_set_size", len(gold["records"]))
    report.setdefault("providers", {})

    for model in args.model:
        extractor = OllamaExtractor(base_url=args.base_url, model=model, timeout=args.timeout)
        available, reason = extractor.availability()
        print(f"== {model}: available={available} ({reason}) ==")
        if not available:
            report["providers"][model] = {"available": False, "reason": reason, "results": []}
            continue

        results = []
        started = time.perf_counter()
        for index, record in enumerate(records, start=1):
            conversation, transcript = _input(record)
            outcome = extractor.extract(conversation)
            entry = {
                "conversation_id": record["conversation_id"],
                "success": outcome.success,
                "schema_valid": outcome.schema_valid,
                "latency_ms": outcome.latency_ms,
                "error": outcome.error,
                "raw": outcome.result.model_dump() if outcome.result else None,
                "validated": None,
            }
            if outcome.result is not None:
                client, advisor = split_transcript_messages(transcript)
                validation = validate_extraction(outcome.result, client, advisor)
                entry["validated"] = validation.extraction.model_dump()
                entry["invalidated"] = validation.invalidated
            results.append(entry)
            if index % 10 == 0:
                elapsed = time.perf_counter() - started
                print(f"  {index}/{len(records)} ({elapsed:.0f}s)")
        report["providers"][model] = {
            "available": True,
            "model": model,
            "results": results,
            "elapsed_s": round(time.perf_counter() - started, 1),
        }
        print(f"  done {model}: {len(results)} results")

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUTPUT}")


if __name__ == "__main__":
    main()
