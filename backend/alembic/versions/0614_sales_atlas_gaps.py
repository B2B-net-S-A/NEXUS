"""Sprzedaż: luki importu Atlasa (opiekun z Atlasa, pola Outlooka, kontakt w wielu firmach).

Revision ID: 0614_sales_atlas_gaps
Revises: 0613_timesheets_permission

SQL i powody: ``app/services/sales_schema.py`` (``GAPS_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0614_sales_atlas_gaps"
down_revision = "0613_timesheets_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.GAPS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.GAPS_DOWNGRADE_DDL:
        op.execute(stmt)
