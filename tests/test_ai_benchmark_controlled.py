from __future__ import annotations

from scripts.run_ai_benchmark_openrouter_controlled import (
    backoff_for_retry,
    classify_error,
    extract_http_status,
    parse_retry_delays,
)


def test_parse_retry_delays():
    assert parse_retry_delays("5,15") == [5.0, 15.0]


def test_extract_http_status():
    assert extract_http_status("HTTP 429: too many") == 429
    assert extract_http_status("network error: TimeoutError") is None


def test_classify_error():
    assert classify_error("HTTP 429: slow down") == "rate_limited"
    assert classify_error("network error: TimeoutError") == "timeout"
    assert classify_error("HTTP 500: boom") == "error"


def test_backoff_for_retry():
    assert backoff_for_retry(0, [5.0, 15.0]) == 5.0
    assert backoff_for_retry(1, [5.0, 15.0]) == 15.0
    assert backoff_for_retry(5, [5.0, 15.0]) == 15.0
