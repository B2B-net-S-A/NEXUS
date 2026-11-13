"""Przelewy i zapłaty faktur kosztowych (E3).

Revision ID: 0697_finance_payments
Revises: 0696_sales_invoice_issue

Tabele ``finance_cost_payments``, ``finance_counterparty_accounts``,
``finance_payment_batches``, ``finance_payment_batch_items``,
``finance_cost_payment_records`` i ``finance_counterparty_account_events``
oraz akcja ``account`` w CHECK historii wpisu. DDL ma jedno źródło
(``app/services/finance_payments_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``. Bez backfillu — wpis bez wiersza
płatności to „niezapłacona”.
"""

from alembic import op

from app.services import finance_payments_schema as schema

revision = "0697_finance_payments"
down_revision = "0696_sales_invoice_issue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
