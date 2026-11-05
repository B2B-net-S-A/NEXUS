"""Początek bieżącego otwarcia rekrutacji (0652).

Revision ID: 0652_job_opening_started_at
Revises: 0651_cv_call_questions

Decyzja Artura 05.11.2026: „Otwórz ponownie” zaczyna nowe otwarcie. Wakaty,
„W drodze”, ostrzeżenie przy zamknięciu i bramka powodu liczą się od tej
chwili, a karty z poprzedniego otwarcia zostają w historii. Kolumna
``jobs.cycle_started_at`` i uzupełnienie z historii ponownych otwarć przez
człowieka (bez przeniesień z Traffita) — ``app/services/job_opening.py``,
lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op

from app.services.job_opening import BACKFILL_MARKER, BACKFILL_SQL

revision = "0652_job_opening_started_at"
down_revision = "0651_cv_call_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cycle_started_at TIMESTAMPTZ NULL"
    )
    op.execute(BACKFILL_SQL)
    # Znacznik jak w entrypoincie: start kontenera nie powtórzy uzupełnienia.
    op.execute(
        sa.text(
            "INSERT INTO app_settings (key, value) VALUES (:key, 'true'::jsonb) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(key=BACKFILL_MARKER)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key").bindparams(
            key=BACKFILL_MARKER
        )
    )
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS cycle_started_at")
