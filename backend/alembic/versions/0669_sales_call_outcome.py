"""Sprzedaż: wynik rozmowy w aktywności i sprzeciw wobec kontaktu.

Revision ID: 0669_sales_call_outcome
Revises: 0668_cortex_first_seen_not_null

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0669_sales_call_outcome"
down_revision = "0668_cortex_first_seen_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DOWNGRADE_DDL:
        op.execute(stmt)
