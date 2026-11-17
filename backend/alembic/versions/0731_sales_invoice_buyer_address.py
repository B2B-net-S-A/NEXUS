"""Faktury sprzedażowe: adres nabywcy z ``Podmiot2/Adres`` dla kartoteki Symfonii.

Revision ID: 0731_sales_invoice_buyer_address
Revises: 0730_champion_profile_revisions

SQL ma jedno źródło (``app/services/client_sales_invoices_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``. Same dodania kolumn
NULL, więc stary kod działa na nowym schemacie.
"""

from alembic import op

from app.services import client_sales_invoices_schema as schema

revision = "0731_sales_invoice_buyer_address"
down_revision = "0730_champion_profile_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.BUYER_ADDRESS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for column in (
        "buyer_address_read_at",
        "buyer_address_line2",
        "buyer_address_line1",
        "buyer_country",
    ):
        op.execute(f"ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS {column}")
