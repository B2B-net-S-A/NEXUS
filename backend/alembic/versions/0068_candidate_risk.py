"""Candidate Risk Profile — dropout history scoring

Revision ID: 0068_candidate_risk
Revises: 0067_merge_phase16_heads
Create Date: 2026-04-27 18:00:00.000000

Context:
    Track candidate dropout risk based on historical withdrawals across all jobs.

    Three risk categories with weights:
      (a) early dropout      — withdrew before any interview        (1pt)
      (b) interview dropout  — withdrew after entering interview    (3pt)
      (c) post-accept dropout — withdrew after accepting offer       (10pt)

What this migration does:
    1. CREATE TYPE candidateofferresponse (pending | accepted | declined)
    2. CREATE TYPE risklevel (low | medium | high)
    3. ALTER TABLE candidate_stages ADD COLUMN candidate_offer_response (nullable)
    4. CREATE TABLE candidate_risk_profile (cached aggregate per candidate)
    5. Backfill 'legacy_unknown' rejection reason for existing withdrawn rows
       without rejection_reason_id (so the new CHECK constraint passes)
    6. Seed 6 predefined withdrawal reasons per pipeline_template
    7. ADD CHECK constraint: stage='withdrawn' requires rejection_reason_id
    8. ADD composite index on (candidate_id, moved_at) for risk windowed queries

Safety: all DDL idempotent (IF NOT EXISTS). Order is critical — backfill MUST
happen before the CHECK constraint, otherwise existing rows will violate it.
"""

from alembic import op


revision = "0068_candidate_risk"
down_revision = "0067_merge_phase16_heads"
branch_labels = None
depends_on = None


SEED_REASONS = [
    "accepted_other_offer",
    "counter_offer",
    "personal_reasons",
    "lost_interest",
    "salary_mismatch",
    "process_too_long",
]
LEGACY_REASON = "legacy_unknown"


def upgrade() -> None:
    # 1) candidateofferresponse enum (idempotent)
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE candidateofferresponse AS ENUM (
                'pending', 'accepted', 'declined'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # 2) risklevel enum (idempotent)
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE risklevel AS ENUM ('low', 'medium', 'high');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # 3) candidate_stages.candidate_offer_response column
    op.execute(
        """
        ALTER TABLE candidate_stages
        ADD COLUMN IF NOT EXISTS candidate_offer_response candidateofferresponse
        """
    )

    # 4) candidate_risk_profile table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_risk_profile (
            candidate_id INTEGER PRIMARY KEY
                REFERENCES candidates(id) ON DELETE CASCADE,
            level risklevel NOT NULL DEFAULT 'low',
            score INTEGER NOT NULL DEFAULT 0,
            early_count INTEGER NOT NULL DEFAULT 0,
            interview_count INTEGER NOT NULL DEFAULT 0,
            post_accept_count INTEGER NOT NULL DEFAULT 0,
            recent_events JSONB NULL,
            computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            stale_after TIMESTAMP WITH TIME ZONE NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_risk_level "
        "ON candidate_risk_profile (level)"
    )

    # 5) Backfill 'legacy_unknown' rejection reason per pipeline_template,
    #    then attach it to existing withdrawn rows lacking a reason.
    op.execute(
        f"""
        INSERT INTO rejection_reasons
            (template_id, name, category, "order", active, created_at, updated_at)
        SELECT id, '{LEGACY_REASON}', 'withdrawn', 999, FALSE, NOW(), NOW()
        FROM pipeline_templates
        ON CONFLICT (template_id, name, category) DO NOTHING
        """
    )
    op.execute(
        f"""
        UPDATE candidate_stages cs
        SET rejection_reason_id = rr.id
        FROM rejection_reasons rr, jobs j
        WHERE cs.stage = 'withdrawn'
          AND cs.rejection_reason_id IS NULL
          AND cs.job_id = j.id
          AND rr.template_id = j.pipeline_template_id
          AND rr.name = '{LEGACY_REASON}'
          AND rr.category = 'withdrawn'
        """
    )

    # 6) Seed 6 predefined withdrawal reasons per template
    for name in SEED_REASONS:
        op.execute(
            f"""
            INSERT INTO rejection_reasons
                (template_id, name, category, "order", active, created_at, updated_at)
            SELECT id, '{name}', 'withdrawn', 0, TRUE, NOW(), NOW()
            FROM pipeline_templates
            ON CONFLICT (template_id, name, category) DO NOTHING
            """
        )

    # 7) CHECK constraint: stage='withdrawn' requires rejection_reason_id.
    #    Order matters — must run AFTER backfill, otherwise legacy rows blow up.
    op.execute(
        """
        ALTER TABLE candidate_stages
        DROP CONSTRAINT IF EXISTS ck_candidate_stages_withdrawn_requires_reason
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
        ADD CONSTRAINT ck_candidate_stages_withdrawn_requires_reason
        CHECK (stage <> 'withdrawn' OR rejection_reason_id IS NOT NULL)
        """
    )

    # 8) Composite index for risk windowed queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_candidate_moved "
        "ON candidate_stages (candidate_id, moved_at)"
    )


def downgrade() -> None:
    # Reverse order — drop FK-dependent objects first.
    op.execute("DROP INDEX IF EXISTS ix_candidate_stages_candidate_moved")
    op.execute(
        "ALTER TABLE candidate_stages "
        "DROP CONSTRAINT IF EXISTS ck_candidate_stages_withdrawn_requires_reason"
    )
    # Remove seed reasons (legacy_unknown stays — backfilled rows still ref it)
    placeholders = ",".join(f"'{n}'" for n in SEED_REASONS)
    op.execute(
        f"""
        DELETE FROM rejection_reasons
        WHERE name IN ({placeholders})
          AND category = 'withdrawn'
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_candidate_risk_level")
    op.execute("DROP TABLE IF EXISTS candidate_risk_profile")
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS candidate_offer_response"
    )
    op.execute("DROP TYPE IF EXISTS risklevel")
    op.execute("DROP TYPE IF EXISTS candidateofferresponse")
