"""Rozliczenia klientów E1: rozliczenie osoby za miesiąc, wersje reguł klienta, źródło MD „settlement”.

Revision ID: 0679_client_settlements
Revises: 0678_duty_search

SQL i powody: ``app/services/client_settlements_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlements_schema as schema

revision = "0679_client_settlements"
down_revision = "0678_duty_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
