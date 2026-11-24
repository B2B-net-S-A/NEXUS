"""Informacja zwrotna o wadach rozliczenia: wada × kontrakt × miesiąc i typ dzwonka.

Revision ID: 0774_settlement_feedback
Revises: 0773_prep_meeting_preparation

Powtórka 7 próby IX–X (24.11.2026): uwagi NEXUS-a o wadach RCP były
prawdziwe, ale nie docierały do konsultanta, akceptującego u klienta ani
opiekuna. Tabela ``client_settlement_feedback`` trzyma stan wady i dziennik
komunikatów (także „na sucho”), a typ ``settlement_feedback`` niesie dzwonek
opiekuna. SQL i powody: ``app/services/client_settlement_feedback_schema.py``
(to samo źródło czyta ``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlement_feedback_schema as schema

revision = "0774_settlement_feedback"
down_revision = "0773_prep_meeting_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in schema.ENUM_DDL:
            op.execute(statement)
    for statement in schema.ALL_DDL:
        op.execute(statement)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed tej
# rewizji jej nie zna — dzwonek tego typu dałby 500 przy odczycie powiadomień.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = '{schema.NOTIFICATION_TYPE}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0774 odmawia: notifications ma wpisy {schema.NOTIFICATION_TYPE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
