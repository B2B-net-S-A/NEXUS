"""Alarm o masowym przeglądaniu CV kandydatów (22.10.2026).

Revision ID: 0508_candidate_data_access_alert
Revises: 0507_prep_review_ready_notification

12.10.2026 dziewięć nowych kont otworzyło w trzy godziny pliki 181 kandydatów
i nikt się o tym nie dowiedział. Decyzja Artura 22.10.2026: alarm bez blokady
do adminów i Head of Recruitment (dzwonek i mail od razu). Typ
``candidate_data_access_alert`` w kategorii „Konto i system”.

Lustro w ``entrypoint.sh`` — pilnuje ``test_candidate_data_access_alerts.py``.
"""

from alembic import op

revision = "0508_candidate_data_access_alert"
down_revision = "0507_prep_review_ready_notification"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_data_access_alert'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'candidate_data_access_alert'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0508 odmawia: notifications ma alarmy o przeglądaniu CV, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
