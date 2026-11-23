"""Przypomnienia o brakującym raporcie godzin: dziennik wysyłek i typ dzwonka.

Revision ID: 0763_settlement_reminders
Revises: 0762_pre_contract_stop

Rekomendacja 4 z makiet panelu Finansów (23.11.2026). Tabela
``client_settlement_reminders`` zapisuje każde przypomnienie (mail do
konsultanta albo dzwonek opiekuna) z unikatem na dzień, a typ
``settlement_report_missing`` niesie dzwonek opiekuna z 7. dnia roboczego.
SQL i powody: ``app/services/client_settlement_reminders_schema.py`` (to samo
źródło czyta ``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlement_reminders_schema as schema

revision = "0763_settlement_reminders"
down_revision = "0762_pre_contract_stop"
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
        RAISE EXCEPTION 'Downgrade 0763 odmawia: notifications ma wpisy {schema.NOTIFICATION_TYPE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
