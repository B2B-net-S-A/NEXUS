"""Paczki księgi do Symfonii FK (K3b) — SQL migracji ``0702_ledger_exports``.

Jedno źródło DDL dla ``alembic/versions/0702_ledger_exports.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda instrukcja
idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

Do przełączenia (tryb roku „symfonia” albo „równolegle”) księgą urzędową jest
Symfonia FK: dokumenty, które NEXUS robi sam, idą do niej plikiem, zamiast być
przepisywane ręcznie.

* ``ledger_exports`` — paczka miesiąca: numer ``K/RRRR-MM/n``, status
  (pobrana → zaksięgowana w Symfonii albo anulowana), rodzaje dokumentów,
  format, bajty pliku i SHA-256 (ponowne pobranie daje ten sam plik), suma Wn
  i znacznik dokumentów płacowych (D2: paczkę z nimi widzą tylko Płace i admin).
* ``ledger_export_documents`` — dokumenty paczki. Dokument jest najwyżej
  w jednej aktywnej paczce (indeks unikalny częściowy); anulowanie paczki
  zwalnia jej dokumenty do następnej.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

EXPORT_STATUSES: tuple[str, ...] = ("exported", "booked", "cancelled")
NUMBER_MAX = 32
FORMAT_MAX = 20
FILE_NAME_MAX = 120

CK_EXPORT_STATUS = f"status IN ({quoted(EXPORT_STATUSES)})"
CK_EXPORT_KINDS = "jsonb_typeof(kinds) = 'array'"
CK_EXPORT_COUNT = "document_count > 0"
EXPORT_ITEM_ACTIVE_WHERE = "active"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_exports (
    id SERIAL PRIMARY KEY,
    year_id INTEGER NOT NULL REFERENCES ledger_years(id) ON DELETE RESTRICT,
    period_id INTEGER NOT NULL REFERENCES ledger_periods(id) ON DELETE RESTRICT,
    number VARCHAR({NUMBER_MAX}) NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'exported',
    kinds JSONB NOT NULL DEFAULT '[]'::jsonb,
    file_format VARCHAR({FORMAT_MAX}) NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NOT NULL,
    file_content BYTEA NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    document_count INTEGER NOT NULL,
    debit_total BIGINT NOT NULL,
    has_payroll BOOLEAN NOT NULL DEFAULT false,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    booked_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    booked_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_ledger_exports_number UNIQUE (number),
    CONSTRAINT ck_ledger_exports_status CHECK ({CK_EXPORT_STATUS}),
    CONSTRAINT ck_ledger_exports_kinds CHECK ({CK_EXPORT_KINDS}),
    CONSTRAINT ck_ledger_exports_count CHECK ({CK_EXPORT_COUNT})
)""",
    """CREATE TABLE IF NOT EXISTS ledger_export_documents (
    export_id INTEGER NOT NULL REFERENCES ledger_exports(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES ledger_documents(id) ON DELETE RESTRICT,
    active BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (export_id, document_id)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_ledger_exports_period "
    "ON ledger_exports (period_id, id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_export_documents_active "
    f"ON ledger_export_documents (document_id) WHERE {EXPORT_ITEM_ACTIVE_WHERE}",
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
    "DROP TABLE IF EXISTS ledger_export_documents",
    "DROP TABLE IF EXISTS ledger_exports",
)
