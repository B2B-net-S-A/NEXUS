"""Sprzedaż: biegi bota researchu, punkty do rozmowy przy firmie, źródło leada ``research``.

Revision ID: 0676_sales_signal_runs
Revises: 0675_notification_on_behalf

SQL i powody: ``app/services/sales_schema.py`` (``SIGNALS_DDL``; to samo źródło
czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0676_sales_signal_runs"
down_revision = "0675_notification_on_behalf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.SIGNALS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.SIGNALS_DOWNGRADE_DDL:
        op.execute(stmt)
