"""Automaty księgi (K3a): PK cykliczne i RMK (rozliczenia międzyokresowe kosztów).

Revision ID: 0701_ledger_automations
Revises: 0700_ledger_core

Tabele ``ledger_recurring`` (wzory PK powtarzanych co miesiąc) i
``ledger_prepayments`` (RMK czynne, np. polisy, z ratą miesięczną). DDL ma
jedno źródło (``app/services/ledger_automation_schema.py``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_automation_schema as schema

revision = "0701_ledger_automations"
down_revision = "0700_ledger_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
