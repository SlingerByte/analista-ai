from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import JSONType

if TYPE_CHECKING:
    from app.models.leads import Lead


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    sku: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    brand: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    line: Mapped[str] = mapped_column(sa.Text, nullable=False)
    engine_cc: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    segment: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    list_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), nullable=False)
    availability: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    leads: Mapped[list["Lead"]] = relationship(back_populates="catalog_item")
