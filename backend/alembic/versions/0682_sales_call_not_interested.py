"""Sprzedaż: wyniki „Nie zainteresowany” i „Zły numer / brak danych” w kolejce.

Revision ID: 0682_sales_call_not_interested
Revises: 0681_sales_call_campaigns

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0682_sales_call_not_interested"
down_revision = "0681_sales_call_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALL_OUTCOMES_V2_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALL_OUTCOMES_V2_DOWNGRADE_DDL:
        op.execute(stmt)
