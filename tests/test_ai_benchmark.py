from __future__ import annotations

import json

from app.ai.base import ExtractionOutcome
from app.ai.benchmark import load_conversations, run_benchmark, select_cases, write_reports
from app.ai.schema import ExtractionResult


class FakeExtractor:
    def __init__(self, provider="fake", model="fake-1", available=True):
        self.provider = provider
        self.model = model
        self._available = available

    def availability(self) -> tuple[bool, str]:
        return (True, "ok") if self._available else (False, "not configured")

    def extract(self, conversation) -> ExtractionOutcome:
        result = ExtractionResult(
            model_interes="XRE",
            model_interes_evidence="me interesa la XRE",
            solicitud_cotizacion=True,
            solicitud_cotizacion_evidence="me la cotiza",
        )
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=True,
            latency_ms=12,
            result=result,
        )


class FailingExtractor:
    provider = "fake-fail"
    model = "fake-fail-1"

    def availability(self) -> tuple[bool, str]:
        return True, "ok"

    def extract(self, conversation) -> ExtractionOutcome:
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=self.provider,
            model=self.model,
            success=True,
            schema_valid=False,
            latency_ms=7,
            error="schema validation failed: 1 error(s)",
            raw_text='{"objecion": true}',
        )


def test_select_cases_is_deterministic_and_covers_labels():
    conversations = load_conversations()
    first = select_cases(conversations)
    second = select_cases(conversations)

    assert len(first) == 10
    ids = [case["conversation_id"] for case in first]
    assert len(set(ids)) == 10
    assert ids == [case["conversation_id"] for case in second]

    labels = {case["case"] for case in first}
    assert {
        "modelo_claro",
        "presupuesto",
        "financiacion",
        "solicitud_cita",
        "objecion",
        "ambigua",
        "poca_evidencia",
    } <= labels
    assert all(isinstance(case["message_count"], int) for case in first)


def test_run_benchmark_with_fake_extractor():
    cases = select_cases(load_conversations())
    report = run_benchmark([FakeExtractor()], cases)

    entry = report["providers"]["fake"]
    assert entry["available"] is True
    assert entry["metrics"]["requests"] == 10
    assert entry["metrics"]["schema_valid_rate"] == 1.0
    assert entry["metrics"]["fields_extracted"] == 20
    assert entry["metrics"]["fields_with_evidence"] == 20
    assert entry["metrics"]["evidence_rate"] == 1.0
    assert entry["results"][0]["raw_text"] is None


def test_run_benchmark_keeps_raw_text_for_schema_failures():
    cases = select_cases(load_conversations())
    report = run_benchmark([FailingExtractor()], cases)

    entry = report["providers"]["fake-fail"]
    assert entry["metrics"]["schema_valid_rate"] == 0.0
    assert entry["results"][0]["raw_text"] == '{"objecion": true}'
    assert entry["results"][0]["error"] == "schema validation failed: 1 error(s)"


def test_run_benchmark_unavailable_provider_is_omitted():
    cases = select_cases(load_conversations())
    report = run_benchmark([FakeExtractor(available=False)], cases)

    entry = report["providers"]["fake"]
    assert entry["available"] is False
    assert entry["availability_reason"] == "not configured"
    assert entry["results"] == []
    assert entry["metrics"]["requests"] == 0


def test_write_reports(tmp_path):
    cases = select_cases(load_conversations())
    report = run_benchmark([FakeExtractor()], cases)

    json_path, md_path = write_reports(report, reports_dir=tmp_path)

    assert json_path.exists() and md_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "v1"
    assert "fake" in loaded["providers"]
    assert "Manual review" in md_path.read_text(encoding="utf-8")
