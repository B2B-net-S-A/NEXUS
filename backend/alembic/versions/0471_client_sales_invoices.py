"""Faktury sprzedażowe do klientów z KSeF (etap 5, E8 cz. 1).

Revision ID: 0471_client_sales_invoices
Revises: 0470_hr_agreements

SQL ma jedno źródło (``app/services/client_sales_invoices_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_sales_invoices_schema as schema

revision = "0471_client_sales_invoices"
down_revision = "0470_hr_agreements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
