"""DDL przypisań „Prowadzi” — JEDNO źródło dla migracji 0519 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``candidate_job_owners``: bieżąca osoba prowadząca kandydata w rekrutacji,
przypisana ręcznie przez admina albo Head of Recruitment (decyzja Artura
25.10.2026). Brak wiersza = jak dotąd: pierwszy weryfikujący, a przed
weryfikacją osoba, która dodała. ``candidate_job_owner_events`` to historia
każdego przypisania (kto, kiedy, komu, kto był wcześniej, dlaczego).

Kolumny ``created_at`` / ``updated_at`` są dla scalania kandydatów:
konflikt klucza rozstrzyga nowszy wiersz (``candidate_merge``).
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS candidate_job_owners (
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
           owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           previous_owner_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           assigned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           reason TEXT NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (candidate_id, job_id)
       )""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_job_owners_owner
           ON candidate_job_owners (owner_user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_job_owners_job
           ON candidate_job_owners (job_id)""",
    """CREATE TABLE IF NOT EXISTS candidate_job_owner_events (
           id SERIAL PRIMARY KEY,
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
           owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           previous_owner_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           assigned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           reason TEXT NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_job_owner_events_pair
           ON candidate_job_owner_events (candidate_id, job_id)""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS candidate_job_owner_events",
    "DROP TABLE IF EXISTS candidate_job_owners",
]
