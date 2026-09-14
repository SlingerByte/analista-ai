from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import BigIntType, JSONType

if TYPE_CHECKING:
    from app.models.conversations import Conversation


class AIExtraction(Base):
    __tablename__ = "ai_extractions"
    __table_args__ = (
        sa.UniqueConstraint(
            "conversation_id", "input_hash", name="uq_ai_extractions_conversation_input"
        ),
    )

    extraction_id: Mapped[int] = mapped_column(
        BigIntType, primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[str] = mapped_column(
        sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Foto del lead al momento de extraer. Nullable: las conversaciones
    # huérfanas no tienen lead y no se inventa ninguno (ver service.py).
    lead_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    # Solo "success" | "error". En "error" guarda el motivo sanitizado
    # (nunca secretos: AIRequestError no incluye credenciales por diseño).
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    input_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    fields: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="extractions")
