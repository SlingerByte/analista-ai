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
    from app.models.organization import Company, User


class IdentityCluster(Base):
    __tablename__ = "identity_clusters"

    cluster_id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=False, index=True
    )
    canonical_lead_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("leads.lead_id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    match_strength: Mapped[str] = mapped_column(sa.Text, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3), nullable=True)
    matched_rules: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.user_id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship()
    canonical_lead: Mapped["Lead | None"] = relationship(
        foreign_keys=[canonical_lead_id]
    )
    decided_by_user: Mapped["User | None"] = relationship()
    members: Mapped[list["IdentityMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class IdentityMember(Base):
    __tablename__ = "identity_members"
    __table_args__ = (
        sa.UniqueConstraint("cluster_id", "lead_id", name="uq_identity_members_cluster_lead"),
    )

    id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(
        sa.ForeignKey("identity_clusters.cluster_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[str] = mapped_column(
        sa.ForeignKey("leads.lead_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    match_strength: Mapped[str] = mapped_column(sa.Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    cluster: Mapped["IdentityCluster"] = relationship(back_populates="members")
    lead: Mapped["Lead"] = relationship(back_populates="identity_member")
