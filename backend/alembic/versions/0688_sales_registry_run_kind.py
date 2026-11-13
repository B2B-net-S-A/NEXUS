"""Sprzedaż: rodzaj biegu ``registry`` — dane firm z białej listy VAT i KRS.

Revision ID: 0688_sales_registry_run_kind
Revises: 0687_b2b_signing_documents

SQL i powody: ``app/services/sales_schema.py`` (``REGISTRY_DDL``; to samo źródło
czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0688_sales_registry_run_kind"
down_revision = "0687_b2b_signing_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.REGISTRY_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.REGISTRY_DOWNGRADE_DDL:
        op.execute(stmt)
