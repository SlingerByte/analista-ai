from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import JSONType

if TYPE_CHECKING:
    from app.models.assignments import Assignment
    from app.models.catalog import CatalogItem
    from app.models.conversations import Conversation
    from app.models.identity import IdentityMember
    from app.models.organization import Company, PointOfSale
    from app.models.scoring import LeadScore


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        # Defensa de BD: el punto de venta debe pertenecer a la misma empresa.
        sa.ForeignKeyConstraint(
            ["company_id", "point_of_sale_id"],
            ["points_of_sale.company_id", "points_of_sale.point_of_sale_id"],
            name="fk_leads_company_pos",
        ),
    )

    lead_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=False, index=True
    )
    point_of_sale_id: Mapped[str] = mapped_column(
        sa.ForeignKey("points_of_sale.point_of_sale_id"), nullable=False, index=True
    )

    channel: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    customer_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    phone_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    phone_normalized: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    email_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)
    city_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    city_normalized: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)

    model_text_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(
        sa.ForeignKey("catalog_items.sku"), nullable=True, index=True
    )

    registration_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    first_contact_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    campaign: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    raw_payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    normalization_meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    record_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    content_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)

    first_seen_run: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True
    )
    last_seen_run: Mapped[int | None] = mapped_column(
        sa.ForeignKey("pipeline_runs.run_id"), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true(), index=True
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

    company: Mapped["Company"] = relationship(back_populates="leads")
    point_of_sale: Mapped["PointOfSale"] = relationship(
        back_populates="leads", foreign_keys=[point_of_sale_id]
    )
    catalog_item: Mapped["CatalogItem | None"] = relationship(back_populates="leads")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="lead")
    identity_member: Mapped["IdentityMember | None"] = relationship(
        back_populates="lead", uselist=False
    )
    scores: Mapped[list["LeadScore"]] = relationship(back_populates="lead")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="lead")
