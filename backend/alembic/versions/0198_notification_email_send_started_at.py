"""Split "reserved for sending" from "sent" on chat fallback notifications.

``tasks/chat_email_fallback.py`` used ``email_sent_at`` itself as the claim:
it stamped the row and committed BEFORE handing anything to SMTP. That made
the stamp a lie for the whole duration of the send — a hard crash or a rolling
restart in that window left the row permanently marked as sent while no email
had ever gone out, with nothing to distinguish it from a genuine send.

``email_send_started_at`` carries the reservation instead. ``email_sent_at``
now only ever means "SMTP confirmed". A crash mid-send leaves a stale
reservation, which the next pass re-claims and delivers.

Additive and nullable — existing rows keep NULL, which reads as "not reserved"
and behaves exactly as before for anything already sent.

Revision ID: 0198_notification_email_send_started_at
Revises: 0196_b2b_signature_automation
"""

from alembic import op


revision = "0198_notification_email_send_started_at"
down_revision = "0197_rejection_reason_disqualifies_person"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Production bootstrapping mirrors this additive DDL in entrypoint.sh
    # because some installations cannot yet rely on Alembic being current.
    # Every statement must therefore tolerate the safety-net having run first.
    op.execute(
        """
        ALTER TABLE notifications
            ADD COLUMN IF NOT EXISTS email_send_started_at TIMESTAMPTZ NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE notifications
            DROP COLUMN IF EXISTS email_send_started_at
        """
    )
