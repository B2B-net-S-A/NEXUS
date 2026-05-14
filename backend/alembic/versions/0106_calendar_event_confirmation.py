"""Calendar event candidate confirmation tracking — Phase 7.5 (Actionable Messages).

Revision ID: 0106_calendar_event_confirmation
Revises: 0105_user_email_templates
Create Date: 2026-05-14 18:00:00.000000

Phase 7.5 of the M365 expansion plan (.claude/plans/elegant-percolating-thimble.md).

Adds two columns to `calendar_events` so we can record when a candidate confirms
an interview invitation — primarily through the Outlook Actionable Messages
button, but the `source` column also accommodates manual reply / phone fallback
paths.

Columns:
- `candidate_confirmed_at` (TIMESTAMPTZ NULL) — when the confirmation arrived.
  NULL = not yet confirmed (or not requested).
- `candidate_confirmation_source` (VARCHAR(50) NULL) — provenance string. Known
  values: `outlook_actionable`, `manual_email_reply`, `phone`. Free-form so we
  can extend without migrations; the API enforces a whitelist.

Idempotent (`IF NOT EXISTS` on column add) so a partial deploy or replay is
safe.
"""

from alembic import op


revision = "0106_calendar_event_confirmation"
down_revision = "0105_user_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS candidate_confirmed_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS candidate_confirmation_source VARCHAR(50) NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events DROP COLUMN IF EXISTS candidate_confirmation_source"
    )
    op.execute(
        "ALTER TABLE calendar_events DROP COLUMN IF EXISTS candidate_confirmed_at"
    )
