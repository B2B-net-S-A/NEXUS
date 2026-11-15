"""Pliki JPK_V7M (K5b).

Revision ID: 0708_ledger_vat_files
Revises: 0707_ledger_fx

Tabela ``ledger_vat_files``: przygotowany plik JPK_V7M (ewidencja VAT
z deklaracją) za miesiąc — wersja, cel złożenia, treść XML z SHA-256, sumy
deklaracji, stan „wysłany”. DDL ma jedno źródło
(``app/services/ledger_vat_schema.py``); entrypoint wykonuje je przy każdym
starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_vat_schema as schema

revision = "0708_ledger_vat_files"
down_revision = "0707_ledger_fx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
