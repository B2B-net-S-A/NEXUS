"""Rozliczenia Nordei N1: kartoteka identyfikatorów klienta i wersje raportu T4T.

Revision ID: 0689_client_time_reports
Revises: 0688_contractor_invoice_checks

SQL i powody: ``app/services/client_time_reports_schema.py`` (to samo źródło
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_time_reports_schema as schema

revision = "0689_client_time_reports"
down_revision = "0688_contractor_invoice_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
