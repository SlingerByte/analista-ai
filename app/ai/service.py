"""Persistencia productiva de extracciones IA.

Flujo por conversación::

    Conversation → conversation_to_input → AIExtractor → ExtractionResult
        → AIExtraction (status "success" | "error")

Idempotencia: se reutiliza la extracción si ya existe una fila exitosa con el
mismo ``(conversation_id, input_hash, provider, model)``. El ``input_hash``
cubre transcript + prompt_version + schema_version (technical-design §9.4),
así que un cambio de contenido o de versiones genera una fila nueva y la
anterior queda con ``is_current = false`` (trazabilidad, no borrado).

No contiene lógica de scoring. Sin colas ni workers: procesamiento secuencial.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.base import AIExtractor
from app.ai.prompt import EXTRACTION_PROMPT_VERSION
from app.ai.schema import SCHEMA_VERSION, ConversationInput, ExtractionResult, Message
from app.ai.validation import split_transcript_messages, validate_extraction
from app.ingestion.loaders import sha256_of
from app.models import AIExtraction, Conversation

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ProcessResult:
    conversation_id: str
    lead_id: str | None
    reused: bool
    extraction: AIExtraction


def build_transcript(messages: list[dict]) -> str:
    """Transcript ``sender: texto`` con el mismo formato del benchmark."""
    lines = []
    for message in messages:
        sender = str(message.get("sender") or "").strip()
        text = str(message.get("text") or "").strip()
        if text:
            lines.append(f"{sender}: {text}")
    return "\n".join(lines)


def compute_input_hash(transcript: str, prompt_version: str, schema_version: str) -> str:
    """Hash del input efectivo. Cambia si cambia el contenido o las versiones."""
    return sha256_of(
        {
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "transcript": transcript,
        }
    )


def conversation_to_input(conversation: Conversation) -> ConversationInput:
    return ConversationInput(
        conversation_id=conversation.conversation_id,
        lead_id=conversation.lead_id,
        channel=conversation.channel,
        messages=[
            Message(
                sender=str(item.get("sender") or ""),
                text=str(item.get("text") or ""),
                hour=str(item.get("hour") or "") or None,
            )
            for item in (conversation.messages or [])
            if str(item.get("text") or "").strip()
        ],
    )


def _mark_current(session: Session, conversation_id: str, keep_id: int) -> None:
    session.execute(
        sa.update(AIExtraction)
        .where(
            AIExtraction.conversation_id == conversation_id,
            AIExtraction.extraction_id != keep_id,
        )
        .values(is_current=False)
    )


def _find_same_input(
    session: Session,
    conversation_id: str,
    input_hash: str,
    extractor: AIExtractor,
) -> AIExtraction | None:
    """Fila del mismo input efectivo (cualquier estado), para `force`."""
    return session.scalar(
        sa.select(AIExtraction)
        .where(
            AIExtraction.conversation_id == conversation_id,
            AIExtraction.input_hash == input_hash,
            AIExtraction.provider == extractor.provider,
            AIExtraction.model_name == extractor.model,
        )
        .order_by(AIExtraction.extraction_id.desc())
    )


def _find_reusable(
    session: Session,
    conversation_id: str,
    input_hash: str,
    extractor: AIExtractor,
) -> AIExtraction | None:
    return session.scalar(
        sa.select(AIExtraction)
        .where(
            AIExtraction.conversation_id == conversation_id,
            AIExtraction.input_hash == input_hash,
            AIExtraction.provider == extractor.provider,
            AIExtraction.model_name == extractor.model,
            AIExtraction.status == STATUS_SUCCESS,
        )
        .order_by(AIExtraction.extraction_id.desc())
    )


def _validated_fields(conversation: Conversation, result: ExtractionResult) -> dict:
    """Aplica la validación determinista y devuelve los `fields` a persistir."""
    client_messages, advisor_messages = split_transcript_messages(
        conversation.messages or []
    )
    validation = validate_extraction(result, client_messages, advisor_messages)
    fields = validation.extraction.model_dump()
    if validation.invalidated:
        fields["validation"] = {
            "invalidated": validation.invalidated,
            "validated": list(validation.validated),
        }
    return fields


def _revalidate_reused(
    conversation: Conversation, extraction: AIExtraction
) -> dict | None:
    """Revalida una extracción reutilizada. None si `fields` no es reconstruible."""
    if not isinstance(extraction.fields, dict):
        return None
    try:
        result = ExtractionResult.model_validate(extraction.fields)
    except ValidationError:
        return None
    return _validated_fields(conversation, result)


def process_conversation(
    session: Session,
    conversation_id: str,
    extractor: AIExtractor,
    *,
    force: bool = False,
) -> ProcessResult:
    """Procesa una conversación de forma idempotente. Siempre hace commit."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError(f"conversation not found: {conversation_id}")

    conversation_input = conversation_to_input(conversation)
    transcript = build_transcript(conversation.messages or [])
    input_hash = compute_input_hash(
        transcript, EXTRACTION_PROMPT_VERSION, SCHEMA_VERSION
    )

    reusable: AIExtraction | None = None
    if not force:
        reusable = _find_reusable(session, conversation_id, input_hash, extractor)
        if reusable is not None:
            # Ninguna reutilización se salta la validación: una fila legacy
            # (previa a la validación) se revalida y se corrige en su lugar.
            revalidated = _revalidate_reused(conversation, reusable)
            if revalidated is not None:
                if reusable.fields != revalidated:
                    reusable.fields = revalidated
                    session.flush()
                reusable.is_current = True
                _mark_current(session, conversation_id, reusable.extraction_id)
                session.commit()
                return ProcessResult(
                    conversation_id=conversation_id,
                    lead_id=conversation.lead_id,
                    reused=True,
                    extraction=reusable,
                )

    outcome = extractor.extract(conversation_input)

    if outcome.success and outcome.schema_valid and outcome.result is not None:
        status, error = STATUS_SUCCESS, None
        # Validación determinista: solo sobrevive lo que tenga evidencia del
        # cliente. Sin esto, una alucinación del modelo llegaría al scoring.
        fields = _validated_fields(conversation, outcome.result)
        raw_response = None
    else:
        # Error controlado: se persiste el motivo (sanitizado, sin secretos)
        # y la conversación queda identificable para reproceso posterior.
        status = STATUS_ERROR
        error = (outcome.error or "unknown extraction failure")[:500]
        fields = None
        raw_response = {"raw_text": outcome.raw_text} if outcome.raw_text else None

    # Solo una extracción exitosa es "funcional" (is_current). Un intento
    # fallido se registra para trazabilidad pero NO desplaza a una success
    # previa: si la reextracción falla, el scoring conserva las señales buenas.
    make_current = status == STATUS_SUCCESS

    if force:
        # El unique (conversation_id, input_hash) impide duplicar el mismo
        # input efectivo: `force` actualiza la fila existente en vez de
        # insertar (útil tras un error transitorio del proveedor).
        same = _find_same_input(session, conversation_id, input_hash, extractor)
        if same is not None:
            same.lead_id = conversation.lead_id
            same.status = status
            same.error = error
            same.fields = fields
            same.raw_response = raw_response
            same.latency_ms = outcome.latency_ms
            same.is_current = make_current
            extraction = same
            session.flush()
            if make_current:
                _mark_current(session, conversation_id, extraction.extraction_id)
            session.commit()
            return ProcessResult(
                conversation_id=conversation_id,
                lead_id=conversation.lead_id,
                reused=False,
                extraction=extraction,
            )

    if reusable is not None:
        # `fields` no reconstruible: se reextrae y se actualiza la misma fila
        # para respetar el unique (conversation_id, input_hash).
        reusable.lead_id = conversation.lead_id
        reusable.status = status
        reusable.error = error
        reusable.fields = fields
        reusable.raw_response = raw_response
        reusable.latency_ms = outcome.latency_ms
        reusable.is_current = make_current
        session.flush()
        if make_current:
            _mark_current(session, conversation_id, reusable.extraction_id)
        session.commit()
        return ProcessResult(
            conversation_id=conversation_id,
            lead_id=conversation.lead_id,
            reused=False,
            extraction=reusable,
        )

    extraction = AIExtraction(
        conversation_id=conversation_id,
        lead_id=conversation.lead_id,
        provider=extractor.provider,
        model_name=extractor.model,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status=status,
        error=error,
        input_hash=input_hash,
        fields=fields,
        raw_response=raw_response,
        latency_ms=outcome.latency_ms,
        is_current=make_current,
    )

    session.add(extraction)
    session.flush()
    if make_current:
        _mark_current(session, conversation_id, extraction.extraction_id)
    session.commit()
    return ProcessResult(
        conversation_id=conversation_id,
        lead_id=conversation.lead_id,
        reused=False,
        extraction=extraction,
    )


