"""Stawki z dokumentów kontraktu (0739): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0739_contract_rate_documents.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

``contract_document_rate_reads`` — jeden wiersz na plik w Dokumentach kontraktu
i wersję czytnika: co model odczytał o stawce Partnera (``result``), jaka
różnica z harmonogramem z tego wynika (``finding``, przeliczane przez pętlę)
i co z nią zrobiono (``decision``). Odczyt to propozycja: stawka w kontrakcie
zmienia się wyłącznie aneksem ``rate_change`` (człowiek albo wpis automatyczny
za flagą), nigdy zapisem w tej tabeli.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = ("read", "failed", "skipped")
DECISIONS: tuple[str, ...] = ("applied", "auto_applied", "dismissed", "undone")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS contract_document_rate_reads (
    id SERIAL PRIMARY KEY,
    contract_document_id INTEGER NOT NULL REFERENCES contract_documents(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    content_sha256 VARCHAR(64) NULL,
    reader_version VARCHAR(32) NOT NULL,
    status VARCHAR(8) NOT NULL,
    result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    finding JSONB NULL,
    has_finding BOOLEAN NOT NULL DEFAULT FALSE,
    decision VARCHAR(16) NULL,
    decision_amendment_ids JSONB NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_contract_document_rate_reads_status CHECK (status IN ({_quoted(STATUSES)})),
    CONSTRAINT ck_contract_document_rate_reads_decision CHECK (decision IS NULL OR decision IN ({_quoted(DECISIONS)})),
    CONSTRAINT ck_contract_document_rate_reads_result CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT uq_contract_document_rate_reads_doc_version UNIQUE (contract_document_id, reader_version)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contract_document_rate_reads_contract "
    "ON contract_document_rate_reads (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_contract_document_rate_reads_open "
    "ON contract_document_rate_reads (contract_id) WHERE has_finding AND decision IS NULL",
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

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS contract_document_rate_reads",)
