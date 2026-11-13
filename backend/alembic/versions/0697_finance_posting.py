"""Księgowość w Finansach (E2): plan kont, reguły dekretu, dekret wpisu i paczki eksportu.

Revision ID: 0697_finance_posting
Revises: 0696_sales_invoice_issue

Tabele ``finance_accounts``, ``finance_posting_rules`` i
``finance_posting_batches``, kolumny ``decree`` i ``batch_id`` w
``finance_cost_entries``, nowe akcje historii wpisu oraz zasiew kont
wzorcowych i reguły domyślnej (kontraktor → 402-203). DDL ma jedno źródło
(``app/services/finance_posting_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import finance_posting_schema as schema

revision = "0697_finance_posting"
down_revision = "0696_sales_invoice_issue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
