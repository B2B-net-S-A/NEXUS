"""notificationtype: ``autofill_decisions_due`` — osoby od systemu czekają na decyzję.

Revision ID: 0516_autofill_decisions_due_notification
Revises: 0515_autofill_feedback

Decyzja Artura 23.10.2026 (silnik „Nowi na 20”): osoba dodana przez system,
o której przez 2 dni robocze nikt nie zdecydował („Dzwonię” albo odrzucenie
z powodem), trafia do „Czeka na Ciebie”, a Rekruter dostaje jeden poranny
dzwonek (``services/autofill_decisions_bell.py``). Kategoria „Kandydaci”,
bez maila. Sama wartość enuma; lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0516_autofill_decisions_due_notification"
down_revision = "0515_autofill_feedback"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'autofill_decisions_due'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'autofill_decisions_due'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0516 odmawia: notifications ma wpisy autofill_decisions_due, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
