"""notificationtype: ``cv_ready`` — CV firmowe gotowe (albo automat go nie zrobił).

Revision ID: 0440_cv_ready_notification
Revises: 0439_cv_finding_dismissals

Droga rekrutera do Delivery Leada (decyzja Artura 14.10.2026): rekruter nie
czeka w ciemno na CV firmowe. Po ruchu na „Zweryfikowany” automat auto-CV
podpina szkic, liczy QC i zamawia poprawki AI, a osoba, która przesunęła
kartę, dostaje dzwonek „CV gotowe do sprawdzenia” — albo „Automat nie zrobił
CV” z powodem, gdy musi coś zrobić sama (``services/cv_auto_generate.py``).
Kategoria „Ruchy w rekrutacjach” (do wyciszenia), bez maila.

Sama zmiana nie wymaga DDL poza wartością enuma. Lustro w ``entrypoint.sh``
(prod alembic bywa osierocony).
"""

from alembic import op

revision = "0440_cv_ready_notification"
down_revision = "0439_cv_finding_dismissals"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'cv_ready'"

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu w powiadomieniach dałby
# 500 przy odczycie dzwonka.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'cv_ready'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0440 odmawia: notifications ma wpisy cv_ready, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
