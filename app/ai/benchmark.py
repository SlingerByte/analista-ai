from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.ai.base import AIExtractor, ExtractionOutcome
from app.ai.factory import UnknownProviderError, build_extractor
from app.ai.prompt import EXTRACTION_PROMPT_VERSION
from app.ai.schema import SCHEMA_VERSION, ConversationInput, Message
from app.config import get_settings
from app.ingestion import loaders
from app.ingestion.normalizers import (
    normalize_canal,
    normalize_key,
    normalize_messages,
    normalize_model_text,
    pick,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
BENCHMARK_SIZE = 10

BRAND_MARKERS = [
    "honda",
    "bajaj",
    "suzuki",
    "akt",
    "hero",
    "pulsar",
    "boxer",
    "xpulse",
    "cb 125",
    "gn 125",
    "dio",
    "navi",
    "dominar",
    "gixxer",
    "v-strom",
    "hunk",
    "dynamic",
    "ttr",
    "nkd",
    "discover",
    "eco",
    "dash",
    "xre",
]
CITA_MARKERS = ["cita", "agendar", "agenda", "visitar", "sucursal", "punto de venta", "pasar a", "ir a la"]
OBJECION_MARKERS = [
    "caro",
    "costoso",
    "otra marca",
    "no me alcanza",
    "pensarlo",
    "pensar",
    "descuento",
    "mejor precio",
    "fuera de presupuesto",
]
AMBIGUA_MARKERS = ["solo estaba mirando", "solo mirando", "estoy mirando", "aun no", "nose", "no se", "mirando opciones"]
MONEY_RE = re.compile(r"\$\s*\d|\b\d[\d.,]*\s*(millones|millon|palos)\b|\b\d{7,}\b")


def _load_catalog_lines(data_dir: Path) -> list[str]:
    rows = loaders.read_csv(data_dir / "catalogo_motos.csv")
    lines = set()
    for row in rows:
        for candidate in (f"{row['marca']} {row['linea']}", row["linea"]):
            normalized = normalize_model_text(candidate)
            if normalized:
                lines.add(normalized)
    return sorted(lines)


def load_conversations(data_dir: Path = loaders.DATA_DIR) -> list[dict]:
    raw = loaders.read_json(data_dir / loaders.CONVERSATIONS_FILE)
    conversations = []
    for item in raw:
        conversation_id = pick(item, ["conversacion_id", "conversation_id", "id"])
        if not conversation_id:
            continue
        conversations.append(
            {
                "conversation_id": str(conversation_id),
                "lead_id": pick(item, ["lead_id", "lead"]),
                "channel": normalize_canal(pick(item, ["canal", "channel"])),
                "messages": normalize_messages(pick(item, ["mensajes", "messages"])),
            }
        )
    return conversations


def _all_key(conversation: dict) -> str:
    return normalize_key(" ".join(message["text"] for message in conversation["messages"]))


def _customer_key(conversation: dict) -> str:
    return normalize_key(
        " ".join(
            message["text"]
            for message in conversation["messages"]
            if message["sender"] == "cliente"
        )
    )


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _to_case(label: str, conversation: dict) -> dict:
    conversation_input = ConversationInput(
        conversation_id=conversation["conversation_id"],
        lead_id=conversation["lead_id"],
        channel=conversation["channel"],
        messages=[Message(**message) for message in conversation["messages"]],
    )
    return {
        "case": label,
        "conversation_id": conversation["conversation_id"],
        "lead_id": conversation["lead_id"],
        "message_count": len(conversation["messages"]),
        "conversation": conversation_input,
    }


def select_cases(
    conversations: list[dict], data_dir: Path = loaders.DATA_DIR, limit: int = BENCHMARK_SIZE
) -> list[dict]:
    catalog_lines = _load_catalog_lines(data_dir)
    prepared = [
        (conversation, _all_key(conversation), _customer_key(conversation), len(conversation["messages"]))
        for conversation in conversations
    ]
    min_count = min((count for *_, count in prepared), default=0)

    picked: set[str] = set()
    cases: list[dict] = []

    def take(label: str, predicate) -> bool:
        for conversation, all_key, customer_key, count in prepared:
            if conversation["conversation_id"] in picked:
                continue
            if predicate(conversation, all_key, customer_key, count):
                picked.add(conversation["conversation_id"])
                cases.append(_to_case(label, conversation))
                return True
        return False

    predicates = [
        ("modelo_claro", lambda c, a, cu, n: any(line in a for line in catalog_lines)),
        ("modelo_variacion", lambda c, a, cu, n: _contains_any(cu, BRAND_MARKERS)),
        ("presupuesto", lambda c, a, cu, n: MONEY_RE.search(cu) is not None),
        ("cuota", lambda c, a, cu, n: "cuota" in cu),
        ("financiacion", lambda c, a, cu, n: "financ" in cu or "credito" in cu),
        ("solicitud_cita", lambda c, a, cu, n: _contains_any(cu, CITA_MARKERS)),
        ("cotizacion_contexto", lambda c, a, cu, n: "cotiz" in a),
        ("objecion", lambda c, a, cu, n: _contains_any(cu, OBJECION_MARKERS)),
        ("ambigua", lambda c, a, cu, n: n <= 7 and _contains_any(cu, AMBIGUA_MARKERS)),
        ("poca_evidencia", lambda c, a, cu, n: n == min_count),
    ]
    for label, predicate in predicates:
        if len(cases) >= limit:
            break
        take(label, predicate)

    if len(cases) < limit:
        leftovers = [c for c in conversations if c["conversation_id"] not in picked]
        leftovers.sort(key=lambda c: (len(c["messages"]), c["conversation_id"]))
        for conversation in leftovers:
            if len(cases) >= limit:
                break
            picked.add(conversation["conversation_id"])
            cases.append(_to_case("adicional", conversation))

    return cases


def _outcome_to_dict(case: dict, outcome: ExtractionOutcome) -> dict:
    result = outcome.result
    return {
        "case": case["case"],
        "conversation_id": outcome.conversation_id,
        "success": outcome.success,
        "schema_valid": outcome.schema_valid,
        "latency_ms": outcome.latency_ms,
        "error": outcome.error,
        "raw_text": outcome.raw_text,
        "fields_extracted": result.fields_extracted() if result else 0,
        "fields_with_evidence": result.fields_with_evidence() if result else 0,
        "extraction": result.model_dump() if result else None,
    }


def _metrics(results: list[dict]) -> dict:
    total = len(results)
    success = sum(1 for item in results if item["success"])
    schema_valid = sum(1 for item in results if item["schema_valid"])
    latencies = [item["latency_ms"] for item in results if item["success"]]
    fields_extracted = sum(item["fields_extracted"] for item in results)
    fields_with_evidence = sum(item["fields_with_evidence"] for item in results)
    errors = [item["error"] for item in results if item["error"]]
    return {
        "requests": total,
        "request_success_rate": round(success / total, 4) if total else None,
        "schema_valid_rate": round(schema_valid / total, 4) if total else None,
        "average_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "fields_extracted": fields_extracted,
        "fields_with_evidence": fields_with_evidence,
        "evidence_rate": round(fields_with_evidence / fields_extracted, 4)
        if fields_extracted
        else None,
        "errors": errors,
    }


def run_benchmark(extractors: list[AIExtractor], cases: list[dict]) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "cases": [
            {
                "case": case["case"],
                "conversation_id": case["conversation_id"],
                "lead_id": case["lead_id"],
                "message_count": case["message_count"],
            }
            for case in cases
        ],
        "providers": {},
    }

    for extractor in extractors:
        available, reason = extractor.availability()
        entry = {
            "provider": extractor.provider,
            "model": extractor.model,
            "available": available,
            "availability_reason": reason,
            "results": [],
            "metrics": _metrics([]),
        }
        if available:
            for case in cases:
                outcome = extractor.extract(case["conversation"])
                entry["results"].append(_outcome_to_dict(case, outcome))
            entry["metrics"] = _metrics(entry["results"])
        report["providers"][extractor.provider] = entry

    return report


