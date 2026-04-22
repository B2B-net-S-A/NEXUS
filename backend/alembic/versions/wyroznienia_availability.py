"""Candidate availability status (Wyróżnienia phase)

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 12:00:00.000000

Adds `availability_status` enum column on `candidates` so the UI can render
consultant highlights (actively_looking / open_to_offers / not_looking /
unknown). Employment state ("u klienta", "bez projektu") is still *derived*
at read-time from `contracts` (active) + `candidate_conflicts`
(type=current_employment, active=true) — no dedicated column needed.

Idempotent + reversible (enum + column both gated by IF NOT EXISTS / DO$$).
"""

from alembic import op
import sqlalchemy as sa

revision = "wyroznienia_availability"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'availabilitystatus'
                ) THEN
                    CREATE TYPE availabilitystatus AS ENUM (
                        'actively_looking',
                        'open_to_offers',
                        'not_looking',
                        'unknown'
                    );
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE candidates "
            "ADD COLUMN IF NOT EXISTS availability_status availabilitystatus "
            "NOT NULL DEFAULT 'unknown'"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidates_availability_status "
            "ON candidates (availability_status)"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP INDEX IF EXISTS ix_candidates_availability_status")
    )
    op.execute(
        sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS availability_status")
    )
    op.execute(sa.text("DROP TYPE IF EXISTS availabilitystatus"))
