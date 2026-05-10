"""Hotfix: add client_orders.rate_client column (omitted in 0093).

Revision ID: 0095_add_order_rate_client
Revises: 0094_wipe_contracts
Create Date: 2026-05-11 10:15:00.000000

W migracji 0093 model ClientOrder dostał pole `rate_client` (per Order, dla
przedłużeń z podwyżką), ale ALTER TABLE w 0093 nie dodał kolumny. Skutek:
``UndefinedColumnError: column client_orders.rate_client does not exist`` przy
każdym query do Order. Hotfix idempotent.
"""

from alembic import op


revision = "0095_add_order_rate_client"
down_revision = "0094_wipe_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_orders "
        "ADD COLUMN IF NOT EXISTS rate_client INTEGER NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS rate_client")
