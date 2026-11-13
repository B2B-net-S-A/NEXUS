"""Księgowość w Finansach (E0, E1): kartoteka kontrahentów i kolejka kosztów.

Revision ID: 0696_finance_ledger
Revises: 0695_sales_invoice_issue

Tabele ``finance_counterparties``, ``finance_cost_entries`` i
``finance_cost_entry_events`` oraz wpisy dla faktur, które już są w źródłach
(backfill). DDL ma jedno źródło (``app/services/finance_ledger_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import finance_ledger_schema as schema

revision = "0696_finance_ledger"
down_revision = "0695_sales_invoice_issue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
