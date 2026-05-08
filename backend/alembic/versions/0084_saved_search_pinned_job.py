"""Saved searches: pin to job.

Revision ID: 0084_saved_search_pinned_job
Revises: 0083_candidate_fts_index
Create Date: 2026-05-08 11:00:00.000000

Adds ``saved_searches.pinned_to_job_id`` (nullable FK → jobs) so a recruiter
can attach a saved candidate filter to a specific job. Manual search V2
loads pinned searches into the job profile's "Wyszukaj manualnie" tab next
to the user's global presets.

Why nullable FK + ON DELETE SET NULL:
- ``NULL`` = global saved search (today's behaviour preserved).
- ``SET NULL`` on job deletion keeps the saved search alive — the user can
  still re-pin it elsewhere or use it globally; we don't want job archival
  to silently delete user-curated filters.
"""

from alembic import op
import sqlalchemy as sa


revision = "0084_saved_search_pinned_job"
down_revision = "0083_candidate_fts_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_searches",
        sa.Column(
            "pinned_to_job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_saved_searches_pinned_to_job_id",
        "saved_searches",
        ["pinned_to_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saved_searches_pinned_to_job_id",
        table_name="saved_searches",
    )
    op.drop_column("saved_searches", "pinned_to_job_id")
