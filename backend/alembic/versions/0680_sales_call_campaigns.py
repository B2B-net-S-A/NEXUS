"""Sprzedaż: kampanie dzwonienia, rekordy kolejki i wyniki rozmów z kolejki.

Revision ID: 0680_sales_call_campaigns
Revises: 0679_client_settlements

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0680_sales_call_campaigns"
down_revision = "0679_client_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALLING_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALLING_DOWNGRADE_DDL:
        op.execute(stmt)
