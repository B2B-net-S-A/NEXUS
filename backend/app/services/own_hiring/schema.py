"""DDL rekrutacji własnej: jedno źródło dla migracji i ``entrypoint.sh``."""

STAGES = (
    "new",
    "invited",
    "no_response",
    "assistant",
    "teams",
    "office",
    "contract",
    "signed",
    "closed",
)
BUCKETS = ("match", "review", "filtered")
CLOSE_REASONS = ("rejected", "withdrawn")
BOOKING_KINDS = ("teams", "office")
BOOKING_STATUSES = ("active", "done", "cancelled")
BOOKED_VIA = ("link", "assistant", "owner")
SYNC_STATUSES = ("pending", "ok", "failed")

NOTIFICATION_TYPE = "own_hiring_update"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS own_hiring_processes (
        id SERIAL PRIMARY KEY,
        title VARCHAR(160) NOT NULL,
        owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        assistant_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        ad_titles JSONB NOT NULL DEFAULT '[]'::jsonb,
        settings JSONB NOT NULL DEFAULT '{}'::jsonb,
        intake_since TIMESTAMPTZ NOT NULL,
        intake_cursor INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    f"""CREATE TABLE IF NOT EXISTS own_hiring_applications (
        id SERIAL PRIMARY KEY,
        process_id INTEGER NOT NULL REFERENCES own_hiring_processes(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        stage VARCHAR(20) NOT NULL DEFAULT 'new'
            CHECK (stage IN ({_sql_list(STAGES)})),
        bucket VARCHAR(10) NOT NULL DEFAULT 'review'
            CHECK (bucket IN ({_sql_list(BUCKETS)})),
        filter_reason VARCHAR(20) NULL,
        evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        source_label VARCHAR(80) NULL,
        ad_title VARCHAR(300) NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        stage_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        token_nonce VARCHAR(32) NULL,
        token_sha256 VARCHAR(64) NULL,
        token_expires_at TIMESTAMPTZ NULL,
        invited_at TIMESTAMPTZ NULL,
        response_due_at TIMESTAMPTZ NULL,
        replied_at TIMESTAMPTZ NULL,
        handed_off_at TIMESTAMPTZ NULL,
        call_attempts INTEGER NOT NULL DEFAULT 0,
        callback_at TIMESTAMPTZ NULL,
        availability VARCHAR(20) NULL,
        expected_money VARCHAR(160) NULL,
        tech_level VARCHAR(20) NULL,
        teams_note TEXT NULL,
        office_note TEXT NULL,
        contract_kind VARCHAR(20) NULL,
        contract_sent_at TIMESTAMPTZ NULL,
        signed_at TIMESTAMPTZ NULL,
        close_reason VARCHAR(20) NULL
            CHECK (close_reason IS NULL OR close_reason IN ({_sql_list(CLOSE_REASONS)})),
        closed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_own_hiring_application UNIQUE (process_id, candidate_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS own_hiring_bookings (
        id SERIAL PRIMARY KEY,
        process_id INTEGER NOT NULL REFERENCES own_hiring_processes(id) ON DELETE CASCADE,
        application_id INTEGER NOT NULL REFERENCES own_hiring_applications(id) ON DELETE CASCADE,
        kind VARCHAR(10) NOT NULL CHECK (kind IN ({_sql_list(BOOKING_KINDS)})),
        status VARCHAR(10) NOT NULL DEFAULT 'active'
            CHECK (status IN ({_sql_list(BOOKING_STATUSES)})),
        booked_via VARCHAR(10) NOT NULL CHECK (booked_via IN ({_sql_list(BOOKED_VIA)})),
        start_at TIMESTAMPTZ NOT NULL,
        end_at TIMESTAMPTZ NOT NULL,
        graph_event_id VARCHAR(255) NULL,
        join_url TEXT NULL,
        sync_status VARCHAR(10) NOT NULL DEFAULT 'pending'
            CHECK (sync_status IN ({_sql_list(SYNC_STATUSES)})),
        sync_attempts INTEGER NOT NULL DEFAULT 0,
        reminder_sent_at TIMESTAMPTZ NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS own_hiring_events (
        id SERIAL PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES own_hiring_applications(id) ON DELETE CASCADE,
        kind VARCHAR(40) NOT NULL,
        actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_own_hiring_token
        ON own_hiring_applications (token_sha256) WHERE token_sha256 IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS ix_own_hiring_app_board
        ON own_hiring_applications (process_id, stage, bucket)""",
    """CREATE INDEX IF NOT EXISTS ix_own_hiring_app_candidate
        ON own_hiring_applications (candidate_id)""",
    """CREATE INDEX IF NOT EXISTS ix_own_hiring_app_due
        ON own_hiring_applications (response_due_at) WHERE stage = 'invited'""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_own_hiring_active_slot
        ON own_hiring_bookings (process_id, start_at) WHERE status = 'active'""",
    """CREATE INDEX IF NOT EXISTS ix_own_hiring_booking_app
        ON own_hiring_bookings (application_id, status)""",
    """CREATE INDEX IF NOT EXISTS ix_own_hiring_events_app
        ON own_hiring_events (application_id, created_at)""",
)

ENUM_DDL = f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{NOTIFICATION_TYPE}'"
