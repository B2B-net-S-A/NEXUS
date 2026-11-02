"""DDL powodów „co generator zrobił źle” — JEDNO źródło dla migracji 0634
i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``cv_generator_feedback``: jeden wiersz na pobranie oryginału CV po złym wyniku
generatora (decyzja Artura 02.11.2026). Bez kopii treści CV: tylko odnośniki do
pary i generacji, kody powodów (``cv_download_policy.FEEDBACK_REASONS``)
i opcjonalny opis rekrutera.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS cv_generator_feedback (
           id SERIAL PRIMARY KEY,
           candidate_stage_id INTEGER NULL
               REFERENCES candidate_stages(id) ON DELETE SET NULL,
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
           client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
           generated_document_id INTEGER NULL
               REFERENCES cv_generated_documents(id) ON DELETE SET NULL,
           generation_status VARCHAR(16) NOT NULL,
           client_rule_version INTEGER NULL,
           content_mode VARCHAR(32) NULL,
           reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
           detail TEXT NULL,
           created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    """CREATE INDEX IF NOT EXISTS ix_cv_generator_feedback_created_at
           ON cv_generator_feedback (created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS ix_cv_generator_feedback_client
           ON cv_generator_feedback (client_id, created_at DESC)""",
]
