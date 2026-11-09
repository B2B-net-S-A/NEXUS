"""Sprzedaż: inne nazwy firmy z CV dołączone do karty albo odrzucone.

Revision ID: 0668_sales_company_aliases
Revises: 0667_drop_abandoned_tables

SQL i powody: ``app/services/sales_schema.py`` (``COMPANY_ALIASES_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0668_sales_company_aliases"
down_revision = "0667_drop_abandoned_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.COMPANY_ALIASES_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.COMPANY_ALIASES_DOWNGRADE_DDL:
        op.execute(stmt)
