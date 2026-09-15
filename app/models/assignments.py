from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import BigIntType

if TYPE_CHECKING:
    from app.models.advisors import Advisor
    from app.models.leads import Lead
    from app.models.organization import Company, PointOfSale
    from app.models.pipeline import PipelineRun


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        # Defensa de BD: la asignación respeta empresa ↔ POS ↔ asesor.
        sa.ForeignKeyConstraint(
            ["company_id", "point_of_sale_id"],
            ["points_of_sale.company_id", "points_of_sale.point_of_sale_id"],
            name="fk_assignments_company_pos",
        ),
        sa.ForeignKeyConstraint(
            ["advisor_id", "company_id", "point_of_sale_id"],
            ["advisors.advisor_id", "advisors.company_id", "advisors.point_of_sale_id"],
            name="fk_assignments_advisor_org",
        ),
    )

    assignment_id: Mapped[int] = mapped_column(
        BigIntType, primary_key=True, autoincrement=True
    )
    lead_id: Mapped[str] = mapped_column(
        sa.ForeignKey("leads.lead_id", ondelete="CASCADE"), nullable=False, index=True
    )
    advisor_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("advisors.advisor_id"), nullable=True, index=True
    )
    company_id: Mapped[str] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=False, index=True
    )
    point_of_sale_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("points_of_sale.point_of_sale_id"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True
    )
    run_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    strategy_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    priority_rank: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="assignments")
    advisor: Mapped["Advisor | None"] = relationship(
        back_populates="assignments", foreign_keys=[advisor_id]
    )
    company: Mapped["Company"] = relationship()
    point_of_sale: Mapped["PointOfSale | None"] = relationship(
        foreign_keys=[point_of_sale_id]
    )
    run: Mapped["PipelineRun | None"] = relationship()
