"""„Ludzie w NEXUSIE” — decyzja o przepięciu czeka na front office bez daty.

Revision ID: 0512_care_board_waiting_decision
Revises: 0511_feedback_channel_teams

Karta „Decyzja” w kolumnie „Czeka na kogoś” czeka na front office bez daty
ponownej próby (makieta K3 z 22.10.2026). Poszerza CHECK
``ck_care_board_states_waiting`` o ``kind = 'decision'``. SQL ma jedno źródło
(``app/services/care_board_schema.py``); entrypoint wykonuje ten sam blok
przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import care_board_schema as schema

revision = "0512_care_board_waiting_decision"
down_revision = "0511_feedback_channel_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.WAITING_DECISION_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Decyzje bez daty wracają do „Nowa” (brak wiersza = „Nowa”).
    op.execute(
        "DELETE FROM care_board_states "
        "WHERE board_column = 'waiting' AND retry_on IS NULL"
    )
    op.execute(
        "ALTER TABLE care_board_states "
        "DROP CONSTRAINT IF EXISTS ck_care_board_states_waiting"
    )
    op.execute(
        "ALTER TABLE care_board_states ADD CONSTRAINT ck_care_board_states_waiting "
        "CHECK (board_column <> 'waiting' OR retry_on IS NOT NULL)"
    )
