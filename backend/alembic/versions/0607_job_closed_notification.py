"""notificationtype: ``job_closed_people_waiting`` — zamknięta rekrutacja z osobami w toku.

Revision ID: 0607_job_closed_notification
Revises: 0606_autofill_whole_client

Zgłoszenie z 28.10.2026: rekruterka nie wiedziała, że Delivery Lead zamknął
rekrutację, w której jej osoby były wysłane do klienta. Decyzja Artura:
rekruter osoby od „CV wysłane” w górę dostaje dzwonek i mail obowiązkowy
(``services/job_closed_notices.py``). Sama wartość enuma; lustro
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0607_job_closed_notification"
down_revision = "0606_autofill_whole_client"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_closed_people_waiting'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'job_closed_people_waiting'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0607 odmawia: notifications ma wpisy job_closed_people_waiting, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
