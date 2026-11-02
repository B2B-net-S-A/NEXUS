"""Faktury sprzedażowe: VAT UE nabywcy i metoda dopasowania „osoba i stawka”.

Revision ID: 0631_sales_invoice_foreign_id
Revises: 0628_sales_meeting_transcripts

SQL ma jedno źródło (``app/services/client_sales_invoices_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_sales_invoices_schema as schema

revision = "0631_sales_invoice_foreign_id"
down_revision = "0628_sales_meeting_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.BUYER_FOREIGN_ID_DDL)
    for stmt in schema.METHOD_CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Ograniczenie metody zostaje: zapisane faktury mogą już mieć wartość ``person``.
    op.execute(
        "ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS buyer_foreign_id"
    )
