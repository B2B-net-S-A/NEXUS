"""notificationtype: ``client_job_opened`` — nowa rekrutacja u klienta DL-a.

Revision ID: 0523_client_job_opened_notification
Revises: 0520_talent_pool_team_visible

Decyzja Artura 26.10.2026 (maile obowiązkowe, PR 3): Delivery Lead dostaje
mail od razu, gdy ktoś inny otworzy rekrutację u jego klienta (założy albo
otworzy ponownie). Kilka w 10 minut idzie jednym mailem
(``services/client_job_opened.py``). Sama wartość enuma; lustro
w ``entrypoint.sh``. Numery 0521–0522 trzyma otwarty stos formularzy klienta;
rewizja, która wejdzie do kolejki druga, przepina ``down_revision``.
"""

from alembic import op

revision = "0523_client_job_opened_notification"
down_revision = "0520_talent_pool_team_visible"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_job_opened'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'client_job_opened'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0523 odmawia: notifications ma wpisy client_job_opened, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
