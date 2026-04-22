"""Job.closed_at — timestamp zamknięcia zapytania + backfill

Revision ID: 0047_job_closed_at
Revises: 0046_backfill_contractor_drafts
Create Date: 2026-04-23 14:00:00.000000

Adds `closed_at` column on `jobs` so we can reliably filter closed requests
by the date they were actually closed (not `updated_at`, which reacts to
any edit). Backfill: for historical rows with `status = 'closed'` we
seed `closed_at = updated_at` as a best-effort approximation.

The setter in `app/api/jobs.py` (PATCH /jobs/{id}) writes `closed_at = now()`
when status flips to `closed`, and clears it when status flips away.

Feature: "Hit ratio per client" report (GET /api/reports/clients).
Idempotent via IF NOT EXISTS guards.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_job_closed_at"
down_revision = "0046_backfill_contractor_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE jobs "
            "ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_closed_at ON jobs (closed_at)"
        )
    )
    # Backfill: best-effort — use updated_at as a proxy for historical closed rows.
    op.execute(
        sa.text(
            "UPDATE jobs SET closed_at = updated_at "
            "WHERE status = 'closed' AND closed_at IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_jobs_closed_at"))
    op.execute(sa.text("ALTER TABLE jobs DROP COLUMN IF EXISTS closed_at"))
