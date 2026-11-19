"""Uchwały Rady nadzorczej w trybie pisemnym (R6).

Revision ID: 0736_board_votes
Revises: 0735_board_meetings

Tabele ``board_votes`` i ``board_vote_ballots`` oraz wartość powiadomienia
``board_vote`` (projekt uchwały do głosowania, wynik). DDL tabel ma jedno
źródło (``app/services/board_votes_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_votes_schema as schema

revision = "0736_board_votes"
down_revision = "0735_board_meetings"
branch_labels = None
depends_on = None

_NOTIFICATION_TYPE = "board_vote"


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
