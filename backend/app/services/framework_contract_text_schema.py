"""Treść umów ramowych dla Jarvisa — SQL migracji 0426 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0426_framework_contract_text.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony).

* ``client_framework_contract_chunks`` — tekst wgranej umowy pocięty na
  fragmenty. Źródło treści dla wyszukiwania i czytania po kolei; ``id`` jest
  identyfikatorem punktu w kolekcji Qdranta ``nexus_client_documents``.
  Dane pochodne: da się je odbudować z pliku umowy.
* ``client_framework_contracts.text_*`` — stan odczytu: dla którego pliku
  zbudowano fragmenty i czy mają wektory.
"""

from __future__ import annotations

STATUS_INDEXED = "indexed"
STATUS_TEXT_ONLY = "text_only"
STATUS_UNREADABLE = "unreadable"
STATUS_FAILED = "failed"
STATUSES = (STATUS_INDEXED, STATUS_TEXT_ONLY, STATUS_UNREADABLE, STATUS_FAILED)

COLUMN_DDL = (
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_status VARCHAR(16) NULL",
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_file_path VARCHAR(512) NULL",
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_chars INTEGER NULL",
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_pages INTEGER NULL",
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_model VARCHAR(64) NULL",
    "ALTER TABLE client_framework_contracts "
    "ADD COLUMN IF NOT EXISTS text_attempted_at TIMESTAMPTZ NULL",
)

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS client_framework_contract_chunks ("
    "id BIGSERIAL PRIMARY KEY, "
    "framework_contract_id INTEGER NOT NULL "
    "REFERENCES client_framework_contracts(id) ON DELETE CASCADE, "
    "chunk_index INTEGER NOT NULL, "
    "text TEXT NOT NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_client_framework_contract_chunks_position "
    "UNIQUE (framework_contract_id, chunk_index))",
)

ALL_DDL = COLUMN_DDL + TABLE_DDL

DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS client_framework_contract_chunks",
    *(
        f"ALTER TABLE client_framework_contracts DROP COLUMN IF EXISTS {column}"
        for column in (
            "text_status",
            "text_file_path",
            "text_chars",
            "text_pages",
            "text_model",
            "text_attempted_at",
        )
    ),
)
