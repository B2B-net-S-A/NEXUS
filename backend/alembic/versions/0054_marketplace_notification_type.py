"""Targ kandydatów: notificationtype enum += 'marketplace_match'

Revision ID: 0054_marketplace_notification_type
Revises: 0053_marketplace_alert_log
Create Date: 2026-04-23 16:20:00.000000

PG nie pozwala na ADD VALUE w bloku transakcyjnym — używamy `autocommit_block`
(wzorzec z 0029_notifications_triggers lines 54-61).

Downgrade = no-op — PG nie wspiera usuwania wartości enum bez rekreacji typu,
a dane w `notifications.notification_type` mogą już na nią wskazywać.
"""

from alembic import op


revision = "0054_marketplace_notification_type"
down_revision = "0053_marketplace_alert_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'marketplace_match'"
        )


def downgrade() -> None:
    # No-op — patrz docstring.
    pass
