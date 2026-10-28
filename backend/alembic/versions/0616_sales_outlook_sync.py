"""Sprzedaż: bieżąca poczta i kalendarz Outlooka handlowców przy firmach.

Revision ID: 0616_sales_outlook_sync
Revises: 0615_job_twins

SQL i powody: ``app/services/sales_schema.py`` (``OUTLOOK_SYNC_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0616_sales_outlook_sync"
down_revision = "0615_job_twins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.OUTLOOK_SYNC_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.OUTLOOK_SYNC_DOWNGRADE_DDL:
        op.execute(stmt)
