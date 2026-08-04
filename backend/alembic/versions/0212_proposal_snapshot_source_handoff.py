"""Allow proposal_snapshots.source = 'handoff'.

Revision ID: 0212_proposal_snapshot_source_handoff
Revises: 0211_proposal_snapshot_degraded
Create Date: 2026-08-04

P0-A: the operational ranking is now produced by the explicit "Przekaż do
searchu" handoff (POST /jobs/{id}/handoff) instead of at create time. Widen the
``ck_proposal_snapshots_source`` CHECK so the new ``handoff`` source is accepted.
"""

from alembic import op


revision = "0212_proposal_snapshot_source_handoff"
down_revision = "0211_proposal_snapshot_degraded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proposal_snapshots "
        "DROP CONSTRAINT IF EXISTS ck_proposal_snapshots_source"
    )
    op.execute(
        "ALTER TABLE proposal_snapshots ADD CONSTRAINT ck_proposal_snapshots_source "
        "CHECK (source IN ('create', 'manual_regenerate', 'job_updated', 'handoff'))"
    )


def downgrade() -> None:
    # Reclassify any 'handoff' rows first — otherwise re-adding the narrowed
    # CHECK fails on existing data.
    op.execute(
        "UPDATE proposal_snapshots SET source = 'manual_regenerate' "
        "WHERE source = 'handoff'"
    )
    op.execute(
        "ALTER TABLE proposal_snapshots "
        "DROP CONSTRAINT IF EXISTS ck_proposal_snapshots_source"
    )
    op.execute(
        "ALTER TABLE proposal_snapshots ADD CONSTRAINT ck_proposal_snapshots_source "
        "CHECK (source IN ('create', 'manual_regenerate', 'job_updated'))"
    )
