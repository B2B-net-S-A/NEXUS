"""Posiedzenia Rady nadzorczej z zamrażanym pakietem (R5).

Revision ID: 0735_board_meetings
Revises: 0734_board_statements

Tabela ``board_meetings`` i wartość powiadomienia ``board_meeting_pack``
(pakiet na posiedzenie gotowy). DDL tabeli ma jedno źródło
(``app/services/board_meetings_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_meetings_schema as schema

revision = "0735_board_meetings"
down_revision = "0734_board_statements"
branch_labels = None
depends_on = None

_NOTIFICATION_TYPE = "board_meeting_pack"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{_NOTIFICATION_TYPE}'"
        )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE).
def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
