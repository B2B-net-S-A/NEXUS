"""Sprzedaż: Bot Listy — brief kampanii dzwonienia (decyzja Artura 13.11.2026).

Revision ID: 0690_sales_bot_lists
Revises: 0689_client_time_reports

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0690_sales_bot_lists"
down_revision = "0689_client_time_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.BOT_LISTS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.BOT_LISTS_DOWNGRADE_DDL:
        op.execute(stmt)
