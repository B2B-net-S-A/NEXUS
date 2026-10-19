"""Sprzęt — „Przypomnij” o zwrocie: typ powiadomienia ``equipment_return_reminder``.

Revision ID: 0478_equipment_return_reminder
Revises: 0477_candidate_consents_two_kinds

Recepcja przypomina posiadaczowi z kontem NEXUSA o zwrocie sprzętu (dzwonek
i mail „Czas i ludzie”). Wartość ma jedno źródło
(``app/services/hr_notification_schema.py``); ``entrypoint.sh`` ma lustro.
"""

from alembic import op

revision = "0478_equipment_return_reminder"
down_revision = "0477_candidate_consents_two_kinds"
branch_labels = None
depends_on = None

VALUE = "equipment_return_reminder"

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis tego typu dałby 500 przy liście powiadomień.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications WHERE notification_type::text = '{VALUE}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0478 odmawia: notifications ma przypomnienia o zwrocie sprzętu, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{VALUE}'")


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
