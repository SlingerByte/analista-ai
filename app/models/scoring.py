from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import BigIntType, JSONType

if TYPE_CHECKING:
    from app.models.leads import Lead
    from app.models.pipeline import PipelineRun


class LeadScore(Base):
    __tablename__ = "lead_scores"

    score_id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    lead_id: Mapped[str] = mapped_column(
        sa.ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True, index=True
    )
    score_version: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    priority_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 2), nullable=True)
    urgency_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 2), nullable=True)
    queue_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 2), nullable=True)
    band: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    reasons: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    params_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true(), index=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="scores")
    run: Mapped["PipelineRun | None"] = relationship()
