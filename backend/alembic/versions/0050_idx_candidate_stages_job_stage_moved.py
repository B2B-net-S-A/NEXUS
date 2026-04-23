"""Index on candidate_stages(job_id, stage, moved_at DESC)

Revision ID: 0050_idx_candidate_stages_job_stage_moved
Revises: 0049_linkedin_employment
Create Date: 2026-04-23 15:00:00.000000

Supports the "candidates from similar historical jobs" feature by making the
hot aggregation query (pull max(moved_at) per (candidate_id, job_id) for a
batch of similar job_ids filtered by stage and cutoff window) cheap.

Read path (see `app/services/similar_job_candidates.py`):
    WHERE job_id IN (:similar_job_ids)
      AND moved_at >= :cutoff
    GROUP BY candidate_id, job_id

Idempotent + reversible.
"""

from alembic import op

revision = "0050_stage_idx"
down_revision = "0049_linkedin_employment"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_candidate_stages_job_stage_moved"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
        "ON candidate_stages (job_id, stage, moved_at DESC)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
