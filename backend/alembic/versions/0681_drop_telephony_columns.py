"""Zdjęcie kolumn usuniętej integracji telefonii z ``calls`` i ``users``.

Revision ID: 0681_drop_telephony_columns
Revises: 0680_stage_moves_all_led_jobs

Integrację wycięto z kodu 08.11.2026; decyzja Artura z 11.11.2026, żeby
zdjąć też jej kolumny. Produkcja 10.11.2026: ``calls`` ma 10 wierszy dodanych
ręcznie i żaden nie ma id rozmowy ani agenta; id agenta miało jedno konto.
Indeksy (``ix_calls_cloudtalk_call_id``, ``ix_calls_cloudtalk_agent_id``,
``uq_users_cloudtalk_agent_id``) znikają razem z kolumnami.

Etykieta ``cloudtalk_call`` w typie ``champion_suggestion_source`` zostaje
(Postgres nie usuwa etykiet enuma, 0 wierszy jej używa). Reguła:
``docs/claude/integracje/cloudtalk-telefonia.md``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0681_drop_telephony_columns"
down_revision = "0680_stage_moves_all_led_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS cloudtalk_call_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS cloudtalk_agent_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS cloudtalk_agent_id")


def downgrade() -> None:
    # Przywraca tylko kształt schematu; wartości przepadły w upgrade().
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS cloudtalk_agent_id INTEGER NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_cloudtalk_agent_id "
        "ON users (cloudtalk_agent_id) WHERE cloudtalk_agent_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS cloudtalk_agent_id INTEGER NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_cloudtalk_agent_id "
        "ON calls (cloudtalk_agent_id) WHERE cloudtalk_agent_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE calls ADD COLUMN IF NOT EXISTS cloudtalk_call_id VARCHAR(255) NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_calls_cloudtalk_call_id "
        "ON calls (cloudtalk_call_id)"
    )
