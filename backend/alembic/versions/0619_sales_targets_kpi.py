"""Sprzedaż: cele i KPI tygodniowe handlowców.

Revision ID: 0619_sales_targets_kpi
Revises: 0618_sales_opportunity_events

SQL i powody: ``app/services/sales_schema.py`` (``TARGETS_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0619_sales_targets_kpi"
down_revision = "0618_sales_opportunity_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TARGETS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.TARGETS_DOWNGRADE_DDL:
        op.execute(stmt)
