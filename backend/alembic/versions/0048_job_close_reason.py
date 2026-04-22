"""Job close metadata: close_reason enum + close_notes

Revision ID: 0048_job_close_reason
Revises: 0047_job_closed_at
Create Date: 2026-04-23 15:00:00.000000

Adds structured close metadata to `jobs` so the "Przegrane rekrutacje" section
of the Client Profile tab can surface *why* a job closed without a placement.

- `close_reason` (enum `jobclosereason`, NULL) — structured reason. NULL for
  legacy rows.
- `close_notes` (TEXT, NULL) — free-form detail from the recruiter.

Note: `closed_at` is added by an earlier migration (`0047_job_closed_at`) —
this migration only adds the reason/notes layer on top.

Enum values: budget / internal_hire / competitor / paused / filled_by_us /
client_ghosted / other.

Idempotent via `IF NOT EXISTS` guards — safe under entrypoint.sh rerun.
"""

from alembic import op


revision = "0048_job_close_reason"
down_revision = "0047_job_closed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum type (idempotent) ────────────────────────────────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobclosereason') THEN
                CREATE TYPE jobclosereason AS ENUM (
                    'budget',
                    'internal_hire',
                    'competitor',
                    'paused',
                    'filled_by_us',
                    'client_ghosted',
                    'other'
                );
            END IF;
        END$$;
        """
    )

    # ── jobs: add close_reason + close_notes (idempotent) ─────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='close_reason'
            ) THEN
                ALTER TABLE jobs ADD COLUMN close_reason jobclosereason NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='close_notes'
            ) THEN
                ALTER TABLE jobs ADD COLUMN close_notes TEXT NULL;
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='close_notes'
            ) THEN
                ALTER TABLE jobs DROP COLUMN close_notes;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='close_reason'
            ) THEN
                ALTER TABLE jobs DROP COLUMN close_reason;
            END IF;
        END$$;
        """
    )
    op.execute("DROP TYPE IF EXISTS jobclosereason")
