"""proposal_snapshots: run_id + input_fingerprint + stale (freshness).

Revision ID: 0213_proposal_snapshot_freshness
Revises: 0212_proposal_snapshot_source_handoff
Create Date: 2026-08-04

P0-B: a snapshot never recorded which brief/Champion revision produced it, nor
whether that revision was later changed — so an outdated ranking looked current.
`run_id` correlates a ranking with match telemetry; `input_fingerprint` records
the revision it was scored against; `stale` is flipped when a matching input
changes, so the UI can prompt a re-run.
"""

from alembic import op


revision = "0213_proposal_snapshot_freshness"
down_revision = "0212_proposal_snapshot_source_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE proposal_snapshots
            ADD COLUMN IF NOT EXISTS run_id TEXT NULL,
            ADD COLUMN IF NOT EXISTS input_fingerprint TEXT NULL,
            ADD COLUMN IF NOT EXISTS stale BOOLEAN NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE proposal_snapshots
            DROP COLUMN IF EXISTS run_id,
            DROP COLUMN IF EXISTS input_fingerprint,
            DROP COLUMN IF EXISTS stale
        """
    )
