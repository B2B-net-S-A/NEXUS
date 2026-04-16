"""Candidate structured fields + RateHistory + CandidateConflict

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16 10:00:00.000000

Adds Phase 1 structured fields on candidates (years_it_experience, preferences,
champion, verifier_id, verified_tech) and creates two auxiliary tables:

- candidate_rate_history — historical rates per (candidate, client/job)
- candidate_conflicts    — hard-filter blacklist (candidate should not be sent to client)

Backward-compatible AND idempotent: all DDL uses IF NOT EXISTS. Needed because
migration 0001_initial runs `Base.metadata.create_all(checkfirst=True)` against
the live model definitions — on a fresh DB, Phase 1 columns are already created
by 0001 and this migration is a no-op for those columns but still creates the
new aux tables.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── candidates: add Phase 1 structured columns (idempotent) ────────────────
    op.execute(
        sa.text(
            "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS years_it_experience INTEGER"
        )
    )
    op.execute(
        sa.text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS preferences JSONB")
    )
    op.execute(
        sa.text(
            "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS champion BOOLEAN NOT NULL DEFAULT false"
        )
    )
    op.execute(
        sa.text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS verifier_id INTEGER")
    )
    # Best-effort FK (idempotent via NOT EXISTS check on constraint)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_candidates_verifier_id'
                ) THEN
                    ALTER TABLE candidates
                    ADD CONSTRAINT fk_candidates_verifier_id
                    FOREIGN KEY (verifier_id) REFERENCES users(id);
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS verified_tech JSONB")
    )

    # ── enums (idempotent) ────────────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contracttype') THEN
                    CREATE TYPE contracttype AS ENUM ('b2b', 'uop', 'zlecenie');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'conflicttype') THEN
                    CREATE TYPE conflicttype AS ENUM ('blacklist', 'current_employment', 'nda', 'competitor');
                END IF;
            END $$;
            """
        )
    )

    # ── candidate_rate_history (idempotent) ───────────────────────────────────
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS candidate_rate_history (
                id SERIAL PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                client_id INTEGER REFERENCES clients(id),
                job_id INTEGER REFERENCES jobs(id),
                rate INTEGER NOT NULL,
                currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
                contract_type contracttype NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                notes TEXT,
                recorded_by INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_rate_history_candidate_id ON candidate_rate_history (candidate_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_rate_history_client_id ON candidate_rate_history (client_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_rate_history_job_id ON candidate_rate_history (job_id)"
        )
    )

    # ── candidate_conflicts (idempotent) ──────────────────────────────────────
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS candidate_conflicts (
                id SERIAL PRIMARY KEY,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                client_id INTEGER NOT NULL REFERENCES clients(id),
                type conflicttype NOT NULL,
                reason TEXT,
                active BOOLEAN NOT NULL DEFAULT true,
                expires_at TIMESTAMPTZ,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_conflicts_candidate_id ON candidate_conflicts (candidate_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_conflicts_client_id ON candidate_conflicts (client_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_conflicts_active ON candidate_conflicts (active)"
        )
    )
    # Partial unique: one ACTIVE conflict per (candidate, client)
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_conflict_active "
            "ON candidate_conflicts (candidate_id, client_id) WHERE active = true"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_candidate_conflict_active"))
    op.execute(sa.text("DROP TABLE IF EXISTS candidate_conflicts"))
    op.execute(sa.text("DROP TYPE IF EXISTS conflicttype"))

    op.execute(sa.text("DROP TABLE IF EXISTS candidate_rate_history"))
    op.execute(sa.text("DROP TYPE IF EXISTS contracttype"))

    op.execute(
        sa.text(
            "ALTER TABLE candidates DROP CONSTRAINT IF EXISTS fk_candidates_verifier_id"
        )
    )
    op.execute(sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS verified_tech"))
    op.execute(sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS verifier_id"))
    op.execute(sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS champion"))
    op.execute(sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS preferences"))
    op.execute(
        sa.text("ALTER TABLE candidates DROP COLUMN IF EXISTS years_it_experience")
    )
