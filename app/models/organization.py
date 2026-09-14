from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import BigIntType

if TYPE_CHECKING:
    from app.models.advisors import Advisor
    from app.models.leads import Lead


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    points_of_sale: Mapped[list["PointOfSale"]] = relationship(back_populates="company")
    users: Mapped[list["User"]] = relationship(back_populates="company")
    advisors: Mapped[list["Advisor"]] = relationship(back_populates="company")
    leads: Mapped[list["Lead"]] = relationship(back_populates="company")


class PointOfSale(Base):
    __tablename__ = "points_of_sale"

    point_of_sale_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    company_id: Mapped[str] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    company: Mapped["Company"] = relationship(back_populates="points_of_sale")
    advisors: Mapped[list["Advisor"]] = relationship(back_populates="point_of_sale")
    leads: Mapped[list["Lead"]] = relationship(back_populates="point_of_sale")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('admin_empresa', 'supervisor', 'asesor', 'admin')",
            name="ck_users_role",
        ),
    )

    user_id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    # Nullable: el admin global no pertenece a ninguna empresa. Asesores y
    # supervisores siempre tienen company_id (la app lo exige).
    company_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("companies.company_id"), nullable=True, index=True
    )
    advisor_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("advisors.advisor_id"), nullable=True
    )
    email: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    company: Mapped["Company | None"] = relationship(back_populates="users")
    advisor: Mapped["Advisor | None"] = relationship(back_populates="users")
