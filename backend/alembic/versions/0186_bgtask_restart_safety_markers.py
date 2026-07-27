"""Durable dedup markers for restart-safe background loops (audyt P1/P2).

Three background loops deduped "already handled" work in in-memory sets that
reset on every restart (Coolify rebuilds on each push) and diverged per uvicorn
worker → duplicate work:

- calendar T-15min reminder loop → re-sent reminders on restart / per worker.
- Slack SLA-breach alert loop → re-alerted every breach on restart / per worker.

Both are fixed by persisting an "already sent/alerted" stamp on the relevant
row and querying it on each loop pass, plus a ``FOR UPDATE SKIP LOCKED`` claim
so only one worker sends per row.

- ``calendar_events.reminder_sent_at``  — NULL = never reminded.
- ``candidate_stages.sla_alerted_at``   — NULL = never alerted.

(The third loop, ``linkedin_sync``, needs no new column — it reuses the existing
``candidates.linkedin_synced_at`` marker plus ``FOR UPDATE SKIP LOCKED``.)

Both columns are nullable with no default, so adding them is a metadata-only,
lock-light change. Mirrored idempotently in backend/entrypoint.sh (prod alembic
is orphaned).

Revision ID: 0186_bgtask_restart_safety_markers
Revises: 0185_widen_scoring_algorithm_version
"""

from alembic import op

revision = "0186_bgtask_restart_safety_markers"
down_revision = "0185_widen_scoring_algorithm_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE candidate_stages "
        "ADD COLUMN IF NOT EXISTS sla_alerted_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS sla_alerted_at")
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS reminder_sent_at")
