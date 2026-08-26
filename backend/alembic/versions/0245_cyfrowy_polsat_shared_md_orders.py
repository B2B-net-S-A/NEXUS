"""Wspólna pula MD zamówień Cyfrowego Polsatu.

Revision ID: 0245_cyfrowy_polsat_shared_md_orders
Revises: 0244_cardif_client_reassignment

Istniejący wariant MD przechowuje budżet na każdej linii konsultanta. Nowy
wariant jest jedną pulą całego zamówienia, analogiczną do puli kosztowej, ale
wyrażoną w MD. Pola są addytywne i domyślnie wyłączone, więc istniejące grupy
BIK/BNP/Polkomtela zachowują dotychczasową semantykę.
"""

from alembic import op
import sqlalchemy as sa


revision = "0245_cyfrowy_polsat_shared_md_orders"
down_revision = "0244_cardif_client_reassignment"
branch_labels = None
depends_on = None


_MD_BUDGET_COHERENCE = """(
    (
        is_md_budget_based = FALSE
        AND md_budget_total IS NULL
        AND md_budget_remaining IS NULL
        AND md_budget_manual_adjustment = 0
    )
    OR (
        is_md_budget_based = TRUE
        AND md_budget_total IS NOT NULL
        AND md_budget_total > 0
        AND md_budget_remaining IS NOT NULL
        AND md_budget_remaining >= 0
    )
)"""


def upgrade() -> None:
    op.add_column(
        "client_order_groups",
        sa.Column(
            "is_md_budget_based",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("md_budget_total", sa.Numeric(16, 6), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("md_budget_remaining", sa.Numeric(16, 6), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "md_budget_manual_adjustment",
            sa.Numeric(16, 6),
            nullable=False,
            server_default="0",
        ),
    )

    op.execute(
        "ALTER TABLE client_order_groups ADD CONSTRAINT "
        "ck_client_order_groups_settlement_exclusive "
        "CHECK (NOT (is_cost_based = TRUE AND is_md_budget_based = TRUE)) NOT VALID"
    )
    op.execute(
        "ALTER TABLE client_order_groups ADD CONSTRAINT "
        "ck_client_order_groups_md_budget_coherence "
        f"CHECK {_MD_BUDGET_COHERENCE} NOT VALID"
    )
    op.execute(
        "ALTER TABLE client_order_groups VALIDATE CONSTRAINT "
        "ck_client_order_groups_settlement_exclusive"
    )
    op.execute(
        "ALTER TABLE client_order_groups VALIDATE CONSTRAINT "
        "ck_client_order_groups_md_budget_coherence"
    )

    op.create_table(
        "client_order_group_md_consumptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("md_reported", sa.Numeric(16, 6), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
            name="ck_group_md_consumptions_period",
        ),
        sa.CheckConstraint(
            "source IN ('import', 'manual')",
            name="ck_group_md_consumptions_source",
        ),
        sa.CheckConstraint(
            "md_reported >= 0",
            name="ck_group_md_consumptions_nonnegative",
        ),
    )
    op.create_index(
        "ux_group_md_consumptions_group_month",
        "client_order_group_md_consumptions",
        ["group_id", "period_month"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_group_md_consumptions_group_month",
        table_name="client_order_group_md_consumptions",
    )
    op.drop_table("client_order_group_md_consumptions")
    op.drop_constraint(
        "ck_client_order_groups_md_budget_coherence",
        "client_order_groups",
        type_="check",
    )
    op.drop_constraint(
        "ck_client_order_groups_settlement_exclusive",
        "client_order_groups",
        type_="check",
    )
    op.drop_column("client_order_groups", "md_budget_manual_adjustment")
    op.drop_column("client_order_groups", "md_budget_remaining")
    op.drop_column("client_order_groups", "md_budget_total")
    op.drop_column("client_order_groups", "is_md_budget_based")
