"""Dokumenty Rady nadzorczej (R1): SQL migracji ``0727_board_documents`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0727_board_documents.py`` i
``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda instrukcja
idempotentna.

* ``board_documents`` — rejestr dokumentów korporacyjnych spółki: statut,
  regulaminy, protokoły i uchwały WZA, RN i Zarządu, sprawozdania. Wiersz
  zakłada admin (Zarząd) z plikiem albo automat z odpisu KRS (``source='krs'``,
  ``krs_key`` = wzmianka, np. ``fs_approval:2025``) — wtedy bez pliku, dopóki
  Zarząd nie dołączy skanu. ``extraction`` to propozycja odczytu modelu
  (numer, data, organ, przedmiot) do zatwierdzenia, nigdy wartość pól.
* ``board_krs_snapshots`` — odpis pełny KRS spółki pobierany co noc; nowy
  wiersz tylko, gdy zmienił się skrót treści. Liczba wpisów i data ostatniego
  wpisu stoją w kolumnach, cały odpis w ``payload``.

Decyzje Artura z 16.11.2026: sekcja „Rada”, Rada czyta, admini wgrywają.
"""

from __future__ import annotations

CATEGORIES: tuple[str, ...] = (
    "statute",
    "rules_management",
    "rules_supervisory",
    "minutes_general",
    "minutes_supervisory",
    "minutes_management",
    "resolution_general",
    "resolution_supervisory",
    "resolution_management",
    "financial_statement",
    "other",
)
ORGANS: tuple[str, ...] = ("general", "supervisory", "management")
SOURCES: tuple[str, ...] = ("upload", "krs")
EXTRACTION_STATUSES: tuple[str, ...] = ("none", "read", "failed", "skipped")
TITLE_MAX = 255
NUMBER_MAX = 64
NAME_MAX = 255


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_CATEGORY = f"category IN ({_quoted(CATEGORIES)})"
CK_ORGAN = f"organ IS NULL OR organ IN ({_quoted(ORGANS)})"
CK_SOURCE = f"source IN ({_quoted(SOURCES)})"
CK_EXTRACTION_STATUS = f"extraction_status IN ({_quoted(EXTRACTION_STATUSES)})"
CK_EXTRACTION = "jsonb_typeof(extraction) = 'object'"
CK_PAYLOAD = "jsonb_typeof(payload) = 'object'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_documents (
    id SERIAL PRIMARY KEY,
    category VARCHAR(32) NOT NULL,
    organ VARCHAR(16) NULL,
    number VARCHAR({NUMBER_MAX}) NULL,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    subject TEXT NULL,
    doc_date DATE NULL,
    source VARCHAR(8) NOT NULL DEFAULT 'upload',
    krs_key VARCHAR(64) NULL,
    krs_entry_no INTEGER NULL,
    krs_entry_date DATE NULL,
    file_name VARCHAR({NAME_MAX}) NULL,
    file_path VARCHAR({NAME_MAX}) NULL,
    content_type VARCHAR(128) NULL,
    file_size INTEGER NULL,
    file_sha256 VARCHAR(64) NULL,
    extraction_status VARCHAR(8) NOT NULL DEFAULT 'none',
    extraction JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_documents_category CHECK ({CK_CATEGORY}),
    CONSTRAINT ck_board_documents_organ CHECK ({CK_ORGAN}),
    CONSTRAINT ck_board_documents_source CHECK ({CK_SOURCE}),
    CONSTRAINT ck_board_documents_extraction_status CHECK ({CK_EXTRACTION_STATUS}),
    CONSTRAINT ck_board_documents_extraction CHECK ({CK_EXTRACTION})
)""",
    f"""CREATE TABLE IF NOT EXISTS board_krs_snapshots (
    id SERIAL PRIMARY KEY,
    krs VARCHAR(10) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    entries_count INTEGER NOT NULL,
    last_entry_no INTEGER NULL,
    last_entry_date DATE NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_krs_snapshots_payload CHECK ({CK_PAYLOAD})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_documents_krs_key "
    "ON board_documents (krs_key) WHERE krs_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_board_documents_category_date "
    "ON board_documents (category, doc_date DESC NULLS LAST)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_krs_snapshots_krs_sha "
    "ON board_krs_snapshots (krs, sha256)",
    "CREATE INDEX IF NOT EXISTS ix_board_krs_snapshots_krs_fetched "
    "ON board_krs_snapshots (krs, fetched_at DESC)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL, *CONSTRAINT_DDL, *DATA_DDL)

TABLES: tuple[str, ...] = ("board_documents", "board_krs_snapshots")

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS board_krs_snapshots",
    "DROP TABLE IF EXISTS board_documents",
)
