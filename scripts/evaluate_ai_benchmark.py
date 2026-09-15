"""Tooling de evaluación (NO producción): métricas gold vs modelos.

Uso:
    uv run python scripts/evaluate_ai_benchmark.py

Lee `reports/gold_set.json` y `reports/ai_gold_benchmark.json`, calcula métricas
por campo y por modelo (accuracy, precision, recall, FP, FN, tasa de null) y
escribe `reports/ai_gold_metrics.json`. No modifica producción ni la BD.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.scoring.engine import SCORE_V1_PARAMS  # noqa: E402
from app.ai.schema import ExtractionResult  # noqa: E402
from app.ai.validation import validate_extraction  # noqa: E402
from app.text import normalize_key  # noqa: E402
from scripts.ai_gold_rules import CATALOG_LINES  # noqa: E402

GOLD = ROOT / "reports" / "gold_set.json"
BENCH = ROOT / "reports" / "ai_gold_benchmark.json"
OUTPUT = ROOT / "reports" / "ai_gold_metrics.json"

CATEGORICAL = ["intencion_compra", "forma_pago", "objecion"]
BOOLEAN = ["solicitud_cita", "solicitud_cotizacion"]
NUMERIC = ["presupuesto", "cuota_inicial"]
ALL_FIELDS = ["model_interes"] + CATEGORICAL + NUMERIC + BOOLEAN


def _model_key(value) -> str | None:
    if value is None:
        return None
    key = normalize_key(value)
    for cat_key, canonical in CATALOG_LINES.items():
        if cat_key in key or normalize_key(canonical) == key:
            return normalize_key(canonical)
    return key or None


def _cat_key(field: str, value):
    if value is None:
        return None
    if field == "model_interes":
        return _model_key(value)
    return normalize_key(value)


def _num_equal(gold: float, pred: float) -> bool:
    return abs(float(gold) - float(pred)) <= max(1.0, abs(float(gold)) * 0.10)


def _classify(field: str, gold, pred) -> str:
    if field in NUMERIC:
        g = None if gold is None else float(gold)
        p = None if pred is None else float(pred)
        if g is None and p is None:
            return "tn"
        if g is None and p is not None:
            return "fp"
        if g is not None and p is None:
            return "fn"
        return "tp" if _num_equal(g, p) else "wrong"
    if field in BOOLEAN:
        g = bool(gold) if gold is not None else False
        p = bool(pred) if pred is not None else False
        if g and p:
            return "tp"
        if not g and not p:
            return "tn"
        return "fp" if p else "fn"
    # categorical
    g = _cat_key(field, gold)
    p = _cat_key(field, pred)
    if g is None and p is None:
        return "tn"
    if g is None and p is not None:
        return "fp"
    if g is not None and p is None:
        return "fn"
    return "tp" if g == p else "wrong"


def _metrics(counters: dict, total: int) -> dict:
    tp, fp, fn, tn, wrong = (counters.get(k, 0) for k in ("tp", "fp", "fn", "tn", "wrong"))
    fp_total, fn_total = fp + wrong, fn + wrong
    precision = tp / (tp + fp_total) if (tp + fp_total) else None
    recall = tp / (tp + fn_total) if (tp + fn_total) else None
    accuracy = (tp + tn) / total if total else None
    predicted_null = tn + fn
    return {
        "total": total,
        "tp": tp, "fp": fp_total, "fn": fn_total, "tn": tn, "wrong": wrong,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "null_rate": round(predicted_null / total, 4) if total else None,
    }


def main() -> None:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["records"]
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    gold_by_id = {r["conversation_id"]: r for r in gold}

    output = {"gold_set_size": len(gold), "providers": {}, "score_impact_refs": {}}
    for model, entry in bench.get("providers", {}).items():
        if not entry.get("available"):
            output["providers"][model] = {"available": False}
            continue
        per_field = {f: {} for f in ALL_FIELDS}
        details = []
        for result in entry["results"]:
            record = gold_by_id.get(result["conversation_id"])
            if record is None:
                continue
            # Recompute deterministic validation from the stored raw output so the
            # comparison reflects the productive pipeline without re-running models.
            pred = {}
            raw = result.get("raw")
            if raw:
                client = [m["texto"] for m in record["transcript"] if m["emisor"] == "cliente"]
                advisor = [m["texto"] for m in record["transcript"] if m["emisor"] != "cliente"]
                try:
                    extraction = ExtractionResult.model_validate(raw)
                    pred = validate_extraction(extraction, client, advisor).extraction.model_dump()
                except Exception:  # noqa: BLE001
                    pred = {}
            outcome = {}
            for field in ALL_FIELDS:
                gold_value = record.get(f"gold_{field}")
                pred_value = pred.get(field)
                cls = _classify(field, gold_value, pred_value)
                per_field[field][cls] = per_field[field].get(cls, 0) + 1
                outcome[field] = {"gold": gold_value, "pred": pred_value, "class": cls}
            details.append({"conversation_id": result["conversation_id"], "outcome": outcome,
                            "schema_valid": result["schema_valid"], "latency_ms": result["latency_ms"]})

        metrics = {f: _metrics(per_field[f], len(details)) for f in ALL_FIELDS}
        total_tp = sum(metrics[f]["tp"] for f in ALL_FIELDS)
        total_fp = sum(metrics[f]["fp"] for f in ALL_FIELDS)
        total_fn = sum(metrics[f]["fn"] for f in ALL_FIELDS)
        total_tn = sum(metrics[f]["tn"] for f in ALL_FIELDS)
        decisions = total_tp + total_fp + total_fn + total_tn
        latencies = [d["latency_ms"] for d in details]
        output["providers"][model] = {
            "available": True,
            "conversations": len(details),
            "schema_valid_rate": round(sum(1 for d in details if d["schema_valid"]) / len(details), 4) if details else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "overall": {
                "tp": total_tp, "fp": total_fp, "fn": total_fn, "tn": total_tn,
                "accuracy": round((total_tp + total_tn) / decisions, 4) if decisions else None,
                "precision": round(total_tp / (total_tp + total_fp), 4) if (total_tp + total_fp) else None,
                "recall": round(total_tp / (total_tp + total_fn), 4) if (total_tp + total_fn) else None,
            },
            "per_field": metrics,
            "details": details,
        }

    output["score_impact_refs"] = {
        "FORMA_PAGO_DECLARADA": SCORE_V1_PARAMS["forma_pago_points"],
        "CLIENTE_PIDIO_COTIZACION": SCORE_V1_PARAMS["cotizacion_points"],
        "CLIENTE_PIDIO_CITA": SCORE_V1_PARAMS["cita_points"],
        "CUOTA_SUFICIENTE": SCORE_V1_PARAMS["cuota_suficiente_points"],
        "PRESUPUESTO_COMPATIBLE": SCORE_V1_PARAMS["presupuesto_compatible_points"],
        "intencion_points": SCORE_V1_PARAMS["intencion_points"],
        "cita_urgency_override": SCORE_V1_PARAMS["cita_urgency_override"],
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    for model, data in output["providers"].items():
        if data.get("available"):
            print(f"{model}: overall={data['overall']} avg_latency_ms={data['avg_latency_ms']}")
    print(f"written {OUTPUT}")


if __name__ == "__main__":
    main()
