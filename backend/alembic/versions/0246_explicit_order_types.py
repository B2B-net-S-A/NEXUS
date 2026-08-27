"""Jawny typ nowych zamówień bez backfillu historii.

Revision ID: 0246_explicit_order_types
Revises: 0245_cyfrowy_polsat_shared_md_orders

Obie kolumny są nullable i migracja nie wykonuje UPDATE. ``NULL`` jest
świadomym znacznikiem rekordu legacy, który nadal korzysta z dotychczasowych
flag, konfiguracji klientowych i matcherów importu.
"""

from alembic import op
import sqlalchemy as sa


revision = "0246_explicit_order_types"
down_revision = "0245_cyfrowy_polsat_shared_md_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_orders",
        sa.Column("order_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("order_type", sa.String(length=16), nullable=True),
    )

    op.create_check_constraint(
        "ck_client_orders_order_type",
        "client_orders",
        "order_type IS NULL OR order_type IN ('periodic', 'cost', 'md')",
    )
    op.create_check_constraint(
        "ck_client_order_groups_order_type",
        "client_order_groups",
        "order_type IS NULL OR order_type IN ('cost', 'md')",
    )
    op.create_check_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        "order_type IS NULL OR "
        "(order_type = 'cost' AND is_cost_based = TRUE "
        "AND is_md_budget_based = FALSE) OR "
        "(order_type = 'md' AND is_cost_based = FALSE "
        "AND is_md_budget_based = TRUE)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        type_="check",
    )
    op.drop_constraint(
        "ck_client_order_groups_order_type",
        "client_order_groups",
        type_="check",
    )
    op.drop_constraint(
        "ck_client_orders_order_type",
        "client_orders",
        type_="check",
    )
    op.drop_column("client_order_groups", "order_type")
    op.drop_column("client_orders", "order_type")
