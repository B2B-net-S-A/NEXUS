"""DDL dziennika zdarzeń CPro — jedno źródło dla migracji i ``entrypoint.sh``."""

from __future__ import annotations

NOTIFICATION_TYPES: tuple[str, ...] = (
    "cpro_candidate_rejected",
    "cpro_interview_change",
    "cpro_close_needs_decision",
)

TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS cpro_mail_events (
        id SERIAL PRIMARY KEY,
        message_key VARCHAR(998) NOT NULL UNIQUE,
        email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
        kind VARCHAR(32) NOT NULL,
        request_number VARCHAR(16),
        person VARCHAR(255),
        reason VARCHAR(300),
        received_at TIMESTAMPTZ NOT NULL,
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
        outcome VARCHAR(16) NOT NULL,
        outcome_text VARCHAR(300) NOT NULL,
        notified INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_cpro_mail_events_received "
    "ON cpro_mail_events (received_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_cpro_mail_events_job "
    "ON cpro_mail_events (job_id, received_at DESC) WHERE job_id IS NOT NULL",
    # Przebieg szuka nowych maili po nadawcy; `emails.from_address` ma już indeks.
)
