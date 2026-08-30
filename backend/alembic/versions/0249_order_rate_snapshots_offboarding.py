"""Order rate snapshots and durable MD consultant offboarding.

Revision ID: 0249_order_rate_snapshots_offboarding
Revises: 0248_contract_rate_currencies

The order-side finance fields are snapshots, not aliases of the current
contract.  Existing standalone orders receive the missing unit/currency
metadata exactly once, while their nullable rate amounts deliberately remain
nullable: that preserves the dated contract-schedule fallback instead of
freezing a potentially stale ``contracts.rate_*`` cache.  Multi-consultant
lines keep the module's canonical PLN/MD representation from ``md_rate_*``.

All DDL is restart-safe because production has an entrypoint safety net which
may have created some or all objects after an interrupted Alembic run.
"""

from alembic import op


revision = "0249_order_rate_snapshots_offboarding"
down_revision = "0248_contract_rate_currencies"
branch_labels = None
depends_on = None


_STANDALONE_RATE_BACKFILL_SQL = """
UPDATE client_orders AS order_row
SET rate_unit = COALESCE(contract.rate_unit, 'monthly'::rateunit),
    billing_hours_per_month = COALESCE(contract.billing_hours_per_month, 160),
    rate_client_currency = COALESCE(
        NULLIF(UPPER(BTRIM(contract.rate_client_currency)), ''),
        NULLIF(UPPER(BTRIM(contract.currency)), ''),
        'PLN'
    ),
    rate_candidate_currency = COALESCE(
        NULLIF(UPPER(BTRIM(contract.rate_candidate_currency)), ''),
        NULLIF(UPPER(BTRIM(contract.currency)), ''),
        'PLN'
    ),
    currency = COALESCE(
        NULLIF(UPPER(BTRIM(contract.rate_client_currency)), ''),
        NULLIF(UPPER(BTRIM(contract.currency)), ''),
        'PLN'
    )
FROM contracts AS contract
WHERE order_row.contract_id = contract.id
  AND order_row.order_group_id IS NULL
  AND (
      order_row.rate_unit IS NULL
      OR order_row.billing_hours_per_month IS NULL
      OR order_row.rate_client_currency IS NULL
      OR order_row.rate_candidate_currency IS NULL
  )
"""


_GROUP_RATE_BACKFILL_SQL = """
UPDATE client_orders AS order_row
SET rate_candidate = order_row.md_rate_cost,
    rate_client = order_row.md_rate_revenue,
    rate_unit = 'daily'::rateunit,
    billing_hours_per_month = 160,
    rate_client_currency = 'PLN',
    rate_candidate_currency = 'PLN',
    currency = 'PLN'
WHERE order_row.order_group_id IS NOT NULL
  AND (
      order_row.rate_unit IS NULL
      OR order_row.billing_hours_per_month IS NULL
      OR order_row.rate_client_currency IS NULL
      OR order_row.rate_candidate_currency IS NULL
  )
"""


_CREATE_OFFBOARDING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS client_order_offboarding_cases (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES client_orders(id) ON DELETE CASCADE,
    order_group_id INTEGER NULL
        REFERENCES client_order_groups(id) ON DELETE SET NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    version INTEGER NOT NULL DEFAULT 1,
    uses_shared_md_pool BOOLEAN NOT NULL DEFAULT FALSE,
    remaining_md_snapshot NUMERIC(16, 6) NOT NULL DEFAULT 0,
    rate_cost_snapshot NUMERIC(12, 2) NULL,
    rate_revenue_snapshot NUMERIC(12, 2) NULL,
    currency_snapshot VARCHAR(3) NULL,
    order_number_snapshot VARCHAR(64) NULL,
    resolution VARCHAR(16) NULL,
    target_order_id INTEGER NULL
        REFERENCES client_orders(id) ON DELETE SET NULL,
    rate_basis VARCHAR(16) NULL,
    resolution_payload JSONB NULL,
    resolved_at TIMESTAMPTZ NULL,
    resolved_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_order_offboarding_order_effective
        UNIQUE (order_id, effective_date),
    CONSTRAINT ck_client_order_offboarding_status
        CHECK (status IN ('pending', 'resolved')),
    CONSTRAINT ck_client_order_offboarding_resolution
        CHECK (resolution IS NULL OR resolution IN ('remove', 'transfer')),
    CONSTRAINT ck_client_order_offboarding_rate_basis
        CHECK (rate_basis IS NULL OR rate_basis IN ('departing', 'recipient')),
    CONSTRAINT ck_client_order_offboarding_resolution_state CHECK (
        (status = 'pending' AND resolution IS NULL AND resolved_at IS NULL
         AND target_order_id IS NULL AND rate_basis IS NULL)
        OR (status = 'resolved' AND resolution IS NOT NULL
            AND resolved_at IS NOT NULL)
    ),
    CONSTRAINT ck_client_order_offboarding_transfer_target CHECK (
        resolution IS DISTINCT FROM 'transfer'
        OR rate_basis IS NOT NULL
    ),
    CONSTRAINT ck_client_order_offboarding_remove_target CHECK (
        resolution IS DISTINCT FROM 'remove'
        OR (target_order_id IS NULL AND rate_basis IS NULL)
    ),
    CONSTRAINT ck_client_order_offboarding_version CHECK (version >= 1),
    CONSTRAINT ck_client_order_offboarding_remaining_nonnegative
        CHECK (remaining_md_snapshot >= 0)
)
"""


_ADD_ALERT_CASE_FK_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_attribute AS source_column
          ON source_column.attrelid = constraint_row.conrelid
         AND source_column.attnum = ANY(constraint_row.conkey)
        WHERE constraint_row.contype = 'f'
          AND constraint_row.conrelid = 'dl_alerts'::regclass
          AND constraint_row.confrelid =
              'client_order_offboarding_cases'::regclass
          AND source_column.attname = 'offboarding_case_id'
    ) THEN
        ALTER TABLE dl_alerts
            ADD CONSTRAINT fk_dl_alerts_offboarding_case
            FOREIGN KEY (offboarding_case_id)
            REFERENCES client_order_offboarding_cases(id)
            ON DELETE SET NULL NOT VALID;
    END IF;
END
$$
"""


