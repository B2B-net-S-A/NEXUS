"""Księga NEXUSA (K1): lata obrotowe, okresy, dokumenty z dekretem, dziennik.

Revision ID: 0700_ledger_core
Revises: 0699_finance_payments

Tabele ``ledger_years``, ``ledger_periods``, ``ledger_documents``,
``ledger_lines`` i ``ledger_events``, nowe kolumny planu kont z E2
(``finance_accounts``: konto nadrzędne, typ, słownik analityki, pozycja
sprawozdania), rodzaj konta ``other`` i wyzwalacze trwałości zatwierdzonych
zapisów. DDL ma jedno źródło (``app/services/ledger_schema.py``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_schema as schema

revision = "0700_ledger_core"
down_revision = "0699_finance_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
