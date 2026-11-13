"""Rozliczenia E4: treść korekt z XML-a i biała lista VAT przy fakturach kontraktorów.

Revision ID: 0688_contractor_invoice_checks
Revises: 0687_b2b_signing_documents

Dwie kolumny JSONB w ``client_contractor_invoices`` (``details``,
``vat_whitelist``). DDL ma jedno źródło
(``app/services/client_settlements_schema.CONTRACTOR_CHECKS_DDL``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_settlements_schema as schema

revision = "0688_contractor_invoice_checks"
down_revision = "0687_b2b_signing_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CONTRACTOR_CHECKS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_contractor_invoices DROP COLUMN IF EXISTS vat_whitelist"
    )
    op.execute("ALTER TABLE client_contractor_invoices DROP COLUMN IF EXISTS details")
