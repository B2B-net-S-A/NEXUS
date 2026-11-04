"""Sprzedaż: skrzynka leadów (skan ogłoszeń, import z Atlasa, wpis ręczny).

Revision ID: 0602_sales_leads
Revises: 0601_sales_core

SQL i powody: ``app/services/sales_schema.py`` (``LEADS_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0602_sales_leads"
down_revision = "0601_sales_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.LEADS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.LEADS_DOWNGRADE_DDL:
        op.execute(stmt)
