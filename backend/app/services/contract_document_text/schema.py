"""Treść podpisanych dokumentów kontraktu (0789): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0789_contract_document_chunks.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

* ``contract_document_chunks`` — tekst pliku umowy, aneksu, wypowiedzenia albo
  porozumienia z Dokumentów kontraktu pocięty na fragmenty. ``id`` jest
  identyfikatorem punktu w kolekcji Qdranta ``nexus_contract_documents``
  (w Qdrancie same wektory, tekst tylko tutaj). Dane pochodne: da się je
  odbudować z pliku.
* ``contract_documents.text_*`` — stan odczytu: dla którego pliku zbudowano
  fragmenty i czy mają wektory. Zapis stanu nie rusza ``updated_at``.
"""

from __future__ import annotations

from app.services.framework_contract_text_schema import (  # noqa: F401 — te same stany
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_TEXT_ONLY,
    STATUS_UNREADABLE,
    STATUSES,
)

STATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("text_status", "VARCHAR(16)"),
    ("text_file_path", "VARCHAR(512)"),
    ("text_chars", "INTEGER"),
    ("text_pages", "INTEGER"),
    ("text_ocr_pages", "INTEGER"),
    ("text_model", "VARCHAR(64)"),
    ("text_attempted_at", "TIMESTAMPTZ"),
)

TABLE_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS contract_document_chunks ("
    "id BIGSERIAL PRIMARY KEY, "
    "contract_document_id INTEGER NOT NULL "
    "REFERENCES contract_documents(id) ON DELETE CASCADE, "
    "contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE, "
    "chunk_index INTEGER NOT NULL, "
    "text TEXT NOT NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_contract_document_chunks_position "
    "UNIQUE (contract_document_id, chunk_index))",
)

COLUMN_DDL: tuple[str, ...] = tuple(
    f"ALTER TABLE contract_documents ADD COLUMN IF NOT EXISTS {name} {kind} NULL"
    for name, kind in STATE_COLUMNS
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contract_document_chunks_contract "
    "ON contract_document_chunks (contract_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS contract_document_chunks",
    *(
        f"ALTER TABLE contract_documents DROP COLUMN IF EXISTS {name}"
        for name, _kind in STATE_COLUMNS
    ),
)
