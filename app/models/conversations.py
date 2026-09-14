from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import JSONType

if TYPE_CHECKING:
    from app.models.ai import AIExtraction
    from app.models.leads import Lead
    from app.models.organization import Company


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    lead_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("leads.lead_id"), nullable=True, index=True
    )
    company_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=True, index=True
    )
    channel: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    content_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="linked", index=True)
    messages: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    first_seen_run: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True
    )
    last_seen_run: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    lead: Mapped["Lead | None"] = relationship(back_populates="conversations")
    company: Mapped["Company | None"] = relationship()
    extractions: Mapped[list["AIExtraction"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
