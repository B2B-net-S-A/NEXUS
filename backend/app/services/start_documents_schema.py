"""Dokumenty do startu — SQL migracji 0649 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0649_start_documents.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.start_document``.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("file", "pesel", "agreement")
STATUSES: tuple[str, ...] = ("delivered", "returned", "not_applicable")

CLIENT_DOCUMENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS client_start_documents ("
    "id SERIAL PRIMARY KEY, "
    "client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE, "
    "position SMALLINT NOT NULL DEFAULT 0, "
    "name VARCHAR(200) NOT NULL, "
    "note VARCHAR(300) NULL, "
    "kind VARCHAR(16) NOT NULL DEFAULT 'file', "
    "required BOOLEAN NOT NULL DEFAULT true, "
    "offset_days SMALLINT NOT NULL DEFAULT -2, "
    "link_url VARCHAR(500) NULL, "
    "fill_from_agreement BOOLEAN NOT NULL DEFAULT false, "
    "template_path VARCHAR(512) NULL, "
    "template_name VARCHAR(255) NULL, "
    "template_content_type VARCHAR(128) NULL, "
    "archived_at TIMESTAMPTZ NULL, "
    "created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_client_start_documents_kind "
    "CHECK (kind IN ('file', 'pesel', 'agreement')), "
    "CONSTRAINT ck_client_start_documents_name CHECK (btrim(name) <> ''), "
    "CONSTRAINT ck_client_start_documents_offset "
    "CHECK (offset_days BETWEEN -30 AND 30)"
    ")"
)
CLIENT_DOCUMENTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_client_start_documents_client "
    "ON client_start_documents (client_id) WHERE archived_at IS NULL"
)
PLACEMENT_DOCUMENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS placement_start_documents ("
    "id SERIAL PRIMARY KEY, "
    "document_id INTEGER NOT NULL "
    "REFERENCES client_start_documents(id) ON DELETE CASCADE, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "status VARCHAR(16) NOT NULL, "
    "file_path VARCHAR(512) NULL, "
    "file_name VARCHAR(255) NULL, "
    "file_content_type VARCHAR(128) NULL, "
    "pesel VARCHAR(11) NULL, "
    "delivered_at TIMESTAMPTZ NULL, "
    "delivered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "checked_at TIMESTAMPTZ NULL, "
    "checked_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "reason VARCHAR(500) NULL, "
    "reason_at TIMESTAMPTZ NULL, "
    "reason_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_placement_start_documents_pair "
    "UNIQUE (document_id, candidate_id, job_id), "
    "CONSTRAINT ck_placement_start_documents_status "
    "CHECK (status IN ('delivered', 'returned', 'not_applicable'))"
    ")"
)
PLACEMENT_DOCUMENTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_placement_start_documents_pair "
    "ON placement_start_documents (candidate_id, job_id)"
)
PLACEMENT_DOCUMENTS_JOB_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_placement_start_documents_job "
    "ON placement_start_documents (job_id)"
)

TABLE_DDL: tuple[str, ...] = (
    CLIENT_DOCUMENTS_DDL,
    CLIENT_DOCUMENTS_INDEX,
    PLACEMENT_DOCUMENTS_DDL,
    PLACEMENT_DOCUMENTS_INDEX,
    PLACEMENT_DOCUMENTS_JOB_INDEX,
)
#: Poza transakcją: ``ALTER TYPE … ADD VALUE`` (``autocommit_block`` w migracji).
ENUM_DDL: tuple[str, ...] = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'start_documents'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'start_documents_due'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'start_documents_returned'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'start_documents_reminder'",
)
