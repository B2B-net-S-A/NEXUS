"""Zajęcia wierzytelności, spór na rozliczeniu i przelewy do organów w paczce.

Revision ID: 0765_contractor_payment_blocks
Revises: 0764_contract_rate_annex_bell

Decyzja Artura z 23.11.2026: rejestr i blokady płatności kontraktorów
w NEXUSIE zamiast Excela i maili. Tabele ``contractor_garnishments``
i ``contractor_payment_holds`` oraz kolumna
``finance_payment_batch_items.garnishments``. DDL ma jedno źródło
(``app/services/contractor_payment_blocks_schema.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``. Same dodania.
"""

from alembic import op

from app.services import contractor_payment_blocks_schema as schema

revision = "0765_contractor_payment_blocks"
down_revision = "0764_contract_rate_annex_bell"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
