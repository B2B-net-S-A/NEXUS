"""Sprzedaż: wynik rozmowy w aktywności i sprzeciw wobec kontaktu.

Revision ID: 0672_sales_call_outcome
Revises: 0671_sales_company_aliases

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0672_sales_call_outcome"
down_revision = "0671_sales_company_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DOWNGRADE_DDL:
        op.execute(stmt)
