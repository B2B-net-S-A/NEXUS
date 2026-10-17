"""Czarna lista z powodem i „Pracuje u nas” tylko z umowy (17.10.2026).

Revision ID: 0452_blacklist_contract_only
Revises: 0451_client_acceptance

Decyzja Artura 17.10.2026 (makiety https://claude.ai/artifact/UGYuAg37XJYhkAipLQyPeW):

* czarna lista „u nas” ustawiana w jednym oknie „Czarna lista…” zapisuje,
  kto, kiedy i dlaczego — trzy kolumny przy kandydacie (status
  ``blacklisted`` zostaje tam, gdzie był);
* zatrudnienie wynika wyłącznie z umowy: ręczny wpis ``current_employment``
  („Oznacz jako zatrudnionego”) przestaje się liczyć. Na produkcji był jeden
  aktywny — zdejmujemy go z powodem (wiersz zostaje w historii), raz,
  z markerem w ``app_settings``;
* typ dzwonka ``hire_missing_contract``: karta trafiła na „Zatrudniony”, a w
  Kontraktach nie ma umowy — przypomnienie dla Delivery Leada klienta.

Lustro w ``entrypoint.sh`` — pilnuje ``test_blacklist_contract_only_migration.py``.
"""

from alembic import op

revision = "0452_blacklist_contract_only"
down_revision = "0451_client_acceptance"
branch_labels = None
depends_on = None

ADD_BLACKLISTED_AT = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS blacklisted_at TIMESTAMPTZ NULL"
)
ADD_BLACKLISTED_BY = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS blacklisted_by_user_id "
    "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
)
ADD_BLACKLIST_REASON = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS blacklist_reason TEXT NULL"
)
ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'hire_missing_contract'"
)
# Raz: marker w tym samym statemencie, bo lustro w entrypoincie leci przy
# każdym starcie kontenera.
RETIRE_MANUAL_EMPLOYMENT = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('manual_employment_conflicts_retired_2026_10', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE candidate_conflicts SET active = FALSE, deactivated_at = NOW(), "
    "deactivation_reason = 'Zatrudnienie wynika tylko z umowy w Kontraktach "
    "(decyzja 17.10.2026)' "
    "WHERE type::text = 'current_employment' AND active "
    "AND EXISTS (SELECT 1 FROM marker)"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — dzwonek tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'hire_missing_contract'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0452 odmawia: notifications ma wpisy hire_missing_contract, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(ADD_BLACKLISTED_AT)
    op.execute(ADD_BLACKLISTED_BY)
    op.execute(ADD_BLACKLIST_REASON)
    op.execute(RETIRE_MANUAL_EMPLOYMENT)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS blacklist_reason")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS blacklisted_by_user_id")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS blacklisted_at")
