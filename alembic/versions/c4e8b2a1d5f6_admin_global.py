"""admin global: company_id nullable + rol admin.

El admin no pertenece a ninguna empresa (company_id NULL). Asesores y
supervisores siguen exigiendo company_id a nivel de aplicación.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4e8b2a1d5f6"
down_revision = "7c1d9a2b4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("company_id", existing_type=sa.Text(), nullable=True)
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role",
            "role IN ('admin_empresa', 'supervisor', 'asesor', 'admin')",
        )


def downgrade() -> None:
    # Los admins globales no tienen representación previa: se eliminan sus
    # filas antes de restaurar NOT NULL (solo uso en desarrollo).
    op.execute("DELETE FROM users WHERE role = 'admin'")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role",
            "role IN ('admin_empresa', 'supervisor', 'asesor')",
        )
        batch_op.alter_column("company_id", existing_type=sa.Text(), nullable=False)