_EVENT_CHECK_SQL = """
ALTER TABLE client_order_group_events
ADD CONSTRAINT ck_client_order_group_events_type CHECK (event_type IN (
    'utworzenie', 'dodanie_konsultanta', 'import_md',
    'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie',
    'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur',
    'transfer_md', 'zakonczenie_konsultanta', 'decyzja_md_wymagana',
    'usuniecie_puli_md', 'przeniesienie_puli_md'
))
"""


_ALERT_CHECK_SQL = """
ALTER TABLE dl_alerts
ADD CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN (
    'cost_order_exhausted', 'draft_consultant_unassigned',
    'md_budget_low', 'missing_revenue_rate', 'md_consultant_ended'
))
"""


def upgrade() -> None:
    # Add nullable first: the deterministic backfill must precede NOT NULL.
    # IF NOT EXISTS lets Alembic finish and stamp a revision whose entrypoint
    # safety net already installed the physical schema.
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
        "rate_candidate NUMERIC(12, 3) NULL"
    )
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS rate_unit rateunit NULL"
    )
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
        "billing_hours_per_month INTEGER NULL"
    )
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
        "rate_client_currency VARCHAR(3) NULL"
    )
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
        "rate_candidate_currency VARCHAR(3) NULL"
    )

    op.execute(_STANDALONE_RATE_BACKFILL_SQL)
    op.execute(_GROUP_RATE_BACKFILL_SQL)
    op.execute("ALTER TABLE client_orders ALTER COLUMN rate_unit SET DEFAULT 'monthly'")
    op.execute("ALTER TABLE client_orders ALTER COLUMN rate_unit SET NOT NULL")
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET DEFAULT 160"
    )
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET NOT NULL"
    )

    op.execute(_CREATE_OFFBOARDING_TABLE_SQL)
    op.execute(
        "ALTER TABLE dl_alerts ADD COLUMN IF NOT EXISTS "
        "offboarding_case_id INTEGER NULL"
    )
    op.execute(_ADD_ALERT_CASE_FK_SQL)

    # Both checks are closed domains. DROP + ADD must be in the same Alembic
    # transaction; merely swallowing duplicate_object would retain the old,
    # narrower definition under the same constraint name.
    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(_EVENT_CHECK_SQL)
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(_ALERT_CHECK_SQL)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_offboarding_cases_id "
        "ON client_order_offboarding_cases (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_offboarding_cases_contract_id "
        "ON client_order_offboarding_cases (contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_offboarding_pending "
        "ON client_order_offboarding_cases (client_id, effective_date) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_offboarding_contract_effective "
        "ON client_order_offboarding_cases (contract_id, effective_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_offboarding_group "
        "ON client_order_offboarding_cases (order_group_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dl_alerts_offboarding_case "
        "ON dl_alerts (offboarding_case_id)"
    )


def downgrade() -> None:
    # Remove rows using the widened domains before restoring the older checks.
    op.execute(
        "DELETE FROM client_order_group_events WHERE event_type IN ("
        "'zakonczenie_konsultanta', 'decyzja_md_wymagana', "
        "'usuniecie_puli_md', 'przeniesienie_puli_md')"
    )
    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(
        "ALTER TABLE client_order_group_events "
        "ADD CONSTRAINT ck_client_order_group_events_type CHECK (event_type IN ("
        "'utworzenie', 'dodanie_konsultanta', 'import_md', "
        "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
        "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
        "'transfer_md'))"
    )

    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'md_consultant_ended'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        "CHECK (alert_type IN ('cost_order_exhausted', "
        "'draft_consultant_unassigned', 'md_budget_low', "
        "'missing_revenue_rate'))"
    )
    op.execute("DROP INDEX IF EXISTS ix_dl_alerts_offboarding_case")
    op.execute("ALTER TABLE dl_alerts DROP COLUMN IF EXISTS offboarding_case_id")

    op.execute("DROP TABLE IF EXISTS client_order_offboarding_cases")

    op.execute(
        "ALTER TABLE client_orders DROP COLUMN IF EXISTS rate_candidate_currency"
    )
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS rate_client_currency")
    op.execute(
        "ALTER TABLE client_orders DROP COLUMN IF EXISTS billing_hours_per_month"
    )
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS rate_unit")
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS rate_candidate")
