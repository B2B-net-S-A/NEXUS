"""Dane firm z umów (E5a, 0755): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0755_contract_partner_reads.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

``contract_partner_reads`` — jeden wiersz na plik umowy i wersję czytnika: co
model odczytał o firmie Partnera (``result``: pola z cytatami, uwagi kodu),
co powiedział rejestr przy sprawdzeniu na żądanie (``verification``) i co
zrobił człowiek (``decision``). Odczyt to propozycja: profil kandydata zmienia
wyłącznie „Zastosuj” człowieka (``candidate_changes``), a ``confirmed`` to
potwierdzone dane dla masowej wysyłki nowej umowy (osobny PR).
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = ("read", "failed", "skipped")
DECISIONS: tuple[str, ...] = ("applied", "dismissed")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS contract_partner_reads (
    id SERIAL PRIMARY KEY,
    contract_document_id INTEGER NOT NULL REFERENCES contract_documents(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    content_sha256 VARCHAR(64) NULL,
    reader_version VARCHAR(32) NOT NULL,
    status VARCHAR(8) NOT NULL,
    result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    verification JSONB NULL,
    verified_at TIMESTAMPTZ NULL,
    decision VARCHAR(16) NULL,
    confirmed JSONB NULL,
    candidate_changes JSONB NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_contract_partner_reads_status CHECK (status IN ({_quoted(STATUSES)})),
    CONSTRAINT ck_contract_partner_reads_decision CHECK (decision IS NULL OR decision IN ({_quoted(DECISIONS)})),
    CONSTRAINT ck_contract_partner_reads_result CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT uq_contract_partner_reads_doc_version UNIQUE (contract_document_id, reader_version)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contract_partner_reads_contract "
    "ON contract_partner_reads (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_contract_partner_reads_open "
    "ON contract_partner_reads (contract_id) WHERE status = 'read' AND decision IS NULL",
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

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS contract_partner_reads",)
