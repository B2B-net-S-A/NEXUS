"""„Ludzie w NEXUSIE” — typy powiadomień modułów kadrowych.

Revision ID: 0456_hr_notifications
Revises: 0455_hr_access

Urlopy, timesheety, premie, wejście/odejście, sprawy administracja@, sprzęt
(typy osobiste) i opieka nad konsultantem (sekcja Delivery). Lista wartości ma
jedno źródło: ``app/services/hr_notification_schema.py``; lustro literalne
w ``_ENUM_STATEMENTS`` w ``entrypoint.sh``.
"""

from alembic import op

from app.services import hr_notification_schema as schema

revision = "0456_hr_notifications"
down_revision = "0455_hr_access"
branch_labels = None
depends_on = None

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy dzwonku.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ({", ".join(f"'{t}'" for t in schema.NOTIFICATION_TYPES)})
    ) THEN
        RAISE EXCEPTION 'Downgrade 0456 odmawia: notifications ma wpisy typów HR, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
