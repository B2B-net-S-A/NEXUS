"""Paczki księgi do Symfonii FK (K3b).

Revision ID: 0702_ledger_exports
Revises: 0701_ledger_automations

Tabele ``ledger_exports`` (paczka miesiąca z plikiem i SHA-256) i
``ledger_export_documents`` (dokumenty paczki; dokument najwyżej w jednej
aktywnej paczce). DDL ma jedno źródło (``app/services/ledger_export_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_export_schema as schema

revision = "0702_ledger_exports"
down_revision = "0701_ledger_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
