"""Alarm o skrzynkach poza zakresem aplikacji „NEXUS Kadry” (02.11.2026).

Revision ID: 0632_hr_m365_scope_alert
Revises: 0631_user_receives_board_report

Grupę RBAC aplikacji prowadzi się ręcznie w Exchange. 02.11.2026 wszystkie konta
założone 18–29.10 dostały 403 przy odczycie skrzynki i nikt nie dostał sygnału.
Po uzgadnianiu o 7:00 admini dostają listę osób do dopisania:
``hr_m365_scope_missing`` w kategorii „Konto i system”. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0632_hr_m365_scope_alert"
down_revision = "0631_user_receives_board_report"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'hr_m365_scope_missing'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'hr_m365_scope_missing'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0632 odmawia: notifications ma alarmy o zakresie skrzynek, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
