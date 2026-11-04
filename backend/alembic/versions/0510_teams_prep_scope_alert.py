"""Alarm o osobach spoza zakresu aplikacji prepów w Teams (22.10.2026).

Revision ID: 0510_teams_prep_scope_alert
Revises: 0509_care_board

Aplikacja „NEXUS Teams Prep” zakłada prepy tylko w kalendarzach członków
grupy Exchange ``NEXUS-Meetings-Scope``. Grupę wypełniono ręcznie 26.09 i nikt
jej nie uzupełniał — 22.10 dziesięć osób dostawało 409 przy planowaniu prepu.
NEXUS nie może sam dopisywać do grupy (zapis app-only = 403, decyzja Artura
22.10), więc raz dziennie wysyła adminom listę osób do dopisania:
``teams_prep_scope_missing`` w kategorii „Konto i system”. Lustro
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0510_teams_prep_scope_alert"
down_revision = "0509_care_board"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'teams_prep_scope_missing'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'teams_prep_scope_missing'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0510 odmawia: notifications ma alarmy o zakresie prepów, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
