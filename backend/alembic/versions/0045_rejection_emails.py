"""Automatic candidate-rejection emails: scheduler table + notification enums

Revision ID: 0045_rejection_emails
Revises: 0044_experience_search_indexes
Create Date: 2026-04-23 12:00:00.000000

Adds:
  - enum `rejectionemailstatus` (pending | sent | cancelled | failed | skipped)
  - table `scheduled_rejection_emails` (one row per queued rejection email)
  - partial index `ix_scheduled_rejemail_pending_due` for the dispatch loop
  - five new values in enum `notificationtype`:
      rejection_email_scheduled
      rejection_email_sent
      rejection_email_cancelled
      rejection_email_skipped
      rejection_email_failed

Postgres note: `ALTER TYPE ... ADD VALUE` cannot run inside a transaction
alongside DDL that then *uses* the new values in the SAME transaction. Since
this migration only DEFINES the values (they're used from application code
later), we can safely batch them here. Pattern identical to 0034_kpi_coach.py.

Idempotent (IF NOT EXISTS everywhere). Reversible except for enum values —
Postgres does not support dropping enum values without type recreation, so
`downgrade()` leaves `notificationtype` with the five additions (harmless).
"""

from alembic import op


revision = "0045_rejection_emails"
down_revision = "0044_experience_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum: rejectionemailstatus ──────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE rejectionemailstatus AS ENUM (
                'pending', 'sent', 'cancelled', 'failed', 'skipped'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # ── Extend notificationtype enum ────────────────────────────────────────
    for value in (
        "rejection_email_scheduled",
        "rejection_email_sent",
        "rejection_email_cancelled",
        "rejection_email_skipped",
        "rejection_email_failed",
    ):
        op.execute(
            f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
        )

    # ── scheduled_rejection_emails ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_rejection_emails (
            id                  SERIAL PRIMARY KEY,
            candidate_stage_id  INTEGER NOT NULL UNIQUE
                                    REFERENCES candidate_stages(id) ON DELETE CASCADE,
            candidate_id        INTEGER NOT NULL
                                    REFERENCES candidates(id) ON DELETE CASCADE,
            job_id              INTEGER NOT NULL
                                    REFERENCES jobs(id) ON DELETE CASCADE,
            recruiter_id        INTEGER NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
            to_email            VARCHAR(320) NOT NULL,
            subject             VARCHAR(998) NOT NULL,
            body_html           TEXT NOT NULL,
            other_processes     JSONB NOT NULL DEFAULT '[]'::jsonb,
            template_id         INTEGER NULL
                                    REFERENCES email_templates(id) ON DELETE SET NULL,
            status              rejectionemailstatus NOT NULL DEFAULT 'pending',
            scheduled_at        TIMESTAMPTZ NOT NULL,
            sent_at             TIMESTAMPTZ NULL,
            cancelled_at        TIMESTAMPTZ NULL,
            cancelled_by        INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
            email_id            INTEGER NULL
                                    REFERENCES emails(id) ON DELETE SET NULL,
            attempts            INTEGER NOT NULL DEFAULT 0,
            last_error          TEXT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Basic indexes (hot-path queries).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_candidate "
        "ON scheduled_rejection_emails(candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_job "
        "ON scheduled_rejection_emails(job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_recruiter "
        "ON scheduled_rejection_emails(recruiter_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_status "
        "ON scheduled_rejection_emails(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_scheduled_at "
        "ON scheduled_rejection_emails(scheduled_at)"
    )

    # Partial index — dispatch loop's hot query:
    #   SELECT ... WHERE status='pending' AND scheduled_at <= now()
    # Partial indexes stay small even as `sent`/`cancelled` rows accumulate.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_rejemail_pending_due "
        "ON scheduled_rejection_emails(status, scheduled_at) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    # Drop indexes first (safe with IF EXISTS).
    for idx in (
        "ix_scheduled_rejemail_pending_due",
        "ix_scheduled_rejemail_scheduled_at",
        "ix_scheduled_rejemail_status",
        "ix_scheduled_rejemail_recruiter",
        "ix_scheduled_rejemail_job",
        "ix_scheduled_rejemail_candidate",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    op.execute("DROP TABLE IF EXISTS scheduled_rejection_emails")
    op.execute("DROP TYPE IF EXISTS rejectionemailstatus")

    # notificationtype values — Postgres can't remove enum values without
    # recreating the type. Leave them; zero functional impact because no row
    # will be inserted with those values once the code is rolled back.
