"""proposal_snapshots.degraded — flag fallback (degraded-semantic) rankings.

Revision ID: 0211_proposal_snapshot_degraded
Revises: 0211_job_deadline_alerts
Create Date: 2026-08-04

Re-parented onto 0211_job_deadline_alerts (merged from main in parallel) to keep
a single linear alembic head — both were originally branched off 0210.

A ranking produced with a degraded semantic leg (Qdrant/Voyage down or the job
unindexed → neutral-semantic fallback) previously looked identical to a healthy
one after the fact — ``semantic_degraded`` was computed during the run and
discarded. Persist it so the UI can mark a fallback ranking instead of
presenting it as a real AI result.
"""

from alembic import op


revision = "0211_proposal_snapshot_degraded"
down_revision = "0211_job_deadline_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE proposal_snapshots
            ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE proposal_snapshots DROP COLUMN IF EXISTS degraded")
