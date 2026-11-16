"""Środki trwałe i WNiP (K6): ewidencja i dokumenty OT, UL, MT, LT, SP.

Revision ID: 0703_ledger_assets
Revises: 0702_ledger_exports

Tabele ``ledger_assets`` (ewidencja z planem bilansowym i podatkowym, stan
z Symfonii Środki Trwałe) i ``ledger_asset_operations`` (dokumenty środka).
DDL ma jedno źródło (``app/services/ledger_assets_schema.py``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import ledger_assets_schema as schema

revision = "0703_ledger_assets"
down_revision = "0702_ledger_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
