from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import JSONType

if TYPE_CHECKING:
    from app.models.assignments import Assignment
    from app.models.organization import Company, PointOfSale, User


class Advisor(Base):
    __tablename__ = "advisors"

    advisor_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=False, index=True
    )
    point_of_sale_id: Mapped[str] = mapped_column(
        sa.ForeignKey("points_of_sale.point_of_sale_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    daily_capacity: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true(), index=True
    )
    start_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    raw_fields: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship(back_populates="advisors")
    point_of_sale: Mapped["PointOfSale"] = relationship(back_populates="advisors")
    users: Mapped[list["User"]] = relationship(back_populates="advisor")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="advisor")
