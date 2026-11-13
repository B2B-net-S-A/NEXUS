"""E-faktury Peppol przy fakturach sprzedażowych z KSeF (plan Nordei N2).

Revision ID: 0692_client_einvoices
Revises: 0691_settlement_extras

Tabela ``client_sales_invoice_einvoices``. DDL ma jedno źródło
(``app/services/client_einvoices_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_einvoices_schema as schema

revision = "0692_client_einvoices"
down_revision = "0691_settlement_extras"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
