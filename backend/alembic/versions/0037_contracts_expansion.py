"""Contracts module expansion: termination, equipment, benchmarks, engagement,
consultant location, notes/calls linkage, extended alert thresholds

Revision ID: 0037_contracts_expansion
Revises: 0036_microsoft365
Create Date: 2026-04-22 18:00:00.000000

Scope of this migration (Nexus Contracts module expansion):

1. `contracts` — new columns:
   - termination_reason (enum ContractTerminationReason) — structured reason
   - termination_lessons (Text) — TAC-only "what we learned"
   - terminated_at (Date) — actual termination date (may differ from end_date)
   - target_rate_min / target_rate_max (Integer) — desired range
   - client_order_end_date (Date) — end of the purchase order on the client side
     (used by alert task; often differs from the consultant's contract end_date)

2. `candidates` — new columns:
   - engagement flags (5x Boolean): is_ambassador, wants_to_verify_candidates,
     open_to_side_projects, open_to_sales_support, open_to_expert_consult
   - engagement_notes (Text)
   - structured location: city, country (ISO-2), region, hub_city,
     latitude, longitude

3. `notes.contract_id` FK → contracts(id) ON DELETE SET NULL (nullable).
4. `calls.contract_id` FK → contracts(id) ON DELETE SET NULL (nullable).

5. New table `contract_equipment` — inventory items handed over to the
   consultant per contract (laptop, phone, badge, token…), with return tracking.

6. New table `rate_benchmarks` — market rate benchmarks (Hays, No Fluff Jobs
   etc.) for cross-referencing contract rates.

7. `notificationtype` enum — new values:
   contract_ending_90d, equipment_return_due_14d, client_order_ending_30d

Pattern: idempotent `DO $$ IF NOT EXISTS $$` blocks + `CREATE INDEX IF NOT
EXISTS` — safe under `entrypoint.sh` re-runs and Base.metadata.create_all()
in DEV.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0037_contracts_expansion"
down_revision = "0036_microsoft365"
branch_labels = None
depends_on = None


_TERMINATION_REASONS = (
    "poached_by_client",
    "project_ended",
    "client_budget_cut",
    "performance_issue",
    "consultant_resigned",
    "better_offer",
    "personal_reasons",
    "contract_breach",
    "mutual_agreement",
    "other",
)

_EQUIPMENT_ITEM_TYPES = (
    "laptop",
    "phone",
    "monitor",
    "headset",
    "docking_station",
    "security_token",
    "keycard",
    "sim_card",
    "other",
)

_EQUIPMENT_OWNERS = ("ours", "client")

_EQUIPMENT_RETURN_STATUSES = ("pending", "returned", "lost", "written_off")

_SENIORITY_LEVELS = ("junior", "mid", "senior", "expert", "principal")

_NEW_NOTIF_TYPES = (
    "contract_ending_90d",
    "equipment_return_due_14d",
    "client_order_ending_30d",
)


def upgrade() -> None:
    # ── New enum types (idempotent) ───────────────────────────────────────
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contractterminationreason') THEN
                CREATE TYPE contractterminationreason AS ENUM (
                    {", ".join(f"'{v}'" for v in _TERMINATION_REASONS)}
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentitemtype') THEN
                CREATE TYPE equipmentitemtype AS ENUM (
                    {", ".join(f"'{v}'" for v in _EQUIPMENT_ITEM_TYPES)}
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentowner') THEN
                CREATE TYPE equipmentowner AS ENUM (
                    {", ".join(f"'{v}'" for v in _EQUIPMENT_OWNERS)}
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentreturnstatus') THEN
                CREATE TYPE equipmentreturnstatus AS ENUM (
                    {", ".join(f"'{v}'" for v in _EQUIPMENT_RETURN_STATUSES)}
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'seniorityleveltype') THEN
                CREATE TYPE seniorityleveltype AS ENUM (
                    {", ".join(f"'{v}'" for v in _SENIORITY_LEVELS)}
                );
            END IF;
        END$$;
        """
    )

    # notificationtype: ALTER TYPE ADD VALUE requires autocommit.
    with op.get_context().autocommit_block():
        for value in _NEW_NOTIF_TYPES:
            op.execute(
                f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
            )

    # ── contracts: termination + target + client_order fields ─────────────
    for column_sql in (
        "ADD COLUMN IF NOT EXISTS termination_reason contractterminationreason",
        "ADD COLUMN IF NOT EXISTS termination_lessons TEXT",
        "ADD COLUMN IF NOT EXISTS terminated_at DATE",
        "ADD COLUMN IF NOT EXISTS target_rate_min INTEGER",
        "ADD COLUMN IF NOT EXISTS target_rate_max INTEGER",
        "ADD COLUMN IF NOT EXISTS client_order_end_date DATE",
    ):
        op.execute(f"ALTER TABLE contracts {column_sql}")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_termination_reason "
        "ON contracts (termination_reason)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_client_order_end_date "
        "ON contracts (client_order_end_date)"
    )

    # ── candidates: engagement flags + structured location ────────────────
    for column_sql in (
        # Engagement flags — all default FALSE, NOT NULL.
        "ADD COLUMN IF NOT EXISTS is_ambassador BOOLEAN NOT NULL DEFAULT false",
        "ADD COLUMN IF NOT EXISTS wants_to_verify_candidates BOOLEAN NOT NULL DEFAULT false",
        "ADD COLUMN IF NOT EXISTS open_to_side_projects BOOLEAN NOT NULL DEFAULT false",
        "ADD COLUMN IF NOT EXISTS open_to_sales_support BOOLEAN NOT NULL DEFAULT false",
        "ADD COLUMN IF NOT EXISTS open_to_expert_consult BOOLEAN NOT NULL DEFAULT false",
        "ADD COLUMN IF NOT EXISTS engagement_notes TEXT",
        # Location.
        "ADD COLUMN IF NOT EXISTS city VARCHAR(120)",
        "ADD COLUMN IF NOT EXISTS country VARCHAR(2)",
        "ADD COLUMN IF NOT EXISTS region VARCHAR(120)",
        "ADD COLUMN IF NOT EXISTS hub_city VARCHAR(120)",
        "ADD COLUMN IF NOT EXISTS latitude NUMERIC(9,6)",
        "ADD COLUMN IF NOT EXISTS longitude NUMERIC(9,6)",
    ):
        op.execute(f"ALTER TABLE candidates {column_sql}")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_hub_city ON candidates (hub_city)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_country ON candidates (country)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_is_ambassador "
        "ON candidates (is_ambassador) WHERE is_ambassador = true"
    )

    # Best-effort seed of hub_city from legacy location string.
    # Run only for rows that still have NULL hub_city so re-runs are safe.
    op.execute(
        """
        UPDATE candidates
           SET hub_city = CASE
               WHEN location ILIKE '%warsza%' OR location ILIKE '%warsaw%' THEN 'Warszawa'
               WHEN location ILIKE '%krak%' OR location ILIKE '%cracow%' THEN 'Kraków'
               WHEN location ILIKE '%wrocław%' OR location ILIKE '%wroclaw%' THEN 'Wrocław'
               WHEN location ILIKE '%gdańs%' OR location ILIKE '%gdansk%'
                 OR location ILIKE '%gdyn%' OR location ILIKE '%sopot%'
                 OR location ILIKE '%trójmiast%' OR location ILIKE '%trojmiast%' THEN 'Trójmiasto'
               WHEN location ILIKE '%poznań%' OR location ILIKE '%poznan%' THEN 'Poznań'
               WHEN location ILIKE '%katowic%' OR location ILIKE '%gliwic%'
                 OR location ILIKE '%śląs%' OR location ILIKE '%slask%' THEN 'Śląsk'
               WHEN location ILIKE '%remote%' OR location ILIKE '%zdalnie%' THEN 'Remote'
               ELSE NULL
           END,
           country = COALESCE(country, 'PL')
         WHERE hub_city IS NULL AND location IS NOT NULL AND location <> ''
        """
    )

    # ── notes.contract_id + calls.contract_id FKs ─────────────────────────
    op.execute(
        "ALTER TABLE notes "
        "ADD COLUMN IF NOT EXISTS contract_id INTEGER "
        "REFERENCES contracts(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notes_contract_id ON notes (contract_id)"
    )

    op.execute(
        "ALTER TABLE calls "
        "ADD COLUMN IF NOT EXISTS contract_id INTEGER "
        "REFERENCES contracts(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_contract_id ON calls (contract_id)"
    )

    # ── contract_equipment table ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_equipment (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            item_type equipmentitemtype NOT NULL,
            owner equipmentowner NOT NULL,
            brand_model VARCHAR(200),
            serial_number VARCHAR(120),
            description TEXT,
            deposit_amount INTEGER,
            deposit_currency VARCHAR(3),
            handed_over_date DATE,
            return_due_date DATE,
            returned_date DATE,
            return_status equipmentreturnstatus NOT NULL DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_equipment_contract_id "
        "ON contract_equipment (contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_equipment_serial_number "
        "ON contract_equipment (serial_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_equipment_return_due "
        "ON contract_equipment (return_status, return_due_date) "
        "WHERE return_status = 'pending'"
    )

    # ── rate_benchmarks table ─────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_benchmarks (
            id SERIAL PRIMARY KEY,
            role VARCHAR(160) NOT NULL,
            seniority seniorityleveltype,
            currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
            rate_unit rateunit NOT NULL,
            market_min INTEGER,
            market_median INTEGER NOT NULL,
            market_max INTEGER,
            source VARCHAR(200) NOT NULL,
            source_date DATE NOT NULL,
            location VARCHAR(120),
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rate_benchmarks_role_seniority_location "
        "ON rate_benchmarks (role, seniority, location)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_benchmarks")
    op.execute("DROP TABLE IF EXISTS contract_equipment")

    op.execute("DROP INDEX IF EXISTS ix_calls_contract_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='calls' AND column_name='contract_id'
            ) THEN
                ALTER TABLE calls DROP COLUMN contract_id;
            END IF;
        END$$;
        """
    )

    op.execute("DROP INDEX IF EXISTS ix_notes_contract_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='notes' AND column_name='contract_id'
            ) THEN
                ALTER TABLE notes DROP COLUMN contract_id;
            END IF;
        END$$;
        """
    )

    # candidates — drop new columns (order doesn't matter for DROP).
    for col in (
        "is_ambassador",
        "wants_to_verify_candidates",
        "open_to_side_projects",
        "open_to_sales_support",
        "open_to_expert_consult",
        "engagement_notes",
        "city",
        "country",
        "region",
        "hub_city",
        "latitude",
        "longitude",
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='candidates' AND column_name='{col}'
                ) THEN
                    ALTER TABLE candidates DROP COLUMN {col};
                END IF;
            END$$;
            """
        )

    op.execute("DROP INDEX IF EXISTS ix_candidates_hub_city")
    op.execute("DROP INDEX IF EXISTS ix_candidates_country")
    op.execute("DROP INDEX IF EXISTS ix_candidates_is_ambassador")

    # contracts — drop new columns.
    op.execute("DROP INDEX IF EXISTS ix_contracts_termination_reason")
    op.execute("DROP INDEX IF EXISTS ix_contracts_client_order_end_date")
    for col in (
        "termination_reason",
        "termination_lessons",
        "terminated_at",
        "target_rate_min",
        "target_rate_max",
        "client_order_end_date",
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='contracts' AND column_name='{col}'
                ) THEN
                    ALTER TABLE contracts DROP COLUMN {col};
                END IF;
            END$$;
            """
        )

    # Drop custom types we added. Safe because the tables/columns using them
    # are already gone above. notificationtype is *not* dropped — ALTER TYPE
    # DROP VALUE isn't supported in Postgres and old rows may still reference
    # the new values.
    for type_name in (
        "seniorityleveltype",
        "equipmentreturnstatus",
        "equipmentowner",
        "equipmentitemtype",
        "contractterminationreason",
    ):
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
