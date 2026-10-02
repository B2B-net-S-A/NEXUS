"""notificationtype: ``request_allocation_proposals`` — propozycje do akceptacji.

Revision ID: 0409_request_allocation_proposals
Revises: 0408_board_task_waiting_notif

Decyzja Artura 02.10.2026: automat przydziału proponuje jedną osobę do
requestu bez obsady, a Head of Recruitment albo admin ją akceptuje, zamienia
albo odrzuca. Dzwonek „Propozycje przydziału do akceptacji: N” to jeden wpis
dziennie na Head of Recruitment (``request_allocation_notices``).

Sama zmiana nie wymaga DDL: propozycja to istniejący stan ``proposed``
w ``job_work_assignments``, a powody zwolnienia mieszczą się w
``release_reason``. Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0409_request_allocation_proposals"
down_revision = "0408_board_task_waiting_notif"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'request_allocation_proposals'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu w powiadomieniach dałby
# 500 przy odczycie dzwonka.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'request_allocation_proposals'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0409 odmawia: notifications ma wpisy request_allocation_proposals, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
