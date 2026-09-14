from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from app.ai.schema import ConversationInput, ExtractionResult


class AIRequestError(RuntimeError):
    """Transport/HTTP error talking to a provider (never contains credentials)."""


@dataclass
class ExtractionOutcome:
    conversation_id: str
    provider: str
    model: str | None
    success: bool
    schema_valid: bool
    latency_ms: int
    result: ExtractionResult | None = None
    error: str | None = None
    raw_text: str | None = None


@runtime_checkable
class AIExtractor(Protocol):
    provider: str
    model: str | None

    def availability(self) -> tuple[bool, str]:
        ...

    def extract(self, conversation: ConversationInput) -> ExtractionOutcome:
        ...


def _validate_content(
    conversation: ConversationInput,
    content: str | None,
    latency_ms: int,
    provider: str,
    model: str | None,
) -> ExtractionOutcome:
    text = content or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=provider,
            model=model,
            success=False,
            schema_valid=False,
            latency_ms=latency_ms,
            error=f"invalid JSON: {exc.msg}",
            raw_text=text[:500],
        )

    try:
        result = ExtractionResult.model_validate(data)
    except ValidationError as exc:
        return ExtractionOutcome(
            conversation_id=conversation.conversation_id,
            provider=provider,
            model=model,
            success=True,
            schema_valid=False,
            latency_ms=latency_ms,
            error=f"schema validation failed: {exc.error_count()} error(s)",
            raw_text=text[:500],
        )

    return ExtractionOutcome(
        conversation_id=conversation.conversation_id,
        provider=provider,
        model=model,
        success=True,
        schema_valid=True,
        latency_ms=latency_ms,
        result=result,
    )


class BaseHTTPExtractor:
    provider = "base"

    def __init__(self, model: str | None, timeout: float) -> None:
        self.model = model
        self.timeout = timeout

    def availability(self) -> tuple[bool, str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _call(self, conversation: ConversationInput) -> str:  # pragma: no cover
        raise NotImplementedError

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                detail = ""
            raise AIRequestError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIRequestError(f"network error: {type(exc).__name__}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise AIRequestError(f"invalid JSON response: {exc.msg}") from exc

    def extract(self, conversation: ConversationInput) -> ExtractionOutcome:
        started = time.perf_counter()
        try:
            content = self._call(conversation)
        except AIRequestError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ExtractionOutcome(
                conversation_id=conversation.conversation_id,
                provider=self.provider,
                model=self.model,
                success=False,
                schema_valid=False,
                latency_ms=latency_ms,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ExtractionOutcome(
                conversation_id=conversation.conversation_id,
                provider=self.provider,
                model=self.model,
                success=False,
                schema_valid=False,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return _validate_content(conversation, content, latency_ms, self.provider, self.model)
