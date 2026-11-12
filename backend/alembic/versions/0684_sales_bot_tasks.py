"""Sprzedaż: zadania bota — nowe rodzaje biegów i punktów, zlecenie biegu, wyniki do decyzji.

Revision ID: 0684_sales_bot_tasks
Revises: 0683_sales_call_not_interested

SQL i powody: ``app/services/sales_schema.py`` (``BOT_TASKS_DDL``; to samo źródło
czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0684_sales_bot_tasks"
down_revision = "0683_sales_call_not_interested"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.BOT_TASKS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.BOT_TASKS_DOWNGRADE_DDL:
        op.execute(stmt)
