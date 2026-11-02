"""Kartoteka: raport godzin bez limitu dnia dla wybranej osoby.

Revision ID: 0631_no_hours_limit
Revises: 0630_sales_invoice_foreign_id

SQL ma jedno źródło (``app/services/hr_foundation_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_foundation_schema as schema

revision = "0631_no_hours_limit"
down_revision = "0630_sales_invoice_foreign_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.NO_HOURS_LIMIT_DDL)


def downgrade() -> None:
    op.execute("ALTER TABLE employee_profiles DROP COLUMN IF EXISTS no_hours_limit")
