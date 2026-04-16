"""Phase 4: saved_searches + match_history

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-16 14:00:00.000000

Two new tables:
- saved_searches   — named filter presets per user
- match_history    — audit log of recommendation scores

Idempotent.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                name VARCHAR(100) NOT NULL,
                entity VARCHAR(40) NOT NULL,
                filters JSONB NOT NULL DEFAULT '{}'::jsonb,
                shared BOOLEAN NOT NULL DEFAULT false,
                description VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_saved_searches_user_id ON saved_searches (user_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_saved_searches_entity ON saved_searches (entity)"
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS match_history (
                id SERIAL PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id),
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                total_score INTEGER NOT NULL,
                breakdown JSONB,
                triggered_by INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_match_history_job_id ON match_history (job_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_match_history_candidate_id ON match_history (candidate_id)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS match_history"))
    op.execute(sa.text("DROP TABLE IF EXISTS saved_searches"))