def _render_markdown(report: dict) -> str:
    lines = ["# AI extraction benchmark (AI-0)", ""]
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- schema_version: {report['schema_version']}")
    lines.append(f"- prompt_version: {report['prompt_version']}")
    lines.append(f"- cases: {len(report['cases'])}")
    lines.append("")

    lines.append("## Benchmark cases")
    lines.append("")
    lines.append("| case | conversation_id | lead_id | messages |")
    lines.append("|---|---|---|---|")
    for case in report["cases"]:
        lines.append(
            f"| {case['case']} | {case['conversation_id']} | {case['lead_id']} | {case['message_count']} |"
        )
    lines.append("")

    for provider, entry in report["providers"].items():
        lines.append(f"## Provider: {provider}")
        lines.append("")
        lines.append(f"- model: {entry['model']}")
        lines.append(f"- available: {entry['available']} ({entry['availability_reason']})")
        metrics = entry["metrics"]
        if entry["available"]:
            lines.append(
                f"- request_success_rate: {metrics['request_success_rate']} · "
                f"schema_valid_rate: {metrics['schema_valid_rate']}"
            )
            lines.append(
                f"- latency: avg {metrics['average_latency_ms']} ms · median {metrics['median_latency_ms']} ms"
            )
            lines.append(
                f"- fields_extracted: {metrics['fields_extracted']} · "
                f"fields_with_evidence: {metrics['fields_with_evidence']} · "
                f"evidence_rate: {metrics['evidence_rate']}"
            )
            if metrics["errors"]:
                lines.append(f"- errors: {metrics['errors']}")
        lines.append("")

        if entry["available"]:
            lines.append("### Manual review")
            lines.append("")
            lines.append(
                "| case | ok | schema | model_interes | presupuesto | cuota_inicial | forma_pago | intencion | objecion | cita | cotizacion | ev |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for result in entry["results"]:
                data = result["extraction"] or {}
                lines.append(
                    "| {case} | {ok} | {schema} | {mi} | {pre} | {cuo} | {fp} | {it} | {ob} | {ci} | {co} | {ev} |".format(
                        case=result["case"],
                        ok=result["success"],
                        schema=result["schema_valid"],
                        mi=data.get("model_interes"),
                        pre=data.get("presupuesto"),
                        cuo=data.get("cuota_inicial"),
                        fp=data.get("forma_pago"),
                        it=data.get("intencion_compra"),
                        ob=data.get("objecion"),
                        ci=data.get("solicitud_cita"),
                        co=data.get("solicitud_cotizacion"),
                        ev=result["fields_with_evidence"],
                    )
                )
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_reports(report: dict, reports_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "ai_benchmark.json"
    md_path = reports_dir / "ai_benchmark.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    settings = get_settings()
    cases = select_cases(load_conversations())

    extractors = []
    for provider in ("ollama", "openrouter"):
        try:
            extractors.append(build_extractor(provider, settings))
        except UnknownProviderError:
            continue

    report = run_benchmark(extractors, cases)
    json_path, md_path = write_reports(report)

    print("AI extraction benchmark (AI-0)")
    print(f"Cases selected: {len(cases)}")
    for case in report["cases"]:
        print(f"  - {case['case']}: {case['conversation_id']} ({case['message_count']} msgs)")
    print("")
    for provider, entry in report["providers"].items():
        if entry["available"]:
            metrics = entry["metrics"]
            print(
                f"- {provider} (model={entry['model']}): available · "
                f"schema_valid_rate={metrics['schema_valid_rate']} · "
                f"avg_latency_ms={metrics['average_latency_ms']}"
            )
        else:
            print(f"- {provider}: OMITTED — {entry['availability_reason']}")
    print("")
    print(f"Reports written: {json_path} , {md_path}")


if __name__ == "__main__":
    main()
