"""Phase B2: pg_trgm + GIN indexes for fast text search

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-17 12:00:00.000000

Adds fuzzy/full-text search support on candidate CVs and job descriptions.

Operations:
  - enable `pg_trgm` extension (trigram similarity)
  - GIN index on `candidates.raw_cv_text` using gin_trgm_ops
  - GIN index on `candidates.name || ' ' || lastname || ' ' || email` using gin_trgm_ops
    (expression index — speeds up `%q%` across all three fields)
  - GIN index on `jobs.description` using gin_trgm_ops
  - GIN index on `jobs.title` using gin_trgm_ops
  - GIN index on `candidates.preferences` JSONB so `preferences->>'rate_min'`
    filters stay fast at 10k+ candidates

Safe to re-run because indexes use `IF NOT EXISTS`.
"""

from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable trigram extension (idempotent in PostgreSQL).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Candidates
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_cv_trgm "
        "ON candidates USING GIN (raw_cv_text gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_identity_trgm "
        "ON candidates USING GIN ("
        "(coalesce(name, '') || ' ' || coalesce(lastname, '') || ' ' || coalesce(email, '')) "
        "gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_preferences_gin "
        "ON candidates USING GIN (preferences)"
    )

    # Jobs
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_description_trgm "
        "ON jobs USING GIN (description gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_title_trgm "
        "ON jobs USING GIN (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_jobs_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_candidates_preferences_gin")
    op.execute("DROP INDEX IF EXISTS ix_candidates_identity_trgm")
    op.execute("DROP INDEX IF EXISTS ix_candidates_cv_trgm")
    # Leave pg_trgm extension in place — it may be used by other indexes.
