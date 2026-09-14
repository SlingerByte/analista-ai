from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Conversation, IdentityMember


def cluster_conversations(session: Session, cluster_id: int) -> list[Conversation]:
    """Conversations of every lead in a cluster, ordered chronologically.

    Keeps each conversation separate; this is the input for the future AI
    extraction phase (no physical merge of messages).
    """
    lead_ids = sa.select(IdentityMember.lead_id).where(
        IdentityMember.cluster_id == cluster_id
    )
    statement = (
        sa.select(Conversation)
        .where(Conversation.lead_id.in_(lead_ids))
        .order_by(
            Conversation.started_at.is_(None),
            Conversation.started_at,
            Conversation.conversation_id,
        )
    )
    return list(session.scalars(statement).all())
