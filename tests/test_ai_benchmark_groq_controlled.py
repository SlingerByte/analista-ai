from __future__ import annotations

import json

from app.ai.base import AIRequestError
from scripts.run_ai_benchmark_groq_controlled import (
    _CATEGORY_PRIORITY,
    _render_markdown,
    build_report,
    coverage_of,
    is_quota_exhausted,
    is_rate_limit,
    is_server_error,
    is_timeout,
    pick_rate_limit_headers,
    run_groq_benchmark,
    select_controlled_cases,
)

GOLD_PATH = "reports/gold_set.json"


def _gold_records() -> list[dict]:
    with open(GOLD_PATH, encoding="utf-8") as fh:
        return json.load(fh)["records"]


class FakeGroq:
    """Extractor falso: `_post_chat` scriptado, una request por llamada."""

    provider = "groq"

    def __init__(self, model="openai/gpt-oss-20b", behaviors=None):
        self.model = model
        self.behaviors = list(behaviors or [])
        self.calls = 0
        self.last_response_headers: dict = {}

    def _post_chat(self, conversation):
        self.calls += 1
        if not self.behaviors:
            return json.dumps({"model_interes": None})
        behavior = self.behaviors.pop(0) if len(self.behaviors) > 1 else self.behaviors[0]
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _run(selected, extractor, max_requests=15):
    return run_groq_benchmark(extractor, selected, max_requests=max_requests,
                              delay_s=0, sleep_fn=lambda s: None)


# --- Selección ---------------------------------------------------------------


def test_selection_is_deterministic_exactly_ten_and_real_ids():
    records = _gold_records()
    first = select_controlled_cases(records)
    second = select_controlled_cases(records)
    assert len(first) == 10
    ids = [r["conversation_id"] for r, _c in first]
    assert len(set(ids)) == 10
    assert ids == [r["conversation_id"] for r, _c in second]
    real_ids = {r["conversation_id"] for r in records}
    assert set(ids) <= real_ids  # ningún ID inventado


def test_selection_includes_conv58_first():
    selected = select_controlled_cases(_gold_records())
    assert selected[0][0]["conversation_id"] == "CONV-00058"
    assert "conv58_obligatoria" in selected[0][1]


def test_selection_covers_stratified_categories():
    selected = select_controlled_cases(_gold_records())
    union: set[str] = set()
    for _r, cats in selected:
        union.update(cats)
    for category in _CATEGORY_PRIORITY:
        assert category in union, f"categoría sin cubrir: {category}"


def test_coverage_of_conv58():
    records = _gold_records()
    rec58 = next(r for r in records if r["conversation_id"] == "CONV-00058")
    cats = coverage_of(rec58, 3, 8)
    assert {"conv58_obligatoria", "intencion_alta", "cuota_inicial_explicita",
            "objecion_explicita", "cita", "cambio_modelo"} <= cats


# --- Presupuesto y retries -----------------------------------------------------


def test_no_retry_on_429_and_budget_respected():
    selected = select_controlled_cases(_gold_records())
    extractor = FakeGroq(behaviors=[AIRequestError("HTTP 429: slow down")])
    outcome = _run(selected, extractor)
    assert extractor.calls == 10  # exactamente 1 request por conversación
    assert outcome["http_requests"] == 10
    assert outcome["http_requests"] <= 15
    assert outcome["count_rate_limited"] == 10
    assert outcome["stopped_early"] is False
    assert all(e["status"] == "rate_limited" for e in outcome["results"])
    assert all(e["http_status"] == 429 for e in outcome["results"])


def test_stops_immediately_on_daily_quota():
    selected = select_controlled_cases(_gold_records())
    extractor = FakeGroq(behaviors=[
        AIRequestError('HTTP 429: {"message": "Rate limit reached for requests per day. Remaining: 0"}')
    ])
    outcome = _run(selected, extractor)
    assert extractor.calls == 1
    assert outcome["stopped_early"] is True
    assert outcome["stop_reason"] == "cuota diaria/global agotada"
    assert len(outcome["results"]) == 1


def test_single_retry_on_5xx_then_success():
    selected = select_controlled_cases(_gold_records())[:1]
    extractor = FakeGroq(behaviors=[
        AIRequestError("HTTP 503: overloaded"),
        json.dumps({"model_interes": None}),
    ])
    outcome = _run(selected, extractor)
    assert extractor.calls == 2
    assert outcome["results"][0]["status"] == "ok"
    assert outcome["results"][0]["attempts"] == 2


def test_persistent_5xx_retries_once_then_error():
    selected = select_controlled_cases(_gold_records())[:1]
    extractor = FakeGroq(behaviors=[AIRequestError("HTTP 500: boom")])
    outcome = _run(selected, extractor)
    assert extractor.calls == 2
    assert outcome["results"][0]["status"] == "error"


def test_single_retry_on_timeout():
    selected = select_controlled_cases(_gold_records())[:1]
    extractor = FakeGroq(behaviors=[
        AIRequestError("network error: TimeoutError"),
        json.dumps({"model_interes": None}),
    ])
    outcome = _run(selected, extractor)
    assert extractor.calls == 2
    assert outcome["results"][0]["status"] == "ok"


def test_non_transient_400_no_retry():
    selected = select_controlled_cases(_gold_records())[:1]
    extractor = FakeGroq(behaviors=[AIRequestError("HTTP 400: bad request")])
    outcome = _run(selected, extractor)
    assert extractor.calls == 1
    assert outcome["results"][0]["status"] == "error"


