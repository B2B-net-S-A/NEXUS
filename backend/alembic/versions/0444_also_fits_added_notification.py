"""notificationtype: ``also_fits_added`` — ktoś dodał osobę do Twojej rekrutacji z „Pasuje też do”.

Revision ID: 0444_also_fits_added_notification
Revises: 0443_integrations_v1

Decyzja Artura 14.10.2026 (D2): po „+ Dodaj” pod podpowiedzią „Pasuje też do”
osoba trafia od razu do „Nowych” rekrutacji B, a rekruterzy B dostają dzwonek:
kto dodał, kogo i przy której rekrutacji padła podpowiedź
(``services/also_fits.py``). Kategoria „Kandydaci” (do wyciszenia), bez maila.

Sama zmiana nie wymaga DDL poza wartością enuma. Lustro w ``entrypoint.sh``
(prod alembic bywa osierocony).
"""

from alembic import op

revision = "0444_also_fits_added_notification"
down_revision = "0443_integrations_v1"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'also_fits_added'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu w powiadomieniach dałby
# 500 przy odczycie dzwonka.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'also_fits_added'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0444 odmawia: notifications ma wpisy also_fits_added, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
