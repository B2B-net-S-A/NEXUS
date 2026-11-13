"""Przelewy i zapłaty faktur kosztowych (E3).

Revision ID: 0696_finance_payments
Revises: 0695_finance_ledger

Tabele ``finance_cost_payments``, ``finance_counterparty_accounts``,
``finance_payment_batches``, ``finance_payment_batch_items`` i
``finance_cost_payment_records``. DDL ma jedno źródło
(``app/services/finance_payments_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``. Bez backfillu — wpis bez wiersza
płatności to „niezapłacona”.
"""

from alembic import op

from app.services import finance_payments_schema as schema

revision = "0696_finance_payments"
down_revision = "0695_finance_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
