"""Unbounded priority positions and durable COMPASS allocation.

Revision ID: 0277_recruitment_allocation
Revises: 0276_compass_workdays_sync_state
"""

from alembic import op

revision = "0277_recruitment_allocation"
down_revision = "0276_compass_workdays_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'recruitment_allocation_alert'"
    )
    op.execute(
        "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS operational_owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_operational_owner_id ON calendar_events(operational_owner_id)"
    )
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ADD COLUMN IF NOT EXISTS position INTEGER
    """)
    op.execute("""
        UPDATE recruitment_priority_assignments
        SET position = ascii(rank::text) - 64 WHERE position IS NULL
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ALTER COLUMN position SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ALTER COLUMN rank DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments
            DROP CONSTRAINT IF EXISTS ck_priority_assignment_extra_slot_reason
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments
            DROP CONSTRAINT IF EXISTS uq_priority_assignment_member_position
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ADD CONSTRAINT uq_priority_assignment_member_position
            UNIQUE (plan_member_id, position) DEFERRABLE INITIALLY DEFERRED
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments
            DROP CONSTRAINT IF EXISTS ck_priority_assignment_position_positive
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ADD CONSTRAINT ck_priority_assignment_position_positive
            CHECK (position > 0)
    """)
    op.execute("""
        -- Older app instances can continue inserting A-E during deployment.
        CREATE OR REPLACE FUNCTION public.priority_assignment_position_compat()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NEW.position IS NULL THEN
                NEW.position := ascii(NEW.rank::text) - 64;
            ELSIF TG_OP = 'UPDATE' AND NEW.rank IS DISTINCT FROM OLD.rank
                AND NEW.position IS NOT DISTINCT FROM OLD.position AND NEW.rank IS NOT NULL THEN
                NEW.position := ascii(NEW.rank::text) - 64;
            END IF;
            NEW.rank := CASE WHEN NEW.position BETWEEN 1 AND 5
                THEN chr(64 + NEW.position)::public.priorityrank ELSE NULL END;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS priority_assignment_position_compat ON recruitment_priority_assignments
    """)
    op.execute("""
        CREATE TRIGGER priority_assignment_position_compat BEFORE INSERT OR UPDATE
            ON recruitment_priority_assignments FOR EACH ROW
            EXECUTE FUNCTION public.priority_assignment_position_compat()
    """)
    op.execute("""
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS favorite_sourcing_paused BOOLEAN NOT NULL DEFAULT false
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS workforce_availability_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), snapshot JSONB,
            last_success_at TIMESTAMPTZ, last_attempt_at TIMESTAMPTZ, last_error VARCHAR(200)
        )
    """)
    op.execute("""
        INSERT INTO workforce_availability_state(id) VALUES (1) ON CONFLICT DO NOTHING
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS recruitment_allocation_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode VARCHAR(10) NOT NULL DEFAULT 'shadow' CHECK (mode IN ('off', 'shadow', 'auto')),
            last_run_at TIMESTAMPTZ, last_error VARCHAR(200), stats JSONB
        )
    """)
    op.execute("""
        INSERT INTO recruitment_allocation_state(id) VALUES (1) ON CONFLICT DO NOTHING
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS recruitment_allocation_requests (
            id SERIAL PRIMARY KEY,
            job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
            requested_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            channel VARCHAR(20) NOT NULL DEFAULT 'linkedin',
            status VARCHAR(20) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'assigned', 'cancelled')),
            due_at TIMESTAMPTZ, evaluated_at TIMESTAMPTZ,
            assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            suggested_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reason VARCHAR(100), decision JSONB,
            matching_snapshot_id INTEGER REFERENCES proposal_snapshots(id) ON DELETE SET NULL,
            matching_attempts INTEGER NOT NULL DEFAULT 0, matching_claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_recruitment_allocation_requests_status ON recruitment_allocation_requests(status)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS recruitment_allocation_events (
            id SERIAL PRIMARY KEY, topic VARCHAR(80) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_recruitment_allocation_events_processed_at ON recruitment_allocation_events(processed_at)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM recruitment_priority_assignments
                WHERE position > 5 OR (rank IN ('D','E') AND NULLIF(btrim(extra_slot_reason), '') IS NULL))
            THEN RAISE EXCEPTION 'Unbounded assignments cannot be downgraded to A-E; disable automatic allocation instead';
            END IF;
        END $$
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS priority_assignment_position_compat ON recruitment_priority_assignments
    """)
    op.execute("""
        DROP FUNCTION IF EXISTS public.priority_assignment_position_compat()
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments DROP CONSTRAINT IF EXISTS uq_priority_assignment_member_position
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments DROP CONSTRAINT IF EXISTS ck_priority_assignment_position_positive
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments DROP COLUMN IF EXISTS position
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ALTER COLUMN rank SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE recruitment_priority_assignments ADD CONSTRAINT ck_priority_assignment_extra_slot_reason
            CHECK (rank NOT IN ('D', 'E') OR NULLIF(btrim(extra_slot_reason), '') IS NOT NULL)
    """)
    op.execute("""
        ALTER TABLE jobs DROP COLUMN IF EXISTS favorite_sourcing_paused
    """)
    op.execute("""
        DROP TABLE IF EXISTS recruitment_allocation_events
    """)
    op.execute("""
        DROP TABLE IF EXISTS recruitment_allocation_requests
    """)
    op.execute("""
        DROP TABLE IF EXISTS recruitment_allocation_state
    """)
    op.execute("""
        DROP TABLE IF EXISTS workforce_availability_state
    """)
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS operational_owner_id")
    # PostgreSQL enum labels are additive. The unused notification label is safe
    # to retain, avoiding a destructive rebuild of production notifications.
