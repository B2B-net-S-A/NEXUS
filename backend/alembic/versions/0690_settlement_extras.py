"""Rozliczenia klientów E5.1: dodatki do rozliczenia (``client_settlement_extras``),
pierwszy rodzaj — koszty integracji konsultanta ze zgodą DL-a.

Revision ID: 0690_settlement_extras
Revises: 0689_client_time_reports

SQL i powody: ``app/services/client_settlements_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlements_schema as schema

revision = "0690_settlement_extras"
down_revision = "0689_client_time_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.EXTRAS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_settlement_extras CASCADE")
