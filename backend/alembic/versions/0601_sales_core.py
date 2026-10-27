"""Sprzedaż (Atlas → NEXUS): lejki, firmy, kontakty, szanse, aktywności i pliki.

Revision ID: 0601_sales_core
Revises: 0600_sales_permissions

SQL i powody: ``app/services/sales_schema.py`` (to samo źródło czyta
``entrypoint.sh``). Domyślny lejek „Sprzedaż” z etapami jak w Atlasie.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0601_sales_core"
down_revision = "0600_sales_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
