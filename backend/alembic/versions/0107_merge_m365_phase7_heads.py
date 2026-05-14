"""Merge three Phase 7 heads back into a single alembic tip.

Revision ID: 0107_merge_m365_phase7_heads
Revises: 0106_calendar_event_confirmation, 0106_graph_subscriptions, 0106_calendar_meeting_url
Create Date: 2026-05-14 14:45:00.000000

Phase 7 of the M365 plan landed in parallel branches that each appended a
``0106_*`` migration to ``0105_user_email_templates``:

- ``0106_calendar_event_confirmation`` — Phase 7.5 Actionable Messages.
- ``0106_graph_subscriptions`` — Phase 7.3 Graph webhooks.
- ``0106_calendar_meeting_url`` — Phase 7.1 Teams meeting links (this PR).

That left three sibling heads. Per the project convention (see
``0098_merge_heads`` for the historical incident), every PR that creates a
new head must also reconverge to a single tip so ``alembic upgrade head``
keeps working without manual ``stamp`` ceremony on prod.

This revision is empty — its sole purpose is to declare all three
``0106_*`` ancestors so ``alembic upgrade heads`` collapses back to a
single tip.
"""

from alembic import op  # noqa: F401  (kept for parity with other merges)


revision = "0107_merge_m365_phase7_heads"
down_revision = (
    "0106_calendar_event_confirmation",
    "0106_graph_subscriptions",
    "0106_calendar_meeting_url",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
