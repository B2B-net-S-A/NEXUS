"""Onboarding flag on users + needs_sourcing on jobs (first-login gate)

Revision ID: 0035_onboarding_and_job_sourcing
Revises: 0034_kpi_coach
Create Date: 2026-04-21 19:00:00.000000

Adds:
- `users.profile_completed` (bool, default false) + `users.profile_completed_at`
  (timestamptz, nullable) — backs the post-login onboarding gate that forces
  DL and recruiters to fill initial data before accessing the app.
- `jobs.needs_sourcing` (bool, default false, indexed) — set by DL during
  onboarding (and later from the jobs list) to flag jobs that need active
  candidate sourcing.

Data migration: existing users whose role does not require onboarding
(admin, head_of_recruitment, tac, sourcer, user) are marked complete in
place, so the rollout does not surprise them with a blocking modal.

Idempotent + reversible.
"""

from alembic import op
import sqlalchemy as sa

revision = "0035_onboarding_and_job_sourcing"
down_revision = "0034_kpi_coach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) users.profile_completed — idempotent add.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='profile_completed'
            ) THEN
                ALTER TABLE users
                    ADD COLUMN profile_completed BOOLEAN NOT NULL DEFAULT false;
            END IF;
        END$$;
        """
    )

    # 2) users.profile_completed_at — idempotent add.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='profile_completed_at'
            ) THEN
                ALTER TABLE users
                    ADD COLUMN profile_completed_at TIMESTAMP WITH TIME ZONE NULL;
            END IF;
        END$$;
        """
    )

    # 3) jobs.needs_sourcing — idempotent add.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='needs_sourcing'
            ) THEN
                ALTER TABLE jobs
                    ADD COLUMN needs_sourcing BOOLEAN NOT NULL DEFAULT false;
            END IF;
        END$$;
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_needs_sourcing "
        "ON jobs(needs_sourcing)"
    )

    # 4) Data migration: roles that do not need onboarding are pre-flagged
    #    so existing admins/TAC/sourcers/viewers are not blocked on next login.
    op.execute(
        """
        UPDATE users
        SET profile_completed = true,
            profile_completed_at = now()
        WHERE profile_completed = false
          AND role NOT IN ('delivery_lead', 'recruiter')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_needs_sourcing")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='needs_sourcing'
            ) THEN
                ALTER TABLE jobs DROP COLUMN needs_sourcing;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='profile_completed_at'
            ) THEN
                ALTER TABLE users DROP COLUMN profile_completed_at;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='profile_completed'
            ) THEN
                ALTER TABLE users DROP COLUMN profile_completed;
            END IF;
        END$$;
        """
    )
