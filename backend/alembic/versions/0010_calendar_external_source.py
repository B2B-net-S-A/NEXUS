"""Phase 7b.6: external_id + external_source on calendar_events

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-16 17:15:00.000000

Adds to `calendar_events`:
- external_id       VARCHAR(200)  — source-specific UID (iCal UID, Outlook id)
- external_source   VARCHAR(50)   — 'manual' | 'ical' | 'outlook' | 'google'

Plus a partial unique index on (external_source, external_id) WHERE external_id IS NOT NULL
for idempotent re-sync.

Idempotent.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE calendar_events
              ADD COLUMN IF NOT EXISTS external_id VARCHAR(200),
              ADD COLUMN IF NOT EXISTS external_source VARCHAR(50) DEFAULT 'manual'
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              ux_calendar_events_external
              ON calendar_events (external_source, external_id)
              WHERE external_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE calendar_events SET external_source='manual' WHERE external_source IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ux_calendar_events_external"))
    op.execute(
        sa.text(
            """
            ALTER TABLE calendar_events
              DROP COLUMN IF EXISTS external_source,
              DROP COLUMN IF EXISTS external_id
            """
        )
    )
