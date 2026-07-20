"""Merge the two head chains left by the 2026-07-16 parallel-session burst.

Revision ID: 0179_merge_analytics_recruitment_heads
Revises: 0177_analytics_snapshots_cutovers, 0178_recruitment_processes
Create Date: 2026-07-20 12:00:00.000000

Two branches forked off the same tip on 2026-07-16 because two sessions
authored migrations against the same parent within minutes of each other:

- ``0177_analytics_snapshots_cutovers`` — Analytics v1 snapshots + cutover
  bookkeeping (#785, analytics plan PR 7).
- ``0178_recruitment_processes`` — RecruitmentProcess in shadow mode
  (#809, module-4 plan PR-06).

Neither is a superset of the other and neither declared the other as an
ancestor, so ``alembic heads`` reports two tips. Everything in this repo
already invokes ``alembic upgrade heads`` (plural), so the split has not
broken deploys — but it *does* break ``.github/workflows/backup-drill.yml``,
which restores a dump and then runs ``alembic upgrade head`` (singular).
That command raises ``Multiple head revisions are present`` and the
disaster-recovery drill fails, meaning the restore path is unverified.

This revision is empty — its only job is to declare both ancestors so the
graph collapses back to a single tip and ``head`` (singular) resolves again.

Prod note: ``alembic_version`` on NEXUS currently holds a single row far
behind these tips (see ``/api/health/alembic``). This merge does not change
that bookmark and is not an attempt to reconcile it; whether prod should be
migrated forward at all is being decided separately, off the back of the
schema-drift report added alongside this migration. Applying this revision
to a fresh database is a no-op beyond the version bookkeeping.
"""

# Empty merge node — no schema change.

revision = "0179_merge_analytics_recruitment_heads"
down_revision = (
    "0177_analytics_snapshots_cutovers",
    "0178_recruitment_processes",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
