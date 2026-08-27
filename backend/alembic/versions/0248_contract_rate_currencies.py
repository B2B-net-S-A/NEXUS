"""Split contract revenue and cost currencies.

Revision ID: 0248_contract_rate_currencies
Revises: 0247_job_favorite_candidate

The two columns intentionally remain nullable for legacy reads. Existing rows
are backfilled, while a compatibility trigger mirrors a legacy-only insert or
currency update into both explicit columns. New processes that update either
explicit side are left untouched, so mixed-currency contracts remain stable
during a rolling deployment.
"""

from alembic import op


revision = "0248_contract_rate_currencies"
down_revision = "0247_job_favorite_candidate"
branch_labels = None
depends_on = None


_BACKFILL_SQL = """
UPDATE contracts
SET rate_client_currency = COALESCE(
        rate_client_currency,
        NULLIF(UPPER(BTRIM(currency)), ''),
        'PLN'
    ),
    rate_candidate_currency = COALESCE(
        rate_candidate_currency,
        NULLIF(UPPER(BTRIM(currency)), ''),
        'PLN'
    )
WHERE rate_client_currency IS NULL
   OR rate_candidate_currency IS NULL
"""

_LEGACY_SYNC_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION sync_contract_rate_currencies_from_legacy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    normalized_currency VARCHAR(3) := COALESCE(
        NULLIF(UPPER(BTRIM(NEW.currency)), ''),
        'PLN'
    );
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.rate_client_currency := COALESCE(
            NEW.rate_client_currency,
            normalized_currency
        );
        NEW.rate_candidate_currency := COALESCE(
            NEW.rate_candidate_currency,
            normalized_currency
        );
    ELSIF NEW.currency IS DISTINCT FROM OLD.currency
       AND NEW.rate_client_currency IS NOT DISTINCT FROM OLD.rate_client_currency
       AND NEW.rate_candidate_currency IS NOT DISTINCT FROM OLD.rate_candidate_currency
    THEN
        -- An older application changed only the shared legacy field.
        NEW.rate_client_currency := normalized_currency;
        NEW.rate_candidate_currency := normalized_currency;
    END IF;
    IF COALESCE(
           NULLIF(UPPER(BTRIM(NEW.rate_client_currency)), ''),
           normalized_currency
       ) IS DISTINCT FROM COALESCE(
           NULLIF(UPPER(BTRIM(NEW.rate_candidate_currency)), ''),
           normalized_currency
       )
    THEN
        NEW.margin := NULL;
    END IF;
    RETURN NEW;
END;
$$
"""

_LEGACY_SYNC_TRIGGER_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_contract_rate_currencies_legacy_sync'
          AND tgrelid = 'contracts'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_contract_rate_currencies_legacy_sync
        BEFORE INSERT OR UPDATE OF
            margin, currency, rate_client_currency, rate_candidate_currency
        ON contracts
        FOR EACH ROW
        EXECUTE FUNCTION sync_contract_rate_currencies_from_legacy();
    END IF;
END
$$
"""


def upgrade() -> None:
    # The entrypoint safety net may have created these after a previously
    # interrupted Alembic run. Keep the real migration resumable so the
    # revision can still be stamped on the next healthy startup.
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
        "rate_client_currency VARCHAR(3) NULL"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
        "rate_candidate_currency VARCHAR(3) NULL"
    )
    op.execute(_BACKFILL_SQL)
    op.execute(_LEGACY_SYNC_FUNCTION_SQL)
    op.execute(_LEGACY_SYNC_TRIGGER_SQL)


def downgrade() -> None:
    # Lossy for mixed-currency contracts by definition; the retained legacy
    # ``currency`` already mirrors the client/revenue side.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_contract_rate_currencies_legacy_sync ON contracts"
    )
    op.execute("DROP FUNCTION IF EXISTS sync_contract_rate_currencies_from_legacy()")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS rate_candidate_currency")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS rate_client_currency")
