"""Godzina terminu rekrutacji (30.09.2026).

Revision ID: 0406_job_deadline_time
Revises: 0405_proposal_feedback_job_board

Banki (Alior, PKO BP) podają termin z godziną. `jobs.deadline` zostaje datą —
alerty terminów, filtry i sortowanie liczą po dniu — a godzina (czas
Europe/Warsaw) żyje obok. Lustro w `entrypoint.sh` (`_COLUMN_STATEMENTS`).
"""

from alembic import op

revision = "0406_job_deadline_time"
down_revision = "0405_proposal_feedback_job_board"
branch_labels = None
depends_on = None

ADD_COLUMN = "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline_time TIME NULL"


def upgrade() -> None:
    op.execute(ADD_COLUMN)


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM jobs WHERE deadline_time IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade 0406 odmawia: jobs.deadline_time ma wpisane godziny.';
            END IF;
        END $$"""
    )
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS deadline_time")
