"""DDL folderów w zakładce Dokumenty kontraktu — JEDNO źródło dla migracji
0494 i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Kolejność jest load-bearing: tabela folderów powstaje PRZED kolumną
``contract_documents.folder_id``, która na nią wskazuje.

Folder „Zamówienia” nie ma wiersza, dopóki nikt nie zmieni jego nazwy —
o tym, co w nim leży, decyduje typ dokumentu (``order``), nie ``folder_id``.
Wiersz ``kind = 'orders'`` trzyma tylko własną nazwę folderu na kontrakcie.
"""

from __future__ import annotations

FOLDER_KINDS: tuple[str, ...] = ("user", "orders")

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS contract_document_folders (
           id SERIAL PRIMARY KEY,
           contract_id INTEGER NOT NULL
               REFERENCES contracts (id) ON DELETE CASCADE,
           name VARCHAR(120) NOT NULL,
           kind VARCHAR(16) NOT NULL DEFAULT 'user',
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_contract_document_folders_kind
               CHECK (kind IN ('user', 'orders'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_contract_document_folders_contract
       ON contract_document_folders (contract_id)""",
    # Dwa foldery o tej samej nazwie na jednym kontrakcie czytają się jak jeden.
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_document_folders_name
       ON contract_document_folders (contract_id, lower(name))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_document_folders_orders
       ON contract_document_folders (contract_id) WHERE kind = 'orders'""",
    # Usunięcie folderu nie usuwa plików — wracają do „Aktualnej umowy”.
    """ALTER TABLE contract_documents
       ADD COLUMN IF NOT EXISTS folder_id INTEGER NULL
       REFERENCES contract_document_folders (id) ON DELETE SET NULL""",
    """CREATE INDEX IF NOT EXISTS ix_contract_documents_folder
       ON contract_documents (folder_id)""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP INDEX IF EXISTS ix_contract_documents_folder",
    "ALTER TABLE contract_documents DROP COLUMN IF EXISTS folder_id",
    "DROP TABLE IF EXISTS contract_document_folders",
]
