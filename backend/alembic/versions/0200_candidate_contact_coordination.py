"""Candidate-global contact queue and read-only Traffit intake durability.

Revision ID: 0200_candidate_contact_coordination
Revises: 0199_candidate_stage_removals
"""

from alembic import op


revision = "0200_candidate_contact_coordination"
down_revision = "0199_candidate_stage_removals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain VARCHAR statuses are intentional: no PostgreSQL enum lifecycle.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_contact_cases (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL
                REFERENCES candidates(id) ON DELETE CASCADE,
            owner_user_id INTEGER
                REFERENCES users(id) ON DELETE SET NULL,
            previous_owner_user_id INTEGER
                REFERENCES users(id) ON DELETE SET NULL,
            primary_job_id INTEGER
                REFERENCES jobs(id) ON DELETE SET NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'unassigned',
            due_at TIMESTAMPTZ,
            cooldown_until TIMESTAMPTZ,
            attempt_count SMALLINT NOT NULL DEFAULT 0,
            cycle INTEGER NOT NULL DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1,
            queue_slot SMALLINT,
            assigned_at TIMESTAMPTZ,
            last_attempt_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            blocked_phone_value VARCHAR(30),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_contact_cases_candidate_id
                UNIQUE (candidate_id),
            CONSTRAINT ck_candidate_contact_cases_state CHECK (
                state IN (
                    'unassigned', 'awaiting_capacity', 'queued',
                    'callback_due', 'cooldown', 'handoff_pending',
                    'blocked_no_phone', 'suppressed', 'completed', 'cancelled'
                )
            ),
            CONSTRAINT ck_candidate_contact_cases_queue_slot CHECK (
                queue_slot IS NULL OR queue_slot BETWEEN 1 AND 20
            ),
            CONSTRAINT ck_candidate_contact_cases_slot_owner CHECK (
                queue_slot IS NULL OR owner_user_id IS NOT NULL
            ),
            CONSTRAINT ck_candidate_contact_cases_actionable_slot CHECK (
                (state IN ('queued', 'callback_due')) =
                (queue_slot IS NOT NULL)
            ),
            CONSTRAINT ck_candidate_contact_cases_attempt_count
                CHECK (attempt_count >= 0),
            CONSTRAINT ck_candidate_contact_cases_cycle CHECK (cycle >= 1),
            CONSTRAINT ck_candidate_contact_cases_version CHECK (version >= 1)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_candidate_contact_cases_owner_slot "
        "ON candidate_contact_cases (owner_user_id, queue_slot) "
        "WHERE queue_slot IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_cases_state_due "
        "ON candidate_contact_cases (state, due_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_cases_owner_state "
        "ON candidate_contact_cases (owner_user_id, state)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_contact_opportunities (
            id SERIAL PRIMARY KEY,
            case_id INTEGER NOT NULL
                REFERENCES candidate_contact_cases(id) ON DELETE CASCADE,
            candidate_id INTEGER NOT NULL
                REFERENCES candidates(id) ON DELETE CASCADE,
            -- Durable tombstone: the job-delete hook closes the opportunity,
            -- while this denormalized id preserves its recruitment identity.
            job_id INTEGER NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'manual',
            source_external_ref VARCHAR(255),
            linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            source_cursor_created_at TIMESTAMPTZ,
            source_cursor_external_id VARCHAR(255),
            outcome VARCHAR(32),
            presented_at TIMESTAMPTZ,
            meeting_event_id INTEGER
                REFERENCES calendar_events(id) ON DELETE SET NULL,
            meeting_scheduled_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ,
            closed_reason VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_contact_opportunities_candidate_job
                UNIQUE (candidate_id, job_id),
            CONSTRAINT uq_candidate_contact_opportunities_case_job
                UNIQUE (case_id, job_id),
            CONSTRAINT ck_candidate_contact_opportunities_source CHECK (
                source IN ('pipeline', 'shortlist', 'traffit', 'manual')
            ),
            CONSTRAINT ck_candidate_contact_opportunities_outcome CHECK (
                outcome IS NULL OR outcome IN (
                    'interested', 'maybe', 'not_interested', 'not_presented'
                )
            )
        )
        """
    )
    op.execute(
        "ALTER TABLE candidate_contact_opportunities "
        "ADD COLUMN IF NOT EXISTS linked_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )
    op.execute(
        "ALTER TABLE candidate_contact_opportunities "
        "ADD COLUMN IF NOT EXISTS source_cursor_created_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE candidate_contact_opportunities "
        "ADD COLUMN IF NOT EXISTS source_cursor_external_id VARCHAR(255)"
    )
    # Earlier pre-review variants used ON DELETE CASCADE.  Drop it
    # idempotently so an already-created dormant schema also retains closed
    # opportunities after a physical Job deletion.
    op.execute(
        "ALTER TABLE candidate_contact_opportunities "
        "DROP CONSTRAINT IF EXISTS "
        "candidate_contact_opportunities_job_id_fkey"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_candidate_contact_opportunities_candidate_id "
        "ON candidate_contact_opportunities (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_opportunities_job_id "
        "ON candidate_contact_opportunities (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_opportunities_case_open "
        "ON candidate_contact_opportunities (case_id, closed_at)"
    )

    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_case_id INTEGER")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_outcome VARCHAR(32)")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_source VARCHAR(32)")
    op.execute(
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS "
        "contact_idempotency_key VARCHAR(160)"
    )
    op.execute(
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_request_hash VARCHAR(64)"
    )
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_at TIMESTAMPTZ")
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE calls
                ADD CONSTRAINT fk_calls_contact_case_id
                FOREIGN KEY (contact_case_id)
                REFERENCES candidate_contact_cases(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE calls
                ADD CONSTRAINT ck_calls_contact_outcome CHECK (
                    contact_outcome IS NULL OR contact_outcome IN (
                        'connected', 'no_answer', 'callback_requested',
                        'wrong_number', 'do_not_contact'
                    )
                );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_contact_case_id ON calls (contact_case_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_calls_contact_idempotency_key "
        "ON calls (contact_idempotency_key) "
        "WHERE contact_idempotency_key IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_contact_events (
            id BIGSERIAL PRIMARY KEY,
            case_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            opportunity_id INTEGER,
            job_id INTEGER,
            actor_user_id INTEGER,
            call_id INTEGER,
            event_type VARCHAR(64) NOT NULL,
            from_state VARCHAR(32),
            to_state VARCHAR(32),
            idempotency_key VARCHAR(160),
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_events_candidate_id "
        "ON candidate_contact_events (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_events_case_occurred "
        "ON candidate_contact_events (case_id, occurred_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_candidate_contact_events_idempotency "
        "ON candidate_contact_events (idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_candidate_contact_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'candidate_contact_events is append-only; append a correction event'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_candidate_contact_events_immutable "
        "ON candidate_contact_events"
    )
    op.execute(
        """
        CREATE TRIGGER trg_candidate_contact_events_immutable
        BEFORE UPDATE OR DELETE ON candidate_contact_events
        FOR EACH ROW EXECUTE FUNCTION reject_candidate_contact_event_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_contact_traffit_cursors (
            stream VARCHAR(64) PRIMARY KEY,
            cursor_created_at TIMESTAMPTZ,
            cursor_external_id VARCHAR(255),
            last_attempt_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            status VARCHAR(32),
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_contact_traffit_ledger (
            id BIGSERIAL PRIMARY KEY,
            external_event_id VARCHAR(255) NOT NULL,
            source_created_at TIMESTAMPTZ NOT NULL,
            candidate_external_id VARCHAR(255),
            job_external_id VARCHAR(255),
            candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
            job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            case_id INTEGER
                REFERENCES candidate_contact_cases(id) ON DELETE SET NULL,
            opportunity_id INTEGER
                REFERENCES candidate_contact_opportunities(id) ON DELETE SET NULL,
            status VARCHAR(32) NOT NULL,
            payload_hash VARCHAR(64) NOT NULL,
            raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TIMESTAMPTZ,
            error TEXT,
            processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_contact_traffit_ledger_external_event
                UNIQUE (external_event_id),
            CONSTRAINT ck_candidate_contact_traffit_ledger_status
                CHECK (status IN ('processed', 'exception')),
            CONSTRAINT ck_candidate_contact_traffit_ledger_attempts
                CHECK (attempts >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_candidate_contact_traffit_ledger_candidate_id "
        "ON candidate_contact_traffit_ledger (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_contact_traffit_ledger_job_id "
        "ON candidate_contact_traffit_ledger (job_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_contact_traffit_ledger")
    op.execute("DROP TABLE IF EXISTS candidate_contact_traffit_cursors")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_candidate_contact_events_immutable "
        "ON candidate_contact_events"
    )
    op.execute("DROP TABLE IF EXISTS candidate_contact_events")
    op.execute("DROP FUNCTION IF EXISTS reject_candidate_contact_event_mutation()")
    op.execute("DROP INDEX IF EXISTS ux_calls_contact_idempotency_key")
    op.execute("DROP INDEX IF EXISTS ix_calls_contact_case_id")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS ck_calls_contact_outcome")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS fk_calls_contact_case_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS callback_at")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS contact_request_hash")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS contact_idempotency_key")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS contact_source")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS contact_outcome")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS contact_case_id")
    op.execute("DROP TABLE IF EXISTS candidate_contact_opportunities")
    op.execute("DROP TABLE IF EXISTS candidate_contact_cases")
