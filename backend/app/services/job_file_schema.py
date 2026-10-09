"""Pliki rekrutacji — SQL migracji 0427 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0427_job_files.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_job_files_migration_mirror.py`` sprawdza, że każda stoi w entrypoincie
dosłownie — po tabeli ``job_intake_forms``, na którą wskazuje klucz obcy.

Delivery Lead dokłada pliki przy zakładaniu rekrutacji (request klienta,
załączniki). Rekrutacja powstaje dopiero przy „Utwórz i przekaż”, więc do tego
czasu plik wisi na niedokończonym formularzu (``intake_form_id``), a transakcja
tworzenia przepina go na rekrutację (``job_id``). Wiersz bez obu powiązań to
sierota po usuniętym formularzu — sprząta ją ``queue_retention`` razem
z plikiem na dysku.
"""

from __future__ import annotations

SOURCE_REQUEST = "request"
SOURCE_UPLOAD = "upload"
SOURCES = (SOURCE_REQUEST, SOURCE_UPLOAD)

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS job_files ("
    "id SERIAL PRIMARY KEY, "
    "job_id INTEGER NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "intake_form_id INTEGER NULL REFERENCES job_intake_forms(id) ON DELETE SET NULL, "
    "source VARCHAR(16) NOT NULL DEFAULT 'upload', "
    "filename VARCHAR(255) NOT NULL, "
    "file_path VARCHAR(512) NOT NULL, "
    "content_type VARCHAR(128) NULL, "
    "size_bytes INTEGER NOT NULL DEFAULT 0, "
    "uploaded_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_job_files_source CHECK (source IN ('request', 'upload')))"
)

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_job_files_job ON job_files (job_id) "
    "WHERE job_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_job_files_intake_form ON job_files (intake_form_id) "
    "WHERE intake_form_id IS NOT NULL",
)

ALL_DDL = (TABLE_DDL, *INDEX_DDL)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS job_files",)
