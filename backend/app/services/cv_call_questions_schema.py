"""Pytania pod CV w ściądze do rozmowy — SQL migracji 0650 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0650_cv_call_questions.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.cv_call_question``.
"""

from __future__ import annotations

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS cv_call_questions ("
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "status VARCHAR(10) NOT NULL DEFAULT 'ready', "
    "inputs_hash VARCHAR(64) NOT NULL, "
    "model VARCHAR(80) NULL, "
    "questions JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "generated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "PRIMARY KEY (candidate_id, job_id), "
    "CONSTRAINT ck_cv_call_questions_status CHECK (status IN ('ready', 'failed'))"
    ")",
    "CREATE INDEX IF NOT EXISTS ix_cv_call_questions_job ON cv_call_questions (job_id)",
)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS cv_call_questions",)
