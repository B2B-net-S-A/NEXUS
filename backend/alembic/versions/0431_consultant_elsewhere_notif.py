"""notificationtype: ``consultant_in_other_recruitment`` — dzwonek dla Delivery Leada.

Revision ID: 0431_consultant_elsewhere_notif
Revises: 0430_job_ads

Decyzja Artura 12.10.2026 (D3, D4): gdy osoba, która u nas pracuje, zostaje
zatrudniona w innej rekrutacji albo jej CV idzie do innego klienta, Delivery
Lead klienta, u którego pracuje, dostaje dzwonek. Samo dodanie do rekrutacji
nie dzwoni — informuje znacznik „Pracuje u nas” (``services/employment_marker``).

Sama zmiana nie wymaga DDL poza wartością enuma. Lustro w ``entrypoint.sh``
(prod alembic bywa osierocony).
"""

from alembic import op

revision = "0431_consultant_elsewhere_notif"
down_revision = "0430_job_ads"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'consultant_in_other_recruitment'"

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu w powiadomieniach dałby
# 500 przy odczycie dzwonka.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'consultant_in_other_recruitment'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0431 odmawia: notifications ma wpisy consultant_in_other_recruitment, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
