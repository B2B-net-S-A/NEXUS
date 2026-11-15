"""Szablony faktur cyklicznych, refaktury benefitów i faktura z ręki (E6).

Revision ID: 0709_sales_invoice_templates
Revises: 0708_ledger_vat_files

Tabela ``client_invoice_templates`` (szablon „co miesiąc” — usługi bez
zamówienia i refaktury benefitów), ``client_issued_invoices.template_id`` z
jednym szkicem szablonu na miesiąc i ``client_id`` bez NOT NULL (nabywca spoza
kartoteki klientów). DDL ma jedno źródło
(``app/services/client_invoice_templates_schema.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_invoice_templates_schema as schema

revision = "0709_sales_invoice_templates"
down_revision = "0708_ledger_vat_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
