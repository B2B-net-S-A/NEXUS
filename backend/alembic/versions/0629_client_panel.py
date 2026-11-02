"""Panel klienta pod linkiem z CV (02.11.2026).

Revision ID: 0629_client_panel
Revises: 0628_sales_meeting_transcripts

Tabele panelu i typ dzwonka ``client_panel_request``. SQL i powód:
``app/services/client_panel_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import client_panel_schema as schema

revision = "0629_client_panel"
down_revision = "0628_sales_meeting_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.TABLE_DDL:
        op.execute(statement)
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_panel_request'"
        )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — dzwonek dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
         WHERE notification_type::text = 'client_panel_request'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0629 odmawia: są dzwonki client_panel_request, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
