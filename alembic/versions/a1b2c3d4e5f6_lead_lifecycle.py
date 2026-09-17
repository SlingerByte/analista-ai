"""ciclo de vida del lead: campos de cierre.

Agrega ``leads.closed_at`` y ``leads.close_reason`` (nullable). No modifica
datos existentes ni convierte estados: los leads actuales conservan su estado.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "b7d2e4f6a8c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("close_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_column("close_reason")
        batch_op.drop_column("closed_at")
