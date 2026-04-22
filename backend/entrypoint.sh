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
    # Phase 14 (migration 0043_interview_feedback) post-interview reminders
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t15'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t45'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t2h_escalation'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'suggest_next_step'",
    # KPI Coach (migration 0034_kpi_coach): dodaje value 'kpi_coach' do enum
    # notificationtype. Bez tego insert Notification(notification_type='kpi_coach')
    # crashuje z InvalidTextRepresentationError (DB enum nie zna wartości).
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'kpi_coach'",
    # Contractor module (migration 0046_backfill_contractor_drafts): auto-draft
    # + POST /api/contracts/{id}/activate oba używają 'contract_activated' jako
    # notification_type. Safety-net chroni prod przed crash-loopem gdyby alembic
    # head był wolniejszy niż restart aplikacji.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'contract_activated'",
    # Phase 14 dedicated enums for interview_feedback table
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'feedbacksource') THEN
            CREATE TYPE feedbacksource AS ENUM ('candidate_side', 'client_side');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'interestlevel') THEN
            CREATE TYPE interestlevel AS ENUM ('hot', 'warm', 'cold', 'dead');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'nextsteppreference') THEN
            CREATE TYPE nextsteppreference AS ENUM ('ready_for_next', 'need_info', 'pass');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'interviewdecision') THEN
            CREATE TYPE interviewdecision AS ENUM ('advance', 'reject', 'on_hold');
        END IF;
    END $$""",
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
    # AI CC matching (migration 0041_ai_cc_matching): enum for candidate→CC source
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'candidatecccategorysource') THEN
            CREATE TYPE candidatecccategorysource AS ENUM (
                'ai_auto', 'ai_suggested', 'manual'
            );
        END IF;
    END $$""",
    # Client Profile tab (migration 0048_job_close_reason): structured close
    # reason for "Przegrane rekrutacje". Safety-net bo prod może wyjść na live
    # przed ukończeniem upgrade'u alembica, a POST /jobs/{id}/close crashuje
    # bez tego enum + kolumny.
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobclosereason') THEN
            CREATE TYPE jobclosereason AS ENUM (
                'budget', 'internal_hire', 'competitor', 'paused',
                'filled_by_us', 'client_ghosted', 'other'
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
    # talent_pools centroid cache (pre-existing model fields — no dedicated migration)
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS centroid_vector_id VARCHAR(100)",
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS centroid_updated_at TIMESTAMPTZ",
    # talent_pool_memberships source tracking (migration 0040_talent_pool_source_event)
    "ALTER TABLE talent_pool_memberships ADD COLUMN IF NOT EXISTS source_event VARCHAR(50)",
    "ALTER TABLE talent_pool_memberships ADD COLUMN IF NOT EXISTS source_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_tpm_source_job_id ON talent_pool_memberships (source_job_id)",
    # AI CC matching (migration 0041_ai_cc_matching): columns on existing tables
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS competence_category_id INTEGER REFERENCES competence_categories(id) ON DELETE SET NULL",
    "ALTER TABLE job_collaborators ADD COLUMN IF NOT EXISTS removed_from_auto_cc BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE job_collaborators ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ",
    # KPI coach (bundled WIP, migration 0043_kpi_coach_nudger): bez tej kolumny
    # users.kpi_coach_enabled crashuje login query (ORM leci na nią).
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS kpi_coach_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    # Sourcer priority per CC (introduced by team_structure model for Head of
    # Recruitment matrix). Legacy deployments may be missing it.
    "ALTER TABLE user_competence_categories ADD COLUMN IF NOT EXISTS priority SMALLINT",
    "ALTER TABLE user_competence_categories DROP CONSTRAINT IF EXISTS ck_user_cc_priority",
    "ALTER TABLE user_competence_categories ADD CONSTRAINT ck_user_cc_priority CHECK (priority IS NULL OR priority IN (1, 2))",
    # Phase 14 (migration 0043_interview_feedback) needs_attention flag
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_calendar_events_needs_attention ON calendar_events (needs_attention) WHERE needs_attention = true",
    # Phase 14 interview_feedback table (migration 0043_interview_feedback).
    # Prod DEBUG=false → Base.metadata.create_all nie leci, alembic multi-head
    # często pada w dev → tabela musi być stworzona explicite idempotent tutaj.
    """CREATE TABLE IF NOT EXISTS interview_feedback (
        id SERIAL PRIMARY KEY,
        calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        feedback_source feedbacksource NOT NULL,
        overall_impression SMALLINT CHECK (overall_impression IS NULL OR overall_impression BETWEEN 1 AND 5),
        interest_level interestlevel,
        candidate_questions TEXT,
        concerns TEXT,
        next_step_preference nextsteppreference,
        technical_fit SMALLINT CHECK (technical_fit IS NULL OR technical_fit BETWEEN 1 AND 5),
        soft_fit SMALLINT CHECK (soft_fit IS NULL OR soft_fit BETWEEN 1 AND 5),
        overall_fit SMALLINT CHECK (overall_fit IS NULL OR overall_fit BETWEEN 1 AND 5),
        decision interviewdecision,
        client_questions TEXT,
        feedback_summary TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_interview_feedback_event_source UNIQUE (calendar_event_id, feedback_source)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_calendar_event_id ON interview_feedback (calendar_event_id)",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_candidate_id ON interview_feedback (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_job_id ON interview_feedback (job_id)",
    # Phase M365.1 drift: model ma kolumny od migracji 0036_microsoft365 ale
    # multi-head w dev skasowało ich auto-tworzenie. Bez tego SQLAlchemy fetche
    # eventów leci z UndefinedColumnError.
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS m365_series_master_id VARCHAR(255)",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS m365_change_key VARCHAR(100)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_events_m365_series_master_id ON calendar_events (m365_series_master_id)",
    # Client Profile tab + hit-ratio (migrations 0047_job_closed_at +
    # 0048_job_close_reason). Alembic was bailing on multi-head in prod, so
    # these never landed — safety-net avoids UndefinedColumnError on the
    # jobs SELECT and backend crash-loop.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_jobs_closed_at ON jobs(closed_at)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS close_reason jobclosereason",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS close_notes TEXT",
]

_DATA_STATEMENTS = [
    # Backfill closed_at for historical closed rows so reports sort by "real
    # close date" instead of NULL. Safe because only touches NULL rows.
    "UPDATE jobs SET closed_at = updated_at WHERE status = 'closed' AND closed_at IS NULL",
    # Pre-flag roles that don't need onboarding (mirrors migration 0035 step)
    """UPDATE users
          SET profile_completed = TRUE,
              profile_completed_at = COALESCE(profile_completed_at, NOW())
        WHERE profile_completed = FALSE
          AND role::text NOT IN ('delivery_lead', 'recruiter')""",
    # Seed 5 Competence Categories (migration 0033_cc_entities). Idempotent:
    # ON CONFLICT (slug) pomija duplikaty. Nie re-update'uje, bo Head of
    # Recruitment mógł zmodyfikować opis/keywords w UI.
    """INSERT INTO competence_categories (slug, name_pl, name_en, description, keywords, display_order, is_active)
       VALUES
         ('infrastructure_operations', 'Infrastruktura i Operacje', 'Infrastructure & Operations',
          'Zespoły odpowiedzialne za infrastrukturę, cloud, DevOps, SRE, platformę, sieć, bezpieczeństwo systemów, CI/CD oraz niezawodność.',
          '["devops","sre","site reliability","kubernetes","k8s","docker","terraform","ansible","jenkins","gitlab ci","github actions","aws","azure","gcp","cloud","linux","sysadmin","platform","networking","ci/cd","helm","prometheus","grafana","istio","observability","infrastructure"]'::jsonb,
          1, true),
         ('software_development', 'Rozwój Oprogramowania', 'Software Development',
          'Rozwój aplikacji frontend, backend, mobile, embedded. Frameworki webowe, języki programowania, architektura aplikacyjna.',
          '["frontend","backend","fullstack","full stack","full-stack","react","vue","angular","typescript","javascript","nextjs","next.js","nuxt","java","spring","spring boot","python","django","fastapi","flask","node","nodejs","node.js","go","golang","rust",".net","dotnet","c#","csharp","php","laravel","symfony","ruby","rails","mobile","ios","swift","android","kotlin","flutter","react native","embedded"]'::jsonb,
          2, true),
         ('data_ai', 'Dane i AI', 'Data & AI',
          'Inżynieria danych, data science, machine learning, analityka, BI.',
          '["data engineer","data scientist","ml engineer","machine learning","deep learning","ai","nlp","computer vision","llm","gpt","tensorflow","pytorch","spark","airflow","dbt","snowflake","bigquery","redshift","databricks","kafka","analytics","bi","tableau","power bi","looker","etl","elt","mlops","feature store","vector database"]'::jsonb,
          3, true),
         ('security_quality', 'Bezpieczeństwo i Jakość', 'Security & Quality',
          'Zapewnienie jakości, automatyzacja testów, cyberbezpieczeństwo, pentesting, compliance.',
          '["qa","quality assurance","tester","test automation","selenium","cypress","playwright","junit","pytest","security","pentester","appsec","application security","owasp","soc","siem","iso 27001","sast","dast","red team","blue team","penetration testing","vulnerability","cybersecurity","security engineer"]'::jsonb,
          4, true),
         ('management_delivery', 'Zarządzanie i Dostarczanie', 'Management & Delivery',
          'Zarządzanie produktem, projektami, zespołami, delivery.',
          '["pm","product manager","project manager","delivery lead","delivery manager","scrum master","agile coach","product owner","po","business analyst","ba","engineering manager","tech lead","team lead","cto","director","head of"]'::jsonb,
          5, true)
       ON CONFLICT (slug) DO NOTHING""",
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
