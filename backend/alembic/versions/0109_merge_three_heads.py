"""Merge three parallel alembic heads back into a single tip.

Revision ID: 0109_merge_three_heads
Revises: 0108_calendar_recording_discovered, 0108_teams_notification_channels, 0106_candidate_linkedin_slug
Create Date: 2026-05-16 13:00:00.000000

After Phase 7 features landed in parallel branches, three sibling heads
remained:

- ``0108_calendar_recording_discovered`` — Phase 7.8 Stream recording
  (chained off ``0107_merge_m365_phase7_heads``).
- ``0108_teams_notification_channels`` — Phase 7.6 Teams notifications
  (chained off ``0107_users_aad_groups``).
- ``0106_candidate_linkedin_slug`` — LinkedIn extension v0.2 (never
  merged into either ``0107_*`` reconvergence).

Per project convention (see ``0098_merge_heads`` and
``0107_merge_m365_phase7_heads`` for the same pattern), every PR that
creates a new head must also reconverge to a single tip so
``alembic upgrade head`` (singular) keeps working without manual
``stamp`` ceremony on prod.

This revision is empty — its sole purpose is to declare all three
ancestor heads so ``alembic upgrade heads`` collapses back to a single
tip.
"""

from alembic import op  # noqa: F401  (kept for parity with other merges)


revision = "0109_merge_three_heads"
down_revision = (
    "0108_calendar_recording_discovered",
    "0108_teams_notification_channels",
    "0106_candidate_linkedin_slug",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
