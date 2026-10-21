"""Ocena prepu gotowa — powiadomienie dla ludzi pary (22.10.2026).

Revision ID: 0506_prep_review_ready_notification
Revises: 0505_prep_review_configs

Po ocenie prepu z transkryptu Teams prowadzący, planujący, Delivery Lead
rekrutacji i rekruter kandydata dostają ``prep_review_ready`` w ikonie
„Kalendarz” (kategoria „Rozmowy”, licznik): poziom, wynik i ile punktów
trafiło do notatki na Prep 2. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0506_prep_review_ready_notification"
down_revision = "0505_prep_review_configs"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'prep_review_ready'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'prep_review_ready'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0506 odmawia: notifications ma wpisy o ocenie prepu, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
