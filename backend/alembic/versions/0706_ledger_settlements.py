"""Rozrachunki z rozliczaniem pozycji (K4b).

Revision ID: 0706_ledger_settlements
Revises: 0705_ledger_bank

Tabela ``ledger_settlements``: rozliczenie zapisu Wn z zapisem Ma tego samego
konta kontrahenta (kwota, data, sposób, ślad cofnięcia). DDL ma jedno źródło
(``app/services/ledger_settlement_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_settlement_schema as schema

revision = "0706_ledger_settlements"
down_revision = "0705_ledger_bank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
