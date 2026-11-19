"""Salda wyciągów w księdze: ciągłość rachunku dla „po terminie” (19.11.2026).

Revision ID: 0742_ledger_bank_balances
Revises: 0741_order_cost_steps

Wyciąg w Księgowość → Bank zapamiętuje saldo otwarcia i zamknięcia z datami,
numery wyciągów banku i to, czy jego uznania przeszły przez E8. Z tego
łańcucha sald faktura do klienta jest „po terminie” tylko wtedy, gdy NEXUS ma
ciągłe wyciągi rachunku odbioru od wystawienia do dnia po terminie
(``docs/claude/zamowienia/faktury-do-klientow-z-ksef.md``). DDL ma jedno
źródło (``app/services/ledger_bank_balance_schema.py``); entrypoint wykonuje
je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_bank_balance_schema as schema

revision = "0742_ledger_bank_balances"
down_revision = "0741_order_cost_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
