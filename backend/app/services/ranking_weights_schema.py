"""DDL panelu wag rankingu — JEDNO źródło dla migracji 0501 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``scoring_weight_measurements``: pomiar szkicu na zamkniętych rekrutacjach
(zadanie w tle, tylko odczyt); publikacja wymaga ukończonego pomiaru tego
samego szkicu (``fingerprint``).

``scoring_weight_changes``: wiersz = jedna zmiana wag, które obowiązują
w „Dop.”: publikacja z panelu „Ranking kandydatów” (Head of Recruitment, po
pomiarze na historii) albo edycja profilu przez administratora starymi trasami. ``profile_id`` bez klucza
obcego: profil bywa usuwany, a ślad zmiany ma zostać.
"""

from __future__ import annotations

CHANGE_KINDS: tuple[str, ...] = ("publish", "admin_edit")
MEASUREMENT_STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed")

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS scoring_weight_changes (
           id SERIAL PRIMARY KEY,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           actor_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           kind VARCHAR(16) NOT NULL,
           profile_id INTEGER NULL,
           before JSONB NOT NULL,
           after JSONB NOT NULL,
           reason TEXT NULL,
           measurement JSONB NULL,
           CONSTRAINT ck_scoring_weight_changes_kind
               CHECK (kind IN ('publish', 'admin_edit'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_scoring_weight_changes_created
       ON scoring_weight_changes (created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS scoring_weight_measurements (
           id SERIAL PRIMARY KEY,
           status VARCHAR(16) NOT NULL DEFAULT 'queued',
           requested_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           baseline JSONB NOT NULL,
           draft JSONB NOT NULL,
           fingerprint VARCHAR(64) NOT NULL,
           progress JSONB NULL,
           result JSONB NULL,
           error TEXT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           started_at TIMESTAMPTZ NULL,
           finished_at TIMESTAMPTZ NULL,
           CONSTRAINT ck_scoring_weight_measurements_status
               CHECK (status IN ('queued', 'running', 'done', 'failed'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_scoring_weight_measurements_created
       ON scoring_weight_measurements (created_at DESC)""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS scoring_weight_measurements",
    "DROP TABLE IF EXISTS scoring_weight_changes",
]
