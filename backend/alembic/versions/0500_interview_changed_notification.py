"""Rozmowa u klienta przełożona albo odwołana — powiadomienie dla pary (21.10.2026).

Revision ID: 0500_interview_changed_notification
Revises: 0499_b2b_signing_requests

Zgłoszenie rekruterki: terminy rozmów u klienta często się zmieniają, a gdy
rekruter przełoży albo odwoła rozmowę w NEXUSIE, Delivery Lead nic nie
dostaje (przy prepie para dowiaduje się od 17.10.2026, ``prep_changed*``).
Typ ``interview_changed`` w ikonie „Kalendarz” (kategoria „Rozmowy”), z dymkiem.

Lustro w ``entrypoint.sh`` — pilnuje ``test_interview_change_notifications.py``.
"""

from alembic import op

revision = "0500_interview_changed_notification"
down_revision = "0499_b2b_signing_requests"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'interview_changed'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'interview_changed'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0500 odmawia: notifications ma wpisy o zmianie rozmowy, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
