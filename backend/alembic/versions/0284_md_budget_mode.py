"""Explicit MD budget choice for new orders; preserve all historical budgets."""

from alembic import op
import sqlalchemy as sa

revision = "0284_md_budget_mode"
down_revision = "0283_cv_rule_publications"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "client_order_groups", sa.Column("md_budget_mode", sa.String(16), nullable=True)
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "md_budget_mode_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.drop_constraint(
        "ck_client_order_groups_status", "client_order_groups", type_="check"
    )
    op.create_check_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        "status IN ('draft', 'active', 'scheduled', 'completed', 'exhausted')",
    )
    op.create_check_constraint(
        "ck_client_order_groups_md_mode",
        "client_order_groups",
        "md_budget_mode IS NULL OR (order_type = 'md' AND ((md_budget_mode = 'shared' AND is_md_budget_based = TRUE) OR (md_budget_mode = 'per_person' AND is_md_budget_based = FALSE)))",
    )


def downgrade():
    # Do not silently activate or discard drafts when rolling back.
    op.drop_constraint(
        "ck_client_order_groups_md_mode", "client_order_groups", type_="check"
    )
    op.drop_constraint(
        "ck_client_order_groups_status", "client_order_groups", type_="check"
    )
    op.create_check_constraint(
        "ck_client_order_groups_status",
        "client_order_groups",
        "status IN ('active', 'scheduled', 'completed', 'exhausted')",
    )
    op.drop_column("client_order_groups", "md_budget_mode_locked")
    op.drop_column("client_order_groups", "md_budget_mode")
