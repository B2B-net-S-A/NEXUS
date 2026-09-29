"""DDL dokumentów kontraktów z SharePointa — JEDNO źródło dla migracji 0402
i siatki bezpieczeństwa w ``entrypoint.sh`` (produkcyjny alembic bywa
osierocony; wzór: ``services/b2b_register_import/schema_sql.py``).

Kolejność jest load-bearing: tabela przebiegów powstaje PRZED kolumną
``contract_documents.import_run_id``, która na nią wskazuje.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS contract_doc_sp_runs (
           id SERIAL PRIMARY KEY,
           mode VARCHAR(16) NOT NULL,
           source_url TEXT NULL,
           drive_id VARCHAR(255) NULL,
           folder_item_id VARCHAR(255) NULL,
           counters JSONB NOT NULL DEFAULT '{}'::jsonb,
           error VARCHAR(500) NULL,
           lease_until TIMESTAMPTZ NULL,
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           applied_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           applied_at TIMESTAMPTZ NULL,
           rolled_back_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           rolled_back_at TIMESTAMPTZ NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_contract_doc_sp_runs_mode CHECK (mode IN (
               'listing', 'preview', 'applying', 'applied',
               'rolled_back', 'failed'))
       )""",
    """CREATE TABLE IF NOT EXISTS contract_doc_sp_run_items (
           id SERIAL PRIMARY KEY,
           run_id INTEGER NOT NULL
               REFERENCES contract_doc_sp_runs (id) ON DELETE CASCADE,
           kind VARCHAR(16) NOT NULL,
           folder_name VARCHAR(255) NULL,
           file_name VARCHAR(512) NULL,
           item_id VARCHAR(255) NULL,
           size_bytes BIGINT NULL,
           doc_type VARCHAR(32) NULL,
           contract_id INTEGER NULL REFERENCES contracts (id) ON DELETE SET NULL,
           candidate_id INTEGER NULL,
           person_name VARCHAR(255) NULL,
           match_kind VARCHAR(16) NULL,
           reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
           note VARCHAR(500) NULL,
           selected BOOLEAN NOT NULL DEFAULT true,
           status VARCHAR(24) NOT NULL DEFAULT 'info',
           contract_document_id INTEGER NULL
               REFERENCES contract_documents (id) ON DELETE SET NULL,
           error VARCHAR(255) NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_contract_doc_sp_run_items_kind CHECK (kind IN (
               'assignment', 'contract', 'folder', 'file'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_contract_doc_sp_run_items_run
       ON contract_doc_sp_run_items (run_id, kind)""",
    # Stan każdego pliku z folderu na SharePoincie — synchronizacja nie
    # przetwarza drugi raz pliku, którego stan się nie zmienił (``c_tag``).
    """CREATE TABLE IF NOT EXISTS contract_doc_sp_items (
           item_id VARCHAR(255) PRIMARY KEY,
           drive_id VARCHAR(255) NOT NULL,
           folder_name VARCHAR(255) NULL,
           file_name VARCHAR(512) NOT NULL,
           size_bytes BIGINT NULL,
           c_tag VARCHAR(255) NULL,
           status VARCHAR(24) NOT NULL,
           reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
           proposed_contract_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
           decided_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_contract_doc_sp_items_status CHECK (status IN (
               'imported', 'skipped', 'waiting_contract', 'review',
               'dismissed', 'pushed'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_contract_doc_sp_items_status
       ON contract_doc_sp_items (status)""",
    # ── Nowe kolumny dokumentów kontraktu ──────────────────────────────────
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR(64) NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS source VARCHAR(24) NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL
       REFERENCES contract_doc_sp_runs (id) ON DELETE SET NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS sharepoint_item_id VARCHAR(255) NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS sharepoint_push_status VARCHAR(16) NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS sharepoint_push_error VARCHAR(255) NULL""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS sharepoint_push_attempts INTEGER NOT NULL
       DEFAULT 0""",
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS sharepoint_pushed_at TIMESTAMPTZ NULL""",
    """CREATE INDEX IF NOT EXISTS ix_contract_documents_contract_sha
       ON contract_documents (contract_id, content_sha256)""",
    """CREATE INDEX IF NOT EXISTS ix_contract_documents_sharepoint_item
       ON contract_documents (sharepoint_item_id)""",
    """CREATE INDEX IF NOT EXISTS ix_contract_documents_import_run
       ON contract_documents (import_run_id)""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP INDEX IF EXISTS ix_contract_documents_import_run",
    "DROP INDEX IF EXISTS ix_contract_documents_sharepoint_item",
    "DROP INDEX IF EXISTS ix_contract_documents_contract_sha",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS sharepoint_pushed_at",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS sharepoint_push_attempts",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS sharepoint_push_error",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS sharepoint_push_status",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS sharepoint_item_id",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS import_run_id",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS source",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS content_sha256",
    "DROP TABLE IF EXISTS contract_doc_sp_items",
    "DROP TABLE IF EXISTS contract_doc_sp_run_items",
    "DROP TABLE IF EXISTS contract_doc_sp_runs",
]
