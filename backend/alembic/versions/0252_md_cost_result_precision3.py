"""Preserve three decimal places for MD results and related cost values.

Revision ID: 0252_md_cost_result_precision3
Revises: 0251_explicit_md_per_consultant

The UI can only display a third decimal if the import, persistence and API
layers have not rounded it away first.  MD consumption already uses six
decimal places; this revision widens the result fields that were still stored
as two-decimal values:

* Finance ``md_count`` and its corresponding result amounts;
* standalone cost-order total values that seed group budgets;
* cost-order group budgets and their calculated remainder/adjustment;
* imported, settled and unsettled invoice consumption amounts.

Only NUMERIC types are widened.  There is no historical UPDATE and no value is
recalculated.  Precision grows together with scale so every previous integer
range remains available.
"""

import sqlalchemy as sa
from alembic import op


revision = "0252_md_cost_result_precision3"
down_revision = "0251_explicit_md_per_consultant"
branch_labels = None
depends_on = None


# table, column, old precision, new precision, nullable
_RESULT_COLUMNS = (
    ("finance_monthly_results", "md_count", 8, 9, True),
    ("finance_monthly_results", "compensation", 14, 15, True),
    ("finance_monthly_results", "invoice_amount", 14, 15, True),
    ("finance_monthly_results", "margin_pln", 14, 15, True),
    ("client_orders", "total_value", 12, 13, True),
    ("client_order_groups", "budget_amount", 16, 17, True),
    ("client_order_groups", "budget_remaining", 16, 17, True),
    ("client_order_groups", "budget_manual_adjustment", 16, 17, False),
    ("md_consumption_import_rows", "invoice_amount", 16, 17, True),
    ("client_order_invoice_consumptions", "invoice_amount", 16, 17, False),
    ("client_order_invoice_consumptions", "settled_amount", 16, 17, False),
    ("client_order_invoice_consumptions", "unsettled_amount", 16, 17, False),
)


def upgrade() -> None:
    for table, column, old_precision, new_precision, nullable in _RESULT_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(old_precision, 2),
            type_=sa.Numeric(new_precision, 3),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for table, column, old_precision, new_precision, nullable in _RESULT_COLUMNS:
        # Keep the one widened precision digit while returning to scale 2.
        # A value at the new upper bound can round with carry
        # (e.g. 999999.999 -> 1000000.00), which does not fit the historical
        # ``numeric(old_precision, 2)`` even though it was valid before the
        # downgrade.  ``numeric(new_precision, 2)`` preserves that carry without
        # clamping data; old application code is compatible with the wider
        # database column.
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(new_precision, 3),
            type_=sa.Numeric(new_precision, 2),
            existing_nullable=nullable,
            postgresql_using=(f"round({column}, 2)::numeric({new_precision},2)"),
        )
