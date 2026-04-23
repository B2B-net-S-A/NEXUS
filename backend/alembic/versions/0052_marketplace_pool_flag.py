"""Targ kandydatów: is_marketplace flag + marketplace_until on membership

Revision ID: 0052_marketplace_pool_flag
Revises: 0051_champion_historical_source
Create Date: 2026-04-23 16:00:00.000000

Dodaje:
- talent_pools.is_marketplace (BOOLEAN, default false) — flaga dla singletona
  puli "Targ kandydatów". Partial unique index pilnuje, że może być tylko
  JEDEN rekord z is_marketplace=true.
- talent_pool_memberships.marketplace_until (DATE, nullable) — data wygaśnięcia
  ręcznego wrzutu na targ. NULL dla auto-entry (availability_status=actively_looking).

Idempotentna i odwracalna.
"""

from alembic import op


revision = "0052_marketplace_pool_flag"
down_revision = "0051_champion_historical_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Kolumna is_marketplace na talent_pools.
    op.execute(
        "ALTER TABLE talent_pools "
        "ADD COLUMN IF NOT EXISTS is_marketplace BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # 2) Partial unique — tylko jeden wiersz z is_marketplace=true w systemie.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_talent_pools_marketplace_singleton "
        "ON talent_pools ((1)) WHERE is_marketplace = TRUE"
    )

    # 3) Kolumna marketplace_until na talent_pool_memberships.
    op.execute(
        "ALTER TABLE talent_pool_memberships "
        "ADD COLUMN IF NOT EXISTS marketplace_until DATE"
    )

    # 4) Częściowy indeks dla sweepera (szybka kwerenda wygasłych ręcznych
    #    wrzutów). NULL nie ma znaczenia dla cleanupu.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tpm_marketplace_until "
        "ON talent_pool_memberships (marketplace_until) "
        "WHERE marketplace_until IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tpm_marketplace_until")
    op.execute(
        "ALTER TABLE talent_pool_memberships DROP COLUMN IF EXISTS marketplace_until"
    )
    op.execute("DROP INDEX IF EXISTS ux_talent_pools_marketplace_singleton")
    op.execute("ALTER TABLE talent_pools DROP COLUMN IF EXISTS is_marketplace")
