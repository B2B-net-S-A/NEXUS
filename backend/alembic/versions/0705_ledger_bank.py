"""Wyciągi bankowe w księdze (K4a): jeden import wyciągu w Księdze.

Revision ID: 0705_ledger_bank
Revises: 0704_payroll_lists

Tabele ``ledger_bank_statements`` (wyciąg: plik, rachunek firmy, konto, sumy)
i ``ledger_bank_lines`` (operacje z rozpoznaniem i kontem przeciwstawnym do
dokumentu WB). DDL ma jedno źródło (``app/services/ledger_bank_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_bank_schema as schema

revision = "0705_ledger_bank"
down_revision = "0704_payroll_lists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
