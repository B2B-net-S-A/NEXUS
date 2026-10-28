"""„Ogłoszenia” na pulpicie każdej osoby (decyzja Artura 28.10.2026).

Revision ID: 0616_announcements
Revises: 0615_job_twins

Propozycja Olafa: strefa ogłoszeń na pulpicie, na której Head of Recruitment
i admin publikują ważne informacje. Tabele ``announcements``
i ``announcement_reads`` oraz typ dzwonka ``announcement_important``
(„ważne” = dzwonek i mail obowiązkowy do odbiorców). DDL
w ``app/services/announcements_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.announcements_schema import ENUM_DDL, INDEX_DDL, TABLE_DDL

revision = "0616_announcements"
down_revision = "0615_job_twins"
branch_labels = None
depends_on = None

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'announcement_important'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0616 odmawia: notifications ma powiadomienia o ważnych ogłoszeniach, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ENUM_DDL)
    for statement in (*TABLE_DDL, *INDEX_DDL):
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP TABLE IF EXISTS announcement_reads")
    op.execute("DROP TABLE IF EXISTS announcements")
