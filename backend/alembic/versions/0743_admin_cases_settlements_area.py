"""Sprawy: obszar „Rozliczenia” dla maili na adres rozliczeń (19.11.2026).

Revision ID: 0743_admin_cases_settlements_area
Revises: 0742_ledger_bank_balances

Decyzja Artura z 19.11.2026: mail na adres z ``CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES``
(„Do”/„DW”), który czytnik spraw zakłada jako sprawę (pytanie bez załącznika), dostaje
obszar ``settlements`` zamiast ``administration``. Migracja poszerza CHECK obszaru. DDL ma
jedno źródło (``app/services/admin_cases_schema.py``); entrypoint wykonuje je przy każdym
starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import admin_cases_schema as schema

revision = "0743_admin_cases_settlements_area"
down_revision = "0742_ledger_bank_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.SETTLEMENTS_AREA_DOWNGRADE_DDL:
        op.execute(stmt)
