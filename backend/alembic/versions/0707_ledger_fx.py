"""Waluty w księdze (K4c-1): rachunki walutowe i różnice kursowe zrealizowane.

Revision ID: 0707_ledger_fx
Revises: 0706_ledger_settlements

Wyciągi w EUR i USD (kwota w PLN po kursie NBP z ostatniego dnia roboczego
przed operacją), kurs pozycji dokumentu, rozliczenie pozycji w walucie i sposób
``fx``. DDL ma jedno źródło (``app/services/ledger_fx_schema.py``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_fx_schema as schema

revision = "0707_ledger_fx"
down_revision = "0706_ledger_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
