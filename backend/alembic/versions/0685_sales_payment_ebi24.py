"""Zapłaty faktur do klientów odczytane z eBI24 (rodzaj ``ebi24``).

Revision ID: 0685_sales_payment_ebi24
Revises: 0684_sales_bot_tasks

SQL ma jedno źródło (``app/services/client_sales_invoices_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_sales_invoices_schema as schema

revision = "0685_sales_payment_ebi24"
down_revision = "0684_sales_bot_tasks"
branch_labels = None
depends_on = None

EBI24_INDEX = next(
    stmt for stmt in schema.INDEX_DDL if "uq_client_sales_invoice_payments_ebi24" in stmt
)


def upgrade() -> None:
    op.execute(schema.EBI24_DOCUMENT_ID_DDL)
    op.execute(EBI24_INDEX)
    for stmt in schema.PAYMENT_EBI24_CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DELETE FROM client_sales_invoice_payments WHERE kind = 'ebi24'")
    op.execute(
        "ALTER TABLE client_sales_invoice_payments "
        "DROP CONSTRAINT IF EXISTS ck_client_sales_invoice_payments_ebi24"
    )
    op.execute("DROP INDEX IF EXISTS uq_client_sales_invoice_payments_ebi24")
    op.execute(
        "ALTER TABLE client_sales_invoice_payments "
        "DROP COLUMN IF EXISTS ebi24_document_id"
    )
    op.execute(
        "ALTER TABLE client_sales_invoice_payments "
        "DROP CONSTRAINT IF EXISTS ck_client_sales_invoice_payments_kind"
    )
    op.execute(
        "ALTER TABLE client_sales_invoice_payments ADD CONSTRAINT "
        "ck_client_sales_invoice_payments_kind "
        "CHECK (kind IN ('statement_line', 'manual'))"
    )
