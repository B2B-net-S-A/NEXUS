"""Calendar events: online_meeting_url + recording_url for Teams meetings.

Revision ID: 0106_calendar_meeting_url
Revises: 0105_user_email_templates
Create Date: 2026-05-14 14:00:00.000000

Phase 7.1 of the M365 plan (.claude/plans/elegant-percolating-thimble.md).

calendar_events:
- ``online_meeting_url`` (VARCHAR(998) NULL) — Graph-generated Teams join URL
  set by ``create_event(..., with_teams_meeting=True)``. Distinct from the
  legacy ``teams_link`` column, which is user-input free text. Length 998 is
  the conservative Graph upper bound for Teams join URLs.
- ``recording_url`` (VARCHAR(998) NULL) — added proactively for Phase 7.8
  (Stream recording follow-up) so we ship one ALTER TABLE roundtrip instead
  of two. NULL until a recording is published.

Forward-only, idempotent — both columns wrapped in ``IF NOT EXISTS`` guards
so the migration is safe to replay on prod after a partial deploy.
"""

from alembic import op


revision = "0106_calendar_meeting_url"
down_revision = "0105_user_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS online_meeting_url VARCHAR(998) NULL"
    )
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS recording_url VARCHAR(998) NULL"
    )


def downgrade() -> None:
    # Forward-only — dropping these columns would lose Teams join URLs and
    # recording links for any events created since the upgrade.
    raise NotImplementedError(
        "Cannot downgrade: dropping online_meeting_url/recording_url would "
        "lose data for events created after this migration ran."
    )
