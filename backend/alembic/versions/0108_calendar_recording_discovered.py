"""Calendar events: recording_discovered_at marker for Phase 7.8.

Revision ID: 0108_calendar_recording_discovered
Revises: 0107_merge_m365_phase7_heads
Create Date: 2026-05-14 17:00:00.000000

Phase 7.8 of the M365 plan (.claude/plans/elegant-percolating-thimble.md).

Adds ``calendar_events.recording_discovered_at`` (TIMESTAMPTZ NULL). The OneDrive
discovery loop sets this column when it successfully locates a recording for
an event — distinct from ``recording_url`` so we can tell apart "found and
linked" from "still searching" (loop ran but URL stayed NULL) when paging
through events the loop has already inspected.

Without this marker the loop would have to re-scan every event without a
recording on every pass, even ones where Graph has already returned no
candidates over multiple ticks. With the marker we can either (a) move on
quickly because we know we've already looked, or (b) wait longer between
re-scans of "looked but not found" events. We pick (a) for now — keep the
behaviour simple, revisit once we have real-world data.

Forward-only, idempotent — wrapped in ``IF NOT EXISTS`` so the migration
replays safely on prod after a partial deploy.
"""

from alembic import op


revision = "0108_calendar_recording_discovered"
down_revision = "0107_merge_m365_phase7_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS recording_discovered_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    # Forward-only — the column carries discovery-state for the OneDrive
    # scanner and is cheap to keep. Dropping it would force a full re-scan
    # of the lookback window on next deploy.
    raise NotImplementedError(
        "Cannot downgrade: dropping recording_discovered_at would force a "
        "full re-scan of calendar events in the discovery loop."
    )
