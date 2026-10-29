"""DDL ocen „Oceń z AI” — JEDNO źródło dla migracji 0617 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``candidate_ai_assessments``: jeden wiersz na osobę ocenioną w jednym
kliknięciu „Oceń z AI” (``batch_id``) w oknie „Kandydaci do dodania”
(decyzja Artura 28.10.2026, makieta C https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS).
Kto (``assessed_by``), kiedy, kogo, w jakiej rekrutacji i z jakim werdyktem —
żeby po zamknięciu panelu wrócić do wyniku bez ponownego wywołania modelu.
``verdict`` NULL = „AI nie oceniło” (brak CV, awaria modelu), ``error`` to
kod przyczyny, nigdy treść odpowiedzi. ``model_called`` liczy dzienny limit;
wynik przepisany z oceny sprzed < 24 h ma ``reused_from_id`` i limitu nie zużywa.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS candidate_ai_assessments (
           id SERIAL PRIMARY KEY,
           batch_id VARCHAR(36) NOT NULL,
           job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           assessed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           selection_index INTEGER NOT NULL DEFAULT 0,
           verdict VARCHAR(16) NULL,
           strength SMALLINT NULL,
           must_found INTEGER NOT NULL DEFAULT 0,
           must_total INTEGER NOT NULL DEFAULT 0,
           reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
           model VARCHAR(64) NULL,
           error VARCHAR(120) NULL,
           model_called BOOLEAN NOT NULL DEFAULT FALSE,
           reused_from_id INTEGER NULL
               REFERENCES candidate_ai_assessments(id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_candidate_ai_assessments_verdict
               CHECK (verdict IS NULL OR verdict IN ('call', 'maybe', 'no_fit'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_ai_assessments_job_user
           ON candidate_ai_assessments (job_id, assessed_by, created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_ai_assessments_user_day
           ON candidate_ai_assessments (assessed_by, created_at)""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_ai_assessments_batch
           ON candidate_ai_assessments (batch_id)""",
]
