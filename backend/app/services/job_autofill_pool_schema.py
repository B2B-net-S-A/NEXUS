"""DDL puli dopełniania „Nowych” — JEDNO źródło dla migracji 0513 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``job_autofill_pool``: najlepsze osoby z najnowszego nocnego przeglądu
rekrutacji — dopuszczone i zmierzone, z KAŻDYM wynikiem (decyzja Artura
23.10.2026: „Nowi” trzymani na 20 także osobami poniżej progu propozycji).
Przegląd kasuje retencja po 2 dniach, pula zostaje do następnego przeglądu
tej rekrutacji. ``run_id`` bez FK (z tego samego powodu co w ``job_proposals``),
``evidence`` = same nazwy wymagań (``matched_must``, ``missing_must``).
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS job_autofill_pool (
           job_id INTEGER NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
           candidate_id INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
           score NUMERIC(5, 2) NOT NULL,
           run_id VARCHAR(36) NOT NULL,
           cv_revision VARCHAR(64) NULL,
           evidence JSONB NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (job_id, candidate_id)
       )""",
    "CREATE INDEX IF NOT EXISTS ix_job_autofill_pool_job_score "
    "ON job_autofill_pool (job_id, score)",
    "CREATE INDEX IF NOT EXISTS ix_job_autofill_pool_candidate_id "
    "ON job_autofill_pool (candidate_id)",
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS job_autofill_pool"]
