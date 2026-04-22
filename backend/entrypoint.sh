#!/bin/bash
set -e

export PYTHONPATH=/app:${PYTHONPATH}

echo "=== Nexus ATS Backend Starting ==="

# Wait for postgres to be ready
echo "Waiting for database..."
until python -c "
import asyncio, asyncpg, os

async def check():
    url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://nexus:nexus@postgres:5432/nexus')
    url = url.replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    await conn.close()
    print('Database ready!')

asyncio.run(check())
" 2>/dev/null; do
    echo "Database not ready, retrying in 2s..."
    sleep 2
done

# Run migrations
# The alembic.ini lives in /app/alembic/ but script_location=alembic points to /app/alembic
# Run from /app so that 'alembic' dir is found correctly
echo "Running database migrations..."
cd /app
# Tolerate alembic failures in dev: multiple in-flight feature branches can
# produce duplicate-revision or multi-head states. In DEBUG mode the app
# falls back to Base.metadata.create_all() on startup, so tables still exist.
# Production should never hit this path (clean single-head chain on main).
alembic -c alembic/alembic.ini upgrade heads 2>&1 || echo "alembic upgrade failed (likely multi-head in dev); continuing via Base.metadata.create_all"

# Safety net: alembic upgrade sometimes bails halfway through the Phase 8
# multi-head graph (see project_alembic_state memory). The ORM expects
# several columns that those migrations ship; backfill them idempotently
# so ORM queries don't crash with UndefinedColumnError. Non-fatal — bail
# back to alembic-only behavior if anything unexpected happens.
echo "Backfilling critical Phase 8 columns (idempotent)..."
python - <<'PY' || echo "column backfill failed; continuing"
import asyncio, os
import asyncpg

# Every statement here is idempotent. Order matters for enum ADD VALUE
# (must run outside transaction) vs column adds (can run in tx).
_ENUM_STATEMENTS = [
    # userrole: head_of_recruitment (migration 0029_notifications_triggers)
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'head_of_recruitment'",
    # notificationtype: 5 trigger types + champion_profile_updated
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'dl_stage_stale_6h'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_feedback_eobd'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'powercalling_kpi'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_feedback_1h'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'stage_stuck_7d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'champion_profile_updated'",
    # Kontrakty expansion (migration 0037) notificationtype extensions
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'contract_ending_90d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'equipment_return_due_14d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_order_ending_30d'",
    # availabilitystatus (migration wyroznienia_availability) — CREATE TYPE
    # must be gated with DO $$ because PG lacks CREATE TYPE IF NOT EXISTS.
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'availabilitystatus') THEN
            CREATE TYPE availabilitystatus AS ENUM (
                'actively_looking', 'open_to_offers', 'not_looking', 'unknown'
            );
        END IF;
    END $$""",
    # Kontrakty expansion (migration 0037) enum types
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contractterminationreason') THEN
            CREATE TYPE contractterminationreason AS ENUM (
                'poached_by_client', 'project_ended', 'client_budget_cut',
                'performance_issue', 'consultant_resigned', 'better_offer',
                'personal_reasons', 'contract_breach', 'mutual_agreement', 'other'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentitemtype') THEN
            CREATE TYPE equipmentitemtype AS ENUM (
                'laptop', 'phone', 'monitor', 'headset', 'docking_station',
                'security_token', 'keycard', 'sim_card', 'other'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentowner') THEN
            CREATE TYPE equipmentowner AS ENUM ('ours', 'client');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentreturnstatus') THEN
            CREATE TYPE equipmentreturnstatus AS ENUM (
                'pending', 'returned', 'lost', 'written_off'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'seniorityleveltype') THEN
            CREATE TYPE seniorityleveltype AS ENUM (
                'junior', 'mid', 'senior', 'expert', 'principal'
            );
        END IF;
    END $$""",
]

_COLUMN_STATEMENTS = [
    # users (migration 0035_onboarding_and_job_sourcing)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed_at TIMESTAMPTZ",
    # jobs (migration 0035_onboarding_and_job_sourcing + 0029_notifications_triggers)
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS needs_sourcing BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS delivery_lead_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS competence_category_id INTEGER",
    # candidates (migration 0030_candidate_created_by + 0033_cc_entities +
    # wyroznienia_availability)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS competence_category_id INTEGER",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS availability_status availabilitystatus NOT NULL DEFAULT 'unknown'",
    # notifications (migration 0029_notifications_triggers)
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_type VARCHAR(50)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_id INTEGER",
    # contracts (migration 0037_contracts_expansion)
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS termination_reason contractterminationreason",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS termination_lessons TEXT",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS terminated_at DATE",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS target_rate_min INTEGER",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS target_rate_max INTEGER",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS client_order_end_date DATE",
    # candidates engagement flags (migration 0037_contracts_expansion)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS is_ambassador BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS wants_to_verify_candidates BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_side_projects BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_sales_support BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_expert_consult BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS engagement_notes TEXT",
    # candidates structured location (migration 0037_contracts_expansion)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS city VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS country VARCHAR(2)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS region VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS hub_city VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS latitude NUMERIC(9,6)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS longitude NUMERIC(9,6)",
    # notes + calls contract_id FK (migration 0037_contracts_expansion)
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
]

_DATA_STATEMENTS = [
    # Pre-flag roles that don't need onboarding (mirrors migration 0035 step)
    """UPDATE users
          SET profile_completed = TRUE,
              profile_completed_at = COALESCE(profile_completed_at, NOW())
        WHERE profile_completed = FALSE
          AND role::text NOT IN ('delivery_lead', 'recruiter')""",
]


async def backfill():
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://nexus:nexus@postgres:5432/nexus")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Enum ADD VALUE must run in autocommit mode.
    conn = await asyncpg.connect(url)
    try:
        for stmt in _ENUM_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill enum skip: {stmt!r} -> {e!r}")
        for stmt in _COLUMN_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill column skip: {stmt!r} -> {e!r}")
        for stmt in _DATA_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill data skip: {stmt!r} -> {e!r}")
        print("backfill: ok")
    finally:
        await conn.close()

asyncio.run(backfill())
PY

# Second safety net: create any tables that alembic failed to create.
# Uses SQLAlchemy Base.metadata.create_all — idempotent, skips existing
# tables. Handles the Phase 8 tables (competence_categories,
# user_competence_categories, candidate_invite_links, procedures,
# proposal_snapshots, champion_profile_suggestions, app_settings, etc.)
# that migrations 0029_*/0031_*/0032_*/0033_* would have created.
echo "Creating missing tables from SQLAlchemy metadata..."
python - <<'PY' || echo "metadata create_all failed; continuing"
import asyncio
from app.core.database import engine, Base
# Import all model modules so Base.metadata is fully populated.
import app.models  # noqa: F401

async def create_all():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("metadata create_all: ok")

asyncio.run(create_all())
PY

# Run seed (idempotent - skips if already seeded)
echo "Running seed data..."
python seed.py || echo "seed.py failed (likely pre-existing schema drift from unmerged branches); continuing"

# Ensure the dedicated Claude E2E admin account exists on every startup.
# Idempotent upsert — rotates password to the bootstrap value each boot unless
# CLAUDE_ADMIN_BOOTSTRAP_PWD is set in env. Non-fatal.
echo "Ensuring Claude admin account..."
python scripts/ensure_claude_admin.py || echo "ensure_claude_admin failed; continuing"

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
