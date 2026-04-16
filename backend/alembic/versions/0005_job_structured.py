"""Job structured fields for matching engine

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16 10:30:00.000000

Adds Phase 1 structured fields on jobs:

- must_skills / nice_skills    — structured criteria (matching-engine input)
- seniority, work_mode         — new enums
- headcount, reference_number  — B2B staffing metadata
- industry, subcategory        — hierarchical taxonomy
- custom_fields                — freeform JSONB (Faza 4 will replace with a dedicated engine)
- embedding_id                 — persisted Qdrant vector id (populated by Faza 2)
- criteria_generated_at        — timestamp of last AI criteria refresh

Idempotent (IF NOT EXISTS) so that `Base.metadata.create_all(checkfirst=True)`
in 0001_initial does not conflict on fresh DBs.
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'seniority') THEN
                    CREATE TYPE seniority AS ENUM ('junior', 'mid', 'senior', 'lead', 'architect');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workmode') THEN
                    CREATE TYPE workmode AS ENUM ('fulltime', 'parttime', 'contract');
                END IF;
            END $$;
            """
        )
    )

    # Structured skill fields + metadata (idempotent)
    op.execute(sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS must_skills JSONB"))
    op.execute(sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS nice_skills JSONB"))
    op.execute(sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority seniority"))
    op.execute(
        sa.text(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_mode workmode NOT NULL DEFAULT 'fulltime'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS headcount INTEGER NOT NULL DEFAULT 1"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reference_number VARCHAR(50)"
        )
    )
    op.execute(
        sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS industry VARCHAR(50)")
    )
    op.execute(
        sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS subcategory VARCHAR(100)")
    )
    op.execute(sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS custom_fields JSONB"))
    op.execute(
        sa.text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS embedding_id VARCHAR(100)")
    )
    op.execute(
        sa.text(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS criteria_generated_at TIMESTAMPTZ"
        )
    )

    # Partial unique on reference_number (when not null)
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_reference_number "
            "ON jobs (reference_number) WHERE reference_number IS NOT NULL"
        )
    )
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_jobs_industry ON jobs (industry)")
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_id ON jobs (embedding_id)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_jobs_embedding_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_jobs_industry"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_jobs_reference_number"))

    for col in [
        "criteria_generated_at",
        "embedding_id",
        "custom_fields",
        "subcategory",
        "industry",
        "reference_number",
        "headcount",
        "work_mode",
        "seniority",
        "nice_skills",
        "must_skills",
    ]:
        op.execute(sa.text(f"ALTER TABLE jobs DROP COLUMN IF EXISTS {col}"))

    op.execute(sa.text("DROP TYPE IF EXISTS workmode"))
    op.execute(sa.text("DROP TYPE IF EXISTS seniority"))
