"""Phase: LinkedIn-style position/company filters — merge heads + GIN indexes on experience

Revision ID: 0044_experience_search_indexes
Revises: 0043_interview_feedback, 0043_kpi_coach_nudger
Create Date: 2026-04-22 12:00:00.000000

Merges two divergent heads (`0043_interview_feedback` and
`0043_kpi_coach_nudger`, both child of `0042_interview_questions`) into a
single head AND adds search indexes powering the new candidate filters:
  - current_company / past_company / current_title (JSONB experience)
  - companies/suggest autocomplete endpoint

Indexes:
  - GIN on candidates.experience (supports jsonb containment / jsonb_array_elements scans)
  - GIN on (experience::text) gin_trgm_ops (supports ILIKE substring — MVP)

Safe to re-run because indexes use IF NOT EXISTS. `pg_trgm` extension already
enabled by 0013_search_indexes.py.
"""

from alembic import op


revision = "0044_experience_search_indexes"
down_revision = (
    "0043_interview_feedback",
    "0043_kpi_coach_nudger",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_experience_gin "
        "ON candidates USING GIN (experience)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_experience_trgm "
        "ON candidates USING GIN ((experience::text) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_experience_trgm")
    op.execute("DROP INDEX IF EXISTS ix_candidates_experience_gin")
