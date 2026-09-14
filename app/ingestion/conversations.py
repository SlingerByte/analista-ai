from __future__ import annotations

from collections import Counter
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ingestion import loaders
from app.ingestion.normalizers import (
    classify_date,
    normalize_canal,
    normalize_messages,
    normalized_date_value,
    pick,
)
from app.models import Conversation, Lead

CONVERSATION_ID_KEYS = ["conversacion_id", "conversation_id", "id"]
LEAD_ID_KEYS = ["lead_id", "lead", "id_lead"]
CHANNEL_KEYS = ["canal", "channel"]
STARTED_AT_KEYS = ["fecha_inicio", "started_at", "fecha", "date"]
MESSAGES_KEYS = ["mensajes", "messages"]


def ingest_conversations(session: Session, run_id: int, data_dir: Path) -> dict:
    data = loaders.read_json(data_dir / loaders.CONVERSATIONS_FILE)
    if not isinstance(data, list):
        data = []

    lead_company = dict(
        session.execute(sa.select(Lead.lead_id, Lead.company_id)).all()
    )

    inserted = updated = unchanged = 0
    linked = 0
    orphans: list[dict] = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    per_lead: Counter[str] = Counter()

    for raw in data:
        if not isinstance(raw, dict):
            continue
        conversation_id = pick(raw, CONVERSATION_ID_KEYS)
        if not conversation_id:
            continue
        conversation_id = str(conversation_id)

        if conversation_id in seen_ids:
            duplicate_ids.append(conversation_id)
        seen_ids.add(conversation_id)

        source_lead_id = pick(raw, LEAD_ID_KEYS)
        channel = normalize_canal(pick(raw, CHANNEL_KEYS))
        started_info = classify_date(pick(raw, STARTED_AT_KEYS))
        started_at = normalized_date_value(started_info)
        messages = normalize_messages(pick(raw, MESSAGES_KEYS))

        if source_lead_id in lead_company:
            lead_id = source_lead_id
            company_id = lead_company[source_lead_id]
            status = "linked"
            linked += 1
            per_lead[source_lead_id] += 1
        else:
            lead_id = None
            company_id = None
            status = "orphan"
            orphans.append(
                {"conversation_id": conversation_id, "source_lead_id": source_lead_id}
            )

        content_hash = loaders.sha256_of(
            {
                "conversation_id": conversation_id,
                "source_lead_id": source_lead_id,
                "channel": channel,
                "started_at": started_at.isoformat() if started_at else None,
                "messages": messages,
            }
        )

        existing = session.get(Conversation, conversation_id)
        if existing is None:
            session.add(
                Conversation(
                    conversation_id=conversation_id,
                    lead_id=lead_id,
                    company_id=company_id,
                    channel=channel,
                    started_at=started_at,
                    content_hash=content_hash,
                    status=status,
                    messages=messages,
                    first_seen_run=run_id,
                    last_seen_run=run_id,
                )
            )
            inserted += 1
        elif existing.content_hash == content_hash:
            existing.last_seen_run = run_id
            unchanged += 1
        else:
            existing.lead_id = lead_id
            existing.company_id = company_id
            existing.channel = channel
            existing.started_at = started_at
            existing.content_hash = content_hash
            existing.status = status
            existing.messages = messages
            existing.last_seen_run = run_id
            updated += 1

    multiple = sum(1 for count in per_lead.values() if count > 1)

    return {
        "read": len(data),
        "linked": linked,
        "orphan": len(orphans),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "duplicate_conversation_ids": duplicate_ids,
        "multiple_conversations_per_lead": multiple,
        "orphans": orphans,
    }
