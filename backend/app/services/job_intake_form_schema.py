"""Niedokończone formularze „Nowa rekrutacja” — SQL migracji 0416 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0416_job_intake_forms.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_job_intake_forms.py`` sprawdza, że każda stoi w entrypoincie dosłownie.

Od 04.10.2026 rekrutacja nigdy nie jest szkicem: utworzenie = przekazanie do
searchu = publikacja. Formularz, którego Delivery Lead nie skończył, żyje na
jego koncie (``job_intake_forms``) — nie jako rekrutacja w bazie.
"""

from __future__ import annotations

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS job_intake_forms ("
    "id SERIAL PRIMARY KEY, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL, "
    "label VARCHAR(255) NOT NULL DEFAULT '', "
    "source VARCHAR(20) NOT NULL DEFAULT 'manual', "
    "request_text TEXT NULL, "
    "form JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_job_intake_forms_user_updated "
    "ON job_intake_forms (user_id, updated_at)"
)
