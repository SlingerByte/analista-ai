"""Mini benchmark controlado de Groq (NO producción): 10 conversaciones, máx. 15 requests.

Uso:
    uv run python scripts/run_ai_benchmark_groq_controlled.py --model openai/gpt-oss-20b

Reutiliza la metodología de los benchmarks existentes: mismo Gold Set
(`reports/gold_set.json`), mismo prompt v2, mismo schema v1, misma validación
determinista y mismas definiciones de TP/FP/FN/accuracy/precision/recall
(`scripts/evaluate_ai_benchmark.py`). No toca producción ni la BD.

Reglas de presupuesto (estrictas):
- secuencial, una conversación a la vez, sin concurrencia;
- máximo absoluto MAX_HTTP_REQUESTS (default 15) requests HTTP en total;
- ante HTTP 429: NO reintentar; se registra `rate_limited` y se continúa;
- si el 429 indica cuota diaria/global agotada -> DETENER todo inmediatamente;
- ante 5xx/timeout: máximo 1 retry y solo si queda presupuesto;
- nunca se imprimen ni guardan secretos (GROQ_API_KEY, tokens, Authorization).

Llama a `extractor._post_chat` (una sola request HTTP por llamada, sin el
retry interno de `_call`) para tener control exacto del presupuesto.

Escribe:
    reports/ai_benchmark_groq_controlled.json
    reports/ai_benchmark_groq_controlled.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.base import AIRequestError, _validate_content  # noqa: E402
from app.ai.groq import GroqExtractor  # noqa: E402
from app.ai.prompt import EXTRACTION_PROMPT_VERSION  # noqa: E402
from app.ai.schema import SCHEMA_VERSION  # noqa: E402
from app.ai.validation import split_transcript_messages, validate_extraction  # noqa: E402
from app.config import get_settings  # noqa: E402
from scripts.evaluate_ai_benchmark import ALL_FIELDS, _classify, _metrics  # noqa: E402
from scripts.run_ai_benchmark_openrouter import _build_input, _percentile  # noqa: E402

GOLD = ROOT / "reports" / "gold_set.json"
HISTORICAL_METRICS = ROOT / "reports" / "ai_gold_metrics.json"
GLM_CONTROLLED = ROOT / "reports" / "ai_benchmark_glm52_controlled.json"
OUTPUT_JSON = ROOT / "reports" / "ai_benchmark_groq_controlled.json"
OUTPUT_MD = ROOT / "reports" / "ai_benchmark_groq_controlled.md"

DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_LIMIT = 10
DEFAULT_MAX_REQUESTS = 15
DEFAULT_TIMEOUT = 120.0

HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})")
REMAINING_ZERO_RE = re.compile(r"remaining[\"']?\s*[:=]\s*0(?!\d)")

# Señales de cuota diaria/global agotada: ante cualquiera de ellas el benchmark
# se detiene por completo en vez de desperdiciar requests. OJO: "rate limit
# reached" solo cuenta como cuota si NO hay marcadores de ventana transitoria
# (TPM/RPM con "try again in"): un 429 por tokens-por-minuto es transitorio y
# solo se registra como `rate_limited` para continuar con la siguiente.
QUOTA_EXHAUSTED_MARKERS = (
    "daily limit",
    "requests per day",
    "per-day",
    "quota exceeded",
    "quota_exhausted",
    "try again tomorrow",
)

# Ventana transitoria (tokens/requests por minuto/segundo): reintentable con
# espera corta, NO es agotamiento de cuota.
TRANSIENT_WINDOW_MARKERS = (
    "per minute",
    "per second",
    "try again in",
)

# Headers de rate limit que vale la pena conservar en el reporte (sin secretos).
RATE_LIMIT_HEADER_PREFIXES = ("retry-after", "ratelimit-", "x-ratelimit-")


def extract_http_status(message: str | None) -> int | None:
    if not message:
        return None
    match = HTTP_STATUS_RE.search(message)
    return int(match.group(1)) if match else None


def is_rate_limit(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return "429" in message or "rate limit" in lowered or "rate_limit" in lowered


def is_quota_exhausted(message: str | None) -> bool:
    """¿Indica el error cuota diaria/global agotada? Pura (testeable)."""
    if not message:
        return False
    lowered = message.lower()
    if any(marker in lowered for marker in QUOTA_EXHAUSTED_MARKERS):
        return True
    if REMAINING_ZERO_RE.search(lowered):
        return True
    if "free-models-per-day" in lowered:
        return True
    # "rate limit reached" sin ventana transitoria: ante la duda se trata como
    # cuota (no se desperdician requests); con ventana TPM/RPM es transitorio.
    if "rate limit reached" in lowered and not any(
        marker in lowered for marker in TRANSIENT_WINDOW_MARKERS
    ):
        return True
    return False


def is_timeout(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return "timeout" in lowered or "timed out" in lowered


def is_server_error(message: str | None) -> bool:
    if not message:
        return False
    return any(code in message for code in ("HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504"))


def pick_rate_limit_headers(headers: dict | None) -> dict:
    """Filtra headers de rate limit. Nunca incluye Authorization ni secretos."""
    out = {}
    for key, value in (headers or {}).items():
        name = str(key).lower()
        if name == "authorization" or "key" in name or "token" in name or "cookie" in name:
            continue
        if name == "retry-after" or name.startswith(RATE_LIMIT_HEADER_PREFIXES[1:]):
            out[name] = str(value)
    return out


def coverage_of(record: dict, min_msgs: int, max_msgs: int) -> set[str]:
    """Categorías que cubre un record del Gold Set. Pura (testeable)."""
    cats: set[str] = set()
    if record.get("conversation_id") == "CONV-00058":
        cats.add("conv58_obligatoria")
    inten = record.get("gold_intencion_compra")
    if inten == "alta":
        cats.add("intencion_alta")
    if inten in ("baja", "media", "informativa"):
        cats.add("intencion_baja_media_informativa")
    if record.get("gold_cuota_inicial") is not None:
        cats.add("cuota_inicial_explicita")
    if record.get("gold_forma_pago") is not None:
        cats.add("forma_pago_explicita")
    obj = record.get("gold_objecion")
    if obj is not None:
        cats.add("objecion_explicita")
        if obj != "precio":
            cats.add("objecion_no_precio")
    if record.get("gold_solicitud_cita"):
        cats.add("cita")
    if record.get("gold_solicitud_cotizacion"):
        cats.add("cotizacion")
    notes = json.dumps(record.get("gold_notes") or {}, ensure_ascii=False).lower()
    if "switch" in notes or "cambi" in notes or "contrast" in notes:
        cats.add("cambio_modelo")
    if record.get("message_count") == min_msgs:
        cats.add("conversacion_corta")
    if record.get("message_count") == max_msgs:
        cats.add("conversacion_larga")
    return cats


# Orden de prioridad para cubrir categorías (tras CONV-00058 obligatoria).
_CATEGORY_PRIORITY = (
    "intencion_baja_media_informativa",
    "forma_pago_explicita",
    "objecion_no_precio",
    "objecion_explicita",
    "cotizacion",
    "cambio_modelo",
    "conversacion_corta",
    "conversacion_larga",
    "cita",
    "cuota_inicial_explicita",
    "intencion_alta",
)


def select_controlled_cases(records: list[dict], limit: int = 10) -> list[tuple[dict, set[str]]]:
    """Selección determinista y estratificada. Pura (testeable).

    CONV-00058 siempre primera; luego greedy en orden del Gold Set cubriendo
    cada categoría prioritaria con el primer record que la aporte; se rellena
    hasta `limit` con los primeros records no seleccionados. Sin IDs inventados.
    """
    if not records:
        return []
    min_msgs = min(r.get("message_count", 0) for r in records)
    max_msgs = max(r.get("message_count", 0) for r in records)
    cov = {r["conversation_id"]: coverage_of(r, min_msgs, max_msgs) for r in records}

    selected: list[dict] = []
    covered: set[str] = set()

    def _take(record: dict) -> None:
        selected.append(record)
        covered.update(cov[record["conversation_id"]])

    first = next((r for r in records if r.get("conversation_id") == "CONV-00058"), None)
    if first is not None:
        _take(first)
    for category in _CATEGORY_PRIORITY:
        if category in covered:
            continue
        candidate = next(
            (r for r in records if r not in selected and category in cov[r["conversation_id"]]),
            None,
        )
        if candidate is not None:
            _take(candidate)
    for record in records:
        if len(selected) >= limit:
            break
        if record not in selected:
            _take(record)
    return [(r, set(cov[r["conversation_id"]])) for r in selected[:limit]]


def _num_close(a, b) -> bool:
    try:
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) <= max(1.0, abs(float(a)) * 0.10)
    except (TypeError, ValueError):
        return False


def run_groq_benchmark(extractor, selected: list[tuple[dict, set[str]]],
                       *, max_requests: int, delay_s: float = 1.0,
                       sleep_fn=time.sleep) -> dict:
    """Ejecuta el benchmark respetando el presupuesto global. Testeable.

    `extractor` debe exponer `_post_chat(conversation) -> str` (una request),
    `provider`, `model` y `last_response_headers`. No persiste nada.
    """
    results: list[dict] = []
    http_requests = 0
    count_ok = count_rate_limited = count_timeout = count_error = 0
    count_429 = 0
    stopped_early = False
    stop_reason: str | None = None
    started = time.perf_counter()

    def _single_request(conversation) -> tuple[str | None, int | None, str | None, dict]:
        """Una request HTTP. Devuelve (content, latency_ms, error, rl_headers)."""
        nonlocal http_requests, count_429
        http_requests += 1
        try:
            t0 = time.perf_counter()
            content = extractor._post_chat(conversation)
            return content, int((time.perf_counter() - t0) * 1000), None, {}
        except AIRequestError as exc:
            message = str(exc)
            if "429" in message:
                count_429 += 1
            return None, None, message, pick_rate_limit_headers(
                getattr(extractor, "last_response_headers", {}))
        except Exception as exc:  # noqa: BLE001 - el benchmark debe continuar
            return None, None, f"{type(exc).__name__}: {exc}", {}

    for index, (record, categories) in enumerate(selected, start=1):
        if http_requests >= max_requests:
            stopped_early = True
            stop_reason = f"presupuesto HTTP agotado ({max_requests})"
            break
        conversation, transcript = _build_input(record)
        content = latency = last_error = None
        http_status = None
        rl_headers: dict = {}
        attempts = 0
        status = "error"

        while True:
            if http_requests >= max_requests:
                stopped_early = True
                stop_reason = f"presupuesto HTTP agotado ({max_requests})"
                break
            attempts += 1
            content, latency, last_error, rl_headers = _single_request(conversation)
            if last_error is None:
                status = "ok"
                break
            http_status = extract_http_status(last_error) or http_status
            if is_rate_limit(last_error):
                # 429: NO reintentar jamás. Cuota diaria -> detener todo.
                status = "rate_limited"
                if is_quota_exhausted(last_error):
                    stopped_early = True
                    stop_reason = "cuota diaria/global agotada"
                break
            if (is_server_error(last_error) or is_timeout(last_error)) and attempts < 2:
                # 5xx/timeout: un único retry si queda presupuesto.
                continue
            status = "timeout" if is_timeout(last_error) else "error"
            break

        entry: dict = {
            "conversation_id": record["conversation_id"],
            "categories": sorted(categories),
            "model": getattr(extractor, "model", None),
            "attempts": attempts,
            "status": status,
            "http_status": http_status,
            "rate_limit_headers": rl_headers,
            "success": content is not None and status == "ok",
            "latency_ms": latency,
            "error": last_error,
            "raw": None,
            "schema_valid": None,
            "validation_errors": None,
            "validated": None,
            "invalidated": None,
        }
        if content is not None and status == "ok":
            try:
                entry["raw"] = json.loads(content)
            except json.JSONDecodeError:
                entry["raw"] = None
            outcome = _validate_content(conversation, content, latency or 0,
                                        extractor.provider, extractor.model)
            entry["schema_valid"] = outcome.schema_valid
            if outcome.result is not None:
                client, advisor = split_transcript_messages(transcript)
                validation = validate_extraction(outcome.result, client, advisor)
                entry["validated"] = validation.extraction.model_dump()
                entry["invalidated"] = validation.invalidated
                entry["validation_errors"] = validation.invalidated
                count_ok += 1
            else:
                entry["validation_errors"] = {"schema": outcome.error}

        if status == "rate_limited":
            count_rate_limited += 1
        elif status == "timeout":
            count_timeout += 1
        elif status != "ok":
            count_error += 1

        results.append(entry)
        elapsed = time.perf_counter() - started
        print(f"  {index}/{len(selected)} ({elapsed:.0f}s) {entry['conversation_id']} "
              f"status={status} attempts={attempts} http={http_requests}/{max_requests}",
              flush=True)
        if stopped_early and stop_reason == "cuota diaria/global agotada":
            print("  Cuota diaria/global agotada: benchmark detenido.", flush=True)
            break
        if index < len(selected) and delay_s > 0:
            sleep_fn(delay_s)

    assert http_requests <= max_requests, "presupuesto HTTP excedido"

    per_field = {f: {} for f in ALL_FIELDS}
    graded = schema_valid_count = schema_evaluated = 0
    details = []
    for entry, (record, _cats) in zip(results, selected):
        if entry.get("schema_valid") is not None:
            schema_evaluated += 1
            if entry.get("schema_valid"):
                schema_valid_count += 1
        pred = entry.get("validated")
        if pred is None:
            continue
        graded += 1
        outcome_map = {}
        for field in ALL_FIELDS:
            gold_value = record.get(f"gold_{field}")
            pred_value = pred.get(field)
            cls = _classify(field, gold_value, pred_value)
            per_field[field][cls] = per_field[field].get(cls, 0) + 1
            outcome_map[field] = {"gold": gold_value, "pred": pred_value, "class": cls}
        details.append({"conversation_id": entry["conversation_id"], "outcome": outcome_map})

    metrics = {f: _metrics(per_field[f], graded) for f in ALL_FIELDS}
    total_tp = sum(metrics[f]["tp"] for f in ALL_FIELDS)
    total_fp = sum(metrics[f]["fp"] for f in ALL_FIELDS)
    total_fn = sum(metrics[f]["fn"] for f in ALL_FIELDS)
    total_tn = sum(metrics[f]["tn"] for f in ALL_FIELDS)
    decisions = total_tp + total_fp + total_fn + total_tn
    latencies = [e["latency_ms"] for e in results if e["latency_ms"] is not None and e["status"] == "ok"]

    return {
        "selected": [r["conversation_id"] for r, _c in selected],
        "executed": len(results),
        "http_requests": http_requests,
        "max_requests": max_requests,
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
        "count_ok": count_ok,
        "count_rate_limited": count_rate_limited,
        "count_timeout": count_timeout,
        "count_error": count_error,
        "count_429": count_429,
        "graded": graded,
        "schema_evaluated": schema_evaluated,
        "schema_valid_count": schema_valid_count,
        "per_field": per_field,
        "metrics": metrics,
        "tp": total_tp, "fp": total_fp, "fn": total_fn, "tn": total_tn,
        "decisions": decisions,
        "latencies": latencies,
        "details": details,
        "results": results,
    }


def _build_error_analysis(details: list[dict]) -> dict:
    by_id = {d["conversation_id"]: d["outcome"] for d in details}

    def _mismatches(field: str) -> list[str]:
        return [cid for cid, oc in by_id.items() if oc.get(field, {}).get("class") not in ("tp", "tn")]

    cuota_as_presupuesto = []
    cuota_implies_financiacion = []
    for cid, oc in by_id.items():
        cuota_gold = oc.get("cuota_inicial", {}).get("gold")
        pres_gold = oc.get("presupuesto", {}).get("gold")
        pres_pred = oc.get("presupuesto", {}).get("pred")
        forma_gold = oc.get("forma_pago", {}).get("gold")
        forma_pred = oc.get("forma_pago", {}).get("pred")
        if cuota_gold is not None and pres_gold is None and _num_close(pres_pred, cuota_gold):
            cuota_as_presupuesto.append(cid)
        if cuota_gold is not None and forma_gold is None and str(forma_pred or "").lower() == "financiacion":
            cuota_implies_financiacion.append(cid)

    model_mm = _mismatches("model_interes")
    return {
        "modelo": {"mismatches": model_mm,
                   "note": "posible confusión entre primer modelo mencionado y modelo vigente"},
        "intencion": {"mismatches": _mismatches("intencion_compra"),
                      "note": "informativa convertida en alta, o señales ('me sirve', 'voy') ignoradas"},
        "presupuesto": {"mismatches": _mismatches("presupuesto"),
                        "cuota_confudida_como_presupuesto": cuota_as_presupuesto,
                        "note": "gold presupuesto es null en todo el Gold Set: cualquier valor es invención"},
        "inicial": {"mismatches": _mismatches("cuota_inicial"),
                    "note": "cuota mensual del asesor convertida en inicial, o inicial del cliente ignorada"},
        "forma_pago": {"mismatches": _mismatches("forma_pago"),
                       "cuota_implica_financiacion": cuota_implies_financiacion,
                       "note": "mencionar inicial no implica financiacion si el cliente no lo dijo"},
        "objecion": {"mismatches": _mismatches("objecion"),
                     "note": "'muy cara' / 'mas economico' / 'cuota alta' detectadas o ignoradas"},
        "cita": {"mismatches": _mismatches("solicitud_cita"),
                 "note": "'los visito' / 'puedo pasar' detectadas; solo cliente cuenta como evidencia"},
        "cotizacion": {"mismatches": _mismatches("solicitud_cotizacion"),
                       "note": "'dale' / 'ok' / 'listo' no son solicitud de cotización"},
    }


def _build_conv58(records: list[dict], results: list[dict]) -> dict:
    record = next((r for r in records if r.get("conversation_id") == "CONV-00058"), None)
    entry = next((e for e in results if e.get("conversation_id") == "CONV-00058"), None)
    if record is None:
        return {"conversation_id": "CONV-00058", "found_in_gold": False}
    comparison = []
    for field in ALL_FIELDS:
        gold_value = record.get(f"gold_{field}")
        raw = (entry or {}).get("raw") or {}
        final = (entry or {}).get("validated") or {}
        raw_value = raw.get(field)
        final_value = final.get(field)
        evidence = raw.get(f"{field}_evidence")
        if entry and entry.get("validated") is not None:
            cls = _classify(field, gold_value, final_value)
            verdict = "correcto" if cls in ("tp", "tn") else "incorrecto"
        else:
            verdict = "no_evaluado"
        comparison.append({"field": field, "gold": gold_value, "groq": final_value,
                           "evidencia": evidence, "veredicto": verdict})
    return {"conversation_id": "CONV-00058", "found_in_gold": True,
            "status": (entry or {}).get("status"),
            "validation_errors": (entry or {}).get("validation_errors"),
            "comparison": comparison}


def _load_historical() -> dict:
    out: dict = {}
    try:
        data = json.loads(HISTORICAL_METRICS.read_text(encoding="utf-8"))
        for model, entry in data.get("providers", {}).items():
            overall = entry.get("overall") or {}
            out[model] = {"accuracy": overall.get("accuracy"),
                          "precision": overall.get("precision"),
                          "recall": overall.get("recall"),
                          "n": entry.get("conversations")}
    except (OSError, json.JSONDecodeError):
        pass
    try:
        glm = json.loads(GLM_CONTROLLED.read_text(encoding="utf-8"))
        ov = glm.get("overall") or {}
        out["z-ai/glm-5.2:free (controlled,20)"] = {
            "accuracy": ov.get("accuracy"), "precision": ov.get("precision"),
            "recall": ov.get("recall"), "n": glm.get("graded"),
            "availability_rate": (glm.get("availability") or {}).get("availability_rate"),
            "note": "0/20 ok por cuota diaria OpenRouter: sin calidad observable",
        }
    except (OSError, json.JSONDecodeError):
        pass
    return out


def build_report(model: str, gold_size: int, selected: list[tuple[dict, set[str]]],
                 outcome: dict, *, max_requests: int, timeout_s: float, delay_s: float) -> dict:
    """Ensambla el reporte final a partir del resultado. Puro (testeable)."""
    total = len(selected)
    ok, rl = outcome["count_ok"], outcome["count_rate_limited"]
    lat = outcome["latencies"]
    n = outcome["graded"]
    overall = {
        "tp": outcome["tp"], "fp": outcome["fp"], "fn": outcome["fn"], "tn": outcome["tn"],
        "decisions": outcome["decisions"],
        "accuracy": round((outcome["tp"] + outcome["tn"]) / outcome["decisions"], 4) if outcome["decisions"] else None,
        "precision": round(outcome["tp"] / (outcome["tp"] + outcome["fp"]), 4) if (outcome["tp"] + outcome["fp"]) else None,
        "recall": round(outcome["tp"] / (outcome["tp"] + outcome["fn"]), 4) if (outcome["tp"] + outcome["fn"]) else None,
    }
    report = {
        "model": model,
        "provider": "groq",
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "gold_set_source": "reports/gold_set.json",
        "gold_set_size": gold_size,
        "selection": [{"conversation_id": r["conversation_id"], "categories": sorted(c)} for r, c in selected],
        "evaluated": outcome["executed"],
        "graded": n,
        "persistence": "none",
        "config": {"max_requests": max_requests, "timeout_s": timeout_s,
                   "delay_between_s": delay_s, "sequential": True,
                   "retry_policy": "429 sin retry (stop si cuota diaria); 5xx/timeout 1 retry con presupuesto"},
        "requests": {"http_requests": outcome["http_requests"], "max_requests": outcome["max_requests"],
                     "stopped_early": outcome["stopped_early"], "stop_reason": outcome["stop_reason"]},
        "availability": {"total": total, "executed": outcome["executed"], "ok": ok,
                         "rate_limited": rl, "timeouts": outcome["count_timeout"],
                         "errors": outcome["count_error"], "total_429": outcome["count_429"],
                         "availability_rate": round(ok / total, 4) if total else None},
        "latency_ms": {"avg": round(statistics.mean(lat), 1) if lat else None,
                       "median": round(statistics.median(lat), 1) if lat else None,
                       "min": min(lat) if lat else None, "max": max(lat) if lat else None,
                       "p95": _percentile(lat, 95), "n": len(lat)},
        "schema": {"evaluated": outcome["schema_evaluated"], "valid": outcome["schema_valid_count"],
                   "schema_valid_rate": round(outcome["schema_valid_count"] / outcome["schema_evaluated"], 4) if outcome["schema_evaluated"] else None},
        "overall": overall,
        "per_field": outcome["metrics"],
        "error_analysis": _build_error_analysis(outcome["details"]),
        "conv_00058": _build_conv58([r for r, _c in selected], outcome["results"]),
        "historical_comparison": _load_historical(),
        "details": outcome["details"],
        "results": outcome["results"],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Groq controlled mini benchmark (10)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--output-json", default=str(OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(OUTPUT_MD))
    args = parser.parse_args()

    settings = get_settings()
    extractor = GroqExtractor(
        api_key=settings.groq_api_key,
        model=args.model,
        base_url=settings.groq_base_url,
        timeout=args.timeout,
    )
    available, reason = extractor.availability()
    print(f"provider={extractor.provider} model={args.model} available={available} ({reason})")
    if not available:
        raise SystemExit("extractor no disponible")

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    selected = select_controlled_cases(gold["records"], limit=args.limit)
    print("Selección determinista:")
    for record, cats in selected:
        print(f"  {record['conversation_id']}: {sorted(cats)}")

    outcome = run_groq_benchmark(extractor, selected, max_requests=args.max_requests,
                                 delay_s=args.delay)
    report = build_report(args.model, len(gold["records"]), selected, outcome,
                          max_requests=args.max_requests, timeout_s=args.timeout,
                          delay_s=args.delay)
    overall = report["overall"]
    out_json = Path(args.output_json)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = Path(args.output_md)
    out_md.write_text(_render_markdown(report), encoding="utf-8")
    print("overall:", overall)
    print("availability:", report["availability"])
    print("requests:", report["requests"])
    print("written", out_json)
    print("written", out_md)


def _render_markdown(report: dict) -> str:
    model = report["model"]
    av, lat, sch, ov = report["availability"], report["latency_ms"], report["schema"], report["overall"]
    req = report["requests"]
    L = [
        "# Groq GPT-OSS-20B — Controlled Benchmark",
        "",
        f"Model: {model} | Provider: groq | Prompt: {report['prompt_version']} | "
        f"Schema: {report['schema_version']} | Validation: producción | Persistence: none",
        "",
        "## Executive summary",
        "",
        f"- conversaciones: {report['evaluated']}/{av['total']} "
        f"({', '.join(s['conversation_id'] for s in report['selection'])})",
        f"- requests HTTP: {req['http_requests']} (máx. {req['max_requests']})",
        f"- disponibilidad: ok={av['ok']}/{av['total']} (rate={av['availability_rate']}), "
        f"rate_limited={av['rate_limited']}, timeouts={av['timeouts']}, errors={av['errors']}, "
        f"429s={av['total_429']}",
        f"- detención anticipada: {req['stopped_early']} ({req['stop_reason']})",
        f"- schema válido: {sch['valid']}/{sch['evaluated']} (rate={sch['schema_valid_rate']})",
        f"- latencia ok (ms): avg={lat['avg']} median={lat['median']} min={lat['min']} "
        f"max={lat['max']} p95={lat['p95']} n={lat['n']}",
        f"- calidad (graded={report['graded']}): accuracy={ov['accuracy']} "
        f"precision={ov['precision']} recall={ov['recall']}",
        "",
        "## Results",
        "",
        "| Campo | Accuracy | Precision | Recall | TP | FP | FN |",
        "| ----- | -------: | --------: | -----: | -: | -: | -: |",
    ]
    for field in ALL_FIELDS:
        m = report["per_field"][field]
        L.append(f"| {field} | {m['accuracy']} | {m['precision']} | {m['recall']} | "
                 f"{m['tp']} | {m['fp']} | {m['fn']} |")
    L += ["", "## Per-conversation results", "",
          "| Conversation | Status | Latency | Schema | Correct fields |",
          "| ------------ | ------ | ------: | ------ | -------------: |"]
    details_by_id = {d["conversation_id"]: d for d in report["details"]}
    for entry in report["results"]:
        detail = details_by_id.get(entry["conversation_id"])
        if detail is None:
            correct = "-"
        else:
            oc = detail["outcome"]
            correct = f"{sum(1 for v in oc.values() if v['class'] in ('tp', 'tn'))}/{len(oc)}"
        L.append(f"| {entry['conversation_id']} | {entry['status']} | {entry['latency_ms']} | "
                 f"{entry['schema_valid']} | {correct} |")
    L += ["", "## Error analysis", ""]
    for section, content in report["error_analysis"].items():
        mism = {k: v for k, v in content.items() if k != "note"}
        L.append(f"- {section}: {mism} — {content.get('note', '')}")
    conv = report["conv_00058"]
    L += ["", "## CONV-00058", ""]
    if not conv.get("found_in_gold"):
        L.append("CONV-00058 no encontrado en el Gold Set.")
    else:
        L += [f"status={conv.get('status')} validation_errors={conv.get('validation_errors')}", "",
              "| field | gold | groq | evidencia | veredicto |",
              "|---|---|---|---|---|"]
        for row in conv["comparison"]:
            L.append(f"| {row['field']} | {row['gold']} | {row['groq']} | "
                     f"{row['evidencia']} | {row['veredicto']} |")
    L += ["", "## Comparison", "",
          "Solo datos observados, sin ranking ni recomendación automática.", "",
          "| model | accuracy | precision | recall | n |",
          "|---|---|---|---|---|"]
    for hist_model, h in report["historical_comparison"].items():
        L.append(f"| {hist_model} | {h.get('accuracy')} | {h.get('precision')} | "
                 f"{h.get('recall')} | {h.get('n')} |")
    L.append(f"| {model} (controlled, {report['graded']} graded) | {ov['accuracy']} | "
             f"{ov['precision']} | {ov['recall']} | {report['graded']} |")
    ea = report["error_analysis"]
    L += ["", "## Engineering interpretation", "",
          f"1. ¿Groq respondió de manera consistente? ok={av['ok']}/{av['total']}, "
          f"rate_limited={av['rate_limited']}, 429s={av['total_429']}.",
          f"2. ¿El schema fue válido? {sch['valid']}/{sch['evaluated']} (rate={sch['schema_valid_rate']}).",
          f"3. ¿La latencia es razonable para una demo? avg={lat['avg']} ms, "
          f"median={lat['median']} ms, max={lat['max']} ms (n={lat['n']}).",
          f"4. ¿Hubo rate limiting? rate_limited={av['rate_limited']}, "
          f"detención anticipada={req['stopped_early']} ({req['stop_reason']}).",
          f"5. ¿Qué campos parecen más confiables? " + ", ".join(
              f"{f} (acc={report['per_field'][f]['accuracy']})"
              for f in ALL_FIELDS if report["per_field"][f]["accuracy"] == 1.0) + ".",
          f"6. ¿Qué campos siguen siendo problemáticos? " + ", ".join(
              f"{f}" for f in ALL_FIELDS
              if (report["per_field"][f]["accuracy"] or 1.0) < 1.0) + ".",
          f"7. ¿El modelo cometió inferencias peligrosas? cuota→presupuesto: "
          f"{ea['presupuesto']['cuota_confudida_como_presupuesto']}; "
          f"cuota→financiación: {ea['forma_pago']['cuota_implica_financiacion']}.",
          "8. ¿Qué diferencias hay frente a los benchmarks locales? Ver tabla Comparison "
          "(bases distintas: 110 vs slice de 10; GLM-5.2 sin calidad observable por 429).",
          "",
          "> Prompt, schema y validator intactos. Patrones nuevos van como hallazgo, no como parche.",
          ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