def process_pending(
    session: Session,
    extractor: AIExtractor,
    *,
    limit: int = 50,
    conversation_ids: list[str] | None = None,
) -> dict:
    """Procesa secuencialmente. Un fallo inesperado no rompe el lote."""
    query = sa.select(Conversation.conversation_id).order_by(Conversation.conversation_id)
    if conversation_ids is not None:
        query = query.where(Conversation.conversation_id.in_(conversation_ids))
    if limit is not None:
        query = query.limit(limit)
    ids = list(session.scalars(query).all())

    processed = reused = errors = failed = 0
    processed_ids: list[str] = []
    failures: list[dict] = []
    for conversation_id in ids:
        try:
            result = process_conversation(session, conversation_id, extractor)
        except Exception as exc:  # noqa: BLE001 - el lote debe continuar
            session.rollback()
            failed += 1
            failures.append({"conversation_id": conversation_id, "error": str(exc)[:300]})
            continue
        processed += 1
        if result.extraction.status == STATUS_SUCCESS:
            # Solo las extracciones exitosas (nuevas o reutilizadas) alimentan
            # el rescoring; un intento fallido no debe disparar recálculo.
            processed_ids.append(conversation_id)
        if result.reused:
            reused += 1
        elif result.extraction.status == STATUS_ERROR:
            errors += 1

    return {
        "provider": extractor.provider,
        "model": extractor.model,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "candidates": len(ids),
        "processed": processed,
        "reused": reused,
        "errors": errors,
        "failed": failed,
        "failures": failures,
        # Aditivo: conversaciones con extracción exitosa (nuevas o reutilizadas).
        "processed_ids": processed_ids,
    }


def get_current_extraction(
    session: Session, conversation_id: str
) -> AIExtraction | None:
    """Última extracción vigente de una conversación (punto de integración)."""
    return session.scalar(
        sa.select(AIExtraction)
        .where(
            AIExtraction.conversation_id == conversation_id,
            AIExtraction.is_current.is_(True),
            AIExtraction.status == STATUS_SUCCESS,
        )
        .order_by(AIExtraction.extraction_id.desc())
    )


def lead_extractions(session: Session, lead_id: str) -> list[AIExtraction]:
    """Extracciones vigentes de todas las conversaciones de un lead.

    La consolidación por lead es responsabilidad posterior; aquí solo se
    agrupan filas por conversación (un lead puede tener 0, 1 o varias).
    """
    return list(
        session.scalars(
            sa.select(AIExtraction)
            .join(
                Conversation,
                Conversation.conversation_id == AIExtraction.conversation_id,
            )
            .where(
                Conversation.lead_id == lead_id,
                AIExtraction.is_current.is_(True),
                AIExtraction.status == STATUS_SUCCESS,
            )
            .order_by(AIExtraction.extraction_id)
        ).all()
    )
