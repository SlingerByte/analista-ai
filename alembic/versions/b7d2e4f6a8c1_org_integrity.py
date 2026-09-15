"""integridad empresa → punto de venta → asesor → asignación.

Agrega constraints compuestos para impedir combinaciones incoherentes entre
empresa y punto de venta, y entre asignación y asesor. El punto de venta pasa
a ser único por (empresa, POS) para poder ser referenciado por FKs compuestas.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d2e4f6a8c1"
down_revision = "c4e8b2a1d5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("points_of_sale", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_points_of_sale_company_pos", ["company_id", "point_of_sale_id"]
        )

    with op.batch_alter_table("advisors", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_advisors_id_company_pos",
            ["advisor_id", "company_id", "point_of_sale_id"],
        )
        batch_op.create_foreign_key(
            "fk_advisors_company_pos",
            "points_of_sale",
            ["company_id", "point_of_sale_id"],
            ["company_id", "point_of_sale_id"],
        )

    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_leads_company_pos",
            "points_of_sale",
            ["company_id", "point_of_sale_id"],
            ["company_id", "point_of_sale_id"],
        )

    with op.batch_alter_table("assignments", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_assignments_company_pos",
            "points_of_sale",
            ["company_id", "point_of_sale_id"],
            ["company_id", "point_of_sale_id"],
        )
        batch_op.create_foreign_key(
            "fk_assignments_advisor_org",
            "advisors",
            ["advisor_id", "company_id", "point_of_sale_id"],
            ["advisor_id", "company_id", "point_of_sale_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("assignments", schema=None) as batch_op:
        batch_op.drop_constraint("fk_assignments_advisor_org", type_="foreignkey")
        batch_op.drop_constraint("fk_assignments_company_pos", type_="foreignkey")

    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_constraint("fk_leads_company_pos", type_="foreignkey")

    with op.batch_alter_table("advisors", schema=None) as batch_op:
        batch_op.drop_constraint("fk_advisors_company_pos", type_="foreignkey")
        batch_op.drop_constraint("uq_advisors_id_company_pos", type_="unique")

    with op.batch_alter_table("points_of_sale", schema=None) as batch_op:
        batch_op.drop_constraint("uq_points_of_sale_company_pos", type_="unique")