def test_budget_cap_never_exceeded_with_retries():
    selected = select_controlled_cases(_gold_records())
    extractor = FakeGroq(behaviors=[AIRequestError("HTTP 503: busy")])
    outcome = run_groq_benchmark(extractor, selected, max_requests=5,
                                 delay_s=0, sleep_fn=lambda s: None)
    assert outcome["http_requests"] <= 5


# --- Clasificadores puros --------------------------------------------------------


def test_is_quota_exhausted():
    assert is_quota_exhausted("HTTP 429: daily limit exceeded") is True
    assert is_quota_exhausted("Rate limit reached for requests per day. Remaining: 0") is True
    assert is_quota_exhausted("quota exceeded for free-models-per-day") is True
    assert is_quota_exhausted("HTTP 429: slow down, retry soon") is False
    assert is_quota_exhausted(None) is False


def test_tpm_rate_limit_is_transient_not_quota():
    # 429 real observado: límite de tokens por minuto con "try again in 180ms".
    # No debe detener el benchmark, solo registrarse como rate_limited.
    message = ("HTTP 429: Rate limit reached for model `openai/gpt-oss-20b` "
               "on tokens per minute (TPM): Limit 8000, Used 5854. "
               "Please try again in 180ms.")
    assert is_quota_exhausted(message) is False
    assert is_rate_limit(message) is True


def test_transient_429_continues_with_remaining_conversations():
    selected = select_controlled_cases(_gold_records())[:3]
    transient = ("HTTP 429: Rate limit reached on tokens per minute (TPM). "
                 "Please try again in 180ms.")
    extractor = FakeGroq(behaviors=[
        json.dumps({"model_interes": None}),
        AIRequestError(transient),
        json.dumps({"model_interes": None}),
    ])
    outcome = _run(selected, extractor)
    assert extractor.calls == 3
    assert outcome["stopped_early"] is False
    assert [e["status"] for e in outcome["results"]] == ["ok", "rate_limited", "ok"]


def test_rate_limit_timeout_server_classifiers():
    assert is_rate_limit("HTTP 429: x") is True
    assert is_rate_limit("HTTP 500: x") is False
    assert is_timeout("network error: TimeoutError") is True
    assert is_timeout("HTTP 500: x") is False
    assert is_server_error("HTTP 503: x") is True
    assert is_server_error("HTTP 400: x") is False


def test_pick_rate_limit_headers_never_leaks_secrets():
    headers = {"authorization": "Bearer SECRET", "api-key": "x", "retry-after": "3",
               "x-ratelimit-remaining": "0", "content-type": "application/json"}
    picked = pick_rate_limit_headers(headers)
    assert picked == {"retry-after": "3", "x-ratelimit-remaining": "0"}
    assert "SECRET" not in json.dumps(picked)


# --- Métricas y reporte ------------------------------------------------------------


def test_metrics_use_same_definitions():
    selected = select_controlled_cases(_gold_records())[:3]
    extractor = FakeGroq(behaviors=[json.dumps({"model_interes": None})])
    outcome = _run(selected, extractor)
    assert outcome["graded"] == 3
    assert outcome["decisions"] == 3 * 8
    assert outcome["tp"] + outcome["fp"] + outcome["fn"] + outcome["tn"] == outcome["decisions"]
    assert set(outcome["metrics"].keys()) == {
        "model_interes", "intencion_compra", "forma_pago", "objecion",
        "presupuesto", "cuota_inicial", "solicitud_cita", "solicitud_cotizacion"}


def test_per_conversation_table_aligns_by_id():
    records = _gold_records()
    selected = select_controlled_cases(records)[:3]
    transient = "HTTP 429: slow down"
    extractor = FakeGroq(behaviors=[
        json.dumps({"model_interes": None}),
        AIRequestError(transient),
        json.dumps({"model_interes": None}),
    ])
    outcome = _run(selected, extractor)
    report = build_report("openai/gpt-oss-20b", len(records), selected, outcome,
                          max_requests=15, timeout_s=120.0, delay_s=1.0)
    md = _render_markdown(report)
    conv_rl = selected[1][0]["conversation_id"]
    for line in md.splitlines():
        if line.startswith(f"| {conv_rl} |"):
            assert "rate_limited" in line
            assert line.rstrip().endswith("| - |"), line
            break
    else:
        raise AssertionError("fila rate_limited no encontrada en el reporte")


def test_report_and_markdown_sections_without_secrets(tmp_path):
    records = _gold_records()
    selected = select_controlled_cases(records)
    extractor = FakeGroq(behaviors=[AIRequestError("HTTP 429: slow down")])
    outcome = _run(selected, extractor)
    report = build_report("openai/gpt-oss-20b", len(records), selected, outcome,
                          max_requests=15, timeout_s=120.0, delay_s=1.0)
    assert report["conv_00058"]["found_in_gold"] is True
    assert len(report["conv_00058"]["comparison"]) == 8

    json_path = tmp_path / "rep.json"
    md_path = tmp_path / "rep.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = _render_markdown(report)
    md_path.write_text(md, encoding="utf-8")

    for section in ("## Executive summary", "## Results", "## Per-conversation results",
                    "## Error analysis", "## CONV-00058", "## Comparison",
                    "## Engineering interpretation"):
        assert section in md, f"falta sección: {section}"
    assert "GROQ_API_KEY" not in json_path.read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in md
    assert "Bearer" not in md
