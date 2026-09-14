"""ai extraction traceability: lead_id + error.

Agrega foto del lead al momento de extraer (nullable: huérfanas sin lead)
e información de error sanitizada (status "success" | "error").
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c1d9a2b4e5f"
down_revision = "3f0f52dc8084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_extractions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lead_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_extractions_lead_id",
            "leads",
            ["lead_id"],
            ["lead_id"],
            ondelete="CASCADE",
        )
    op.create_index(
        op.f("ix_ai_extractions_lead_id"), "ai_extractions", ["lead_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_extractions_lead_id"), table_name="ai_extractions")
    with op.batch_alter_table("ai_extractions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_ai_extractions_lead_id", type_="foreignkey")
        batch_op.drop_column("lead_id")
        batch_op.drop_column("error")
