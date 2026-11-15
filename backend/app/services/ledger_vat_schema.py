"""Pliki JPK_V7M (K5b) — SQL migracji ``0708_ledger_vat_files``.

Jedno źródło DDL dla ``alembic/versions/0708_ledger_vat_files.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda instrukcja
idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

* ``ledger_vat_files`` — przygotowany plik JPK_V7M (ewidencja VAT z deklaracją
  VAT-7) za miesiąc: kolejna wersja (1, 2, …), cel złożenia (``submission`` =
  złożenie, ``correction`` = korekta z uzasadnieniem P_ORDZU — po wysłanej
  wersji), treść XML i jej SHA-256, sumy deklaracji (``totals``: P_38, P_48,
  P_51, P_53, P_62, liczby wierszy, odcisk rejestrów), stan ``prepared`` /
  ``sent`` (wysłany — oznacza księgowa po wysłaniu bramką MF, z numerem UPO
  w ``sent_note``). Plik zawiera faktury osób zespołu (D2) — pobiera go tylko
  osoba z Płacami albo administrator.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

PURPOSES: tuple[str, ...] = ("submission", "correction")
STATUSES: tuple[str, ...] = ("prepared", "sent")
#: P_ORDZU (etd:TTekstowy) — do 3500 znaków.
REASON_MAX = 3500
NOTE_MAX = 200

CK_PERIOD = "month BETWEEN 1 AND 12 AND version >= 1"
CK_PURPOSE = f"purpose IN ({quoted(PURPOSES)})"
CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_REASON = "purpose <> 'correction' OR reason IS NOT NULL"
CK_SENT = "(status = 'sent') = (sent_at IS NOT NULL)"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_vat_files (
    id BIGSERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    version SMALLINT NOT NULL,
    purpose VARCHAR(12) NOT NULL,
    reason VARCHAR({REASON_MAX}) NULL,
    content BYTEA NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    totals JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    status VARCHAR(10) NOT NULL DEFAULT 'prepared',
    sent_at TIMESTAMPTZ NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    sent_note VARCHAR({NOTE_MAX}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_vat_files_version UNIQUE (year, month, version),
    CONSTRAINT ck_ledger_vat_files_period CHECK ({CK_PERIOD}),
    CONSTRAINT ck_ledger_vat_files_purpose CHECK ({CK_PURPOSE}),
    CONSTRAINT ck_ledger_vat_files_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_ledger_vat_files_reason CHECK ({CK_REASON}),
    CONSTRAINT ck_ledger_vat_files_sent CHECK ({CK_SENT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = ()

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS ledger_vat_files",)
