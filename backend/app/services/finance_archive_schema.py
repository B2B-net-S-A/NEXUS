"""Archiwum dokumentów z eBI24 (E5): SQL migracji ``0720_finance_archive`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0720_finance_archive.py`` i
``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

* ``finance_archive_documents`` — dokument z archiwum eBI24 (faktury sprzedaży
  i kosztowe 2021–2026, ok. 50 tys.): numer, daty, kontrahent, kwoty (PLN i
  waluta), numer KSeF, folder i surowe metadane (``meta``). Plik leży na dysku
  pod ``UPLOADS_DIR/ebi24_archive/<rok>/<id eBI24>.<rozszerzenie>``: PDF/HTML
  wgranego dokumentu albo JSON faktury wystawionej w eBI24 (podgląd renderuje
  NEXUS). Import paczek jest idempotentny po ``source_id`` (id eBI24).

Decyzja Artura z 16.11.2026: archiwum eksportem przez przeglądarkę (tylko
odczyt) i import do NEXUSA, zanim wygaśnie umowa z eBI24.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("sale", "cost", "other")
FILE_TYPES: tuple[str, ...] = ("ebi", "pdf", "html", "xml", "image", "other")
SOURCE_ID_MAX = 32
NUMBER_MAX = 128
NAME_MAX = 512
TEXT_MAX = 255
AMOUNT_MAX = 10**11


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_ARCHIVE_KIND = f"kind IN ({_quoted(KINDS)})"
CK_ARCHIVE_FILE_TYPE = f"file_type IN ({_quoted(FILE_TYPES)})"
CK_ARCHIVE_META = "jsonb_typeof(meta) = 'object'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS finance_archive_documents (
    id SERIAL PRIMARY KEY,
    source VARCHAR(16) NOT NULL DEFAULT 'ebi24',
    source_id VARCHAR({SOURCE_ID_MAX}) NOT NULL,
    bucket_number INTEGER NULL,
    schema_name VARCHAR(64) NOT NULL,
    kind VARCHAR(8) NOT NULL,
    invoice_number VARCHAR({NUMBER_MAX}) NULL,
    title VARCHAR({TEXT_MAX}) NULL,
    issue_date DATE NULL,
    document_date DATE NULL,
    due_date DATE NULL,
    partner_name VARCHAR({NAME_MAX}) NULL,
    partner_id VARCHAR(64) NULL,
    currency VARCHAR(3) NULL,
    net_amount NUMERIC(14,2) NULL,
    vat_amount NUMERIC(14,2) NULL,
    gross_amount NUMERIC(14,2) NULL,
    gross_pln NUMERIC(14,2) NULL,
    paid BOOLEAN NULL,
    ksef_number VARCHAR(64) NULL,
    folder VARCHAR({TEXT_MAX}) NULL,
    file_type VARCHAR(8) NOT NULL,
    file_name VARCHAR({TEXT_MAX}) NULL,
    file_path VARCHAR({TEXT_MAX}) NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_sha256 VARCHAR(64) NOT NULL,
    meta JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    imported_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_finance_archive_documents_kind CHECK ({CK_ARCHIVE_KIND}),
    CONSTRAINT ck_finance_archive_documents_file_type CHECK ({CK_ARCHIVE_FILE_TYPE}),
    CONSTRAINT ck_finance_archive_documents_meta CHECK ({CK_ARCHIVE_META})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_archive_documents_source "
    "ON finance_archive_documents (source, source_id)",
    "CREATE INDEX IF NOT EXISTS ix_finance_archive_documents_date "
    "ON finance_archive_documents (issue_date DESC)",
    "CREATE INDEX IF NOT EXISTS ix_finance_archive_documents_partner "
    "ON finance_archive_documents (partner_id)",
    "CREATE INDEX IF NOT EXISTS ix_finance_archive_documents_number "
    "ON finance_archive_documents (lower(invoice_number))",
    "CREATE INDEX IF NOT EXISTS ix_finance_archive_documents_ksef "
    "ON finance_archive_documents (ksef_number) WHERE ksef_number IS NOT NULL",
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

TABLES: tuple[str, ...] = ("finance_archive_documents",)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in TABLES
)
