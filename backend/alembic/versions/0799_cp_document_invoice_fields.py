"""Pola faktury PDF z poczty rozliczeń: koszt w kontroli miesiąca.

Revision ID: 0799_cp_document_invoice_fields
Revises: 0798_stage_przygotowanie_cv

27.11.2026: faktury konsultantów spoza KSeF (papier, PDF) NEXUS widział tylko
z eksportu eBI24 z 16.11. Faktura PDF z rozliczenia@ leżała jako dokument bez
kwoty. Model z rejestru odczytuje NIP, numer, datę i kwoty
(``consultant_portal/invoice_read.py``), a kontrola miesiąca liczy je obok
KSeF i eBI24. DDL w ``app/services/consultant_portal_schema.py``, lustro
w ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services.consultant_portal_schema import INVOICE_FIELDS_DDL

revision = "0799_cp_document_invoice_fields"
down_revision = "0798_stage_przygotowanie_cv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(INVOICE_FIELDS_DDL)


def downgrade() -> None:
    op.execute("ALTER TABLE cp_documents DROP COLUMN IF EXISTS invoice_fields")
