"""Wyciągi bankowe w księdze (K4a) — SQL migracji ``0705_ledger_bank``.

Jedno źródło DDL dla ``alembic/versions/0705_ledger_bank.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda instrukcja
idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar, decyzja
Artura z 14.11.2026: jeden import wyciągu w Księdze.

* ``ledger_bank_statements`` — wyciąg wgrany w Księdze: skrót pliku (jeden
  plik = jeden wyciąg), rachunek firmy i jego konto w planie, daty operacji,
  liczba pozycji i sumy obciążeń i uznań w groszach (K4a: tylko PLN).
* ``ledger_bank_lines`` — operacje wyciągu z rozpoznaniem: faktura kosztowa
  (E3), rozliczenie osoby z zespołu (R9, płacowe — D2), faktura sprzedaży
  (E8), ZUS, urząd skarbowy, opłata banku, przypisana ręcznie, do wyjaśnienia
  albo duplikat operacji z innego wyciągu. Konto przeciwstawne i kontrahent
  dla dokumentu WB. Pełnego rachunku kontrahenta nie trzymamy — tylko cztery
  ostatnie cyfry, jak E3 i R9.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted
from app.services.ledger_schema import ACCOUNT_MAX

LINE_KINDS: tuple[str, ...] = (
    "cost_invoice",
    "team",
    "sales_invoice",
    "zus",
    "tax",
    "fee",
    "manual",
    "unmatched",
    "duplicate",
)
DIRECTIONS: tuple[str, ...] = ("debit", "credit")
TITLE_MAX = 300
NAME_MAX = 200
NOTE_MAX = 300
LINE_REF_MAX = 64
BANK_REF_MAX = 48

#: Waluty rachunków firmy (jak E8 i R9). K4a: tylko PLN; K4c-1 (0707) dodaje EUR
#: i USD — CHECK na istniejącej bazie zamienia ``ledger_fx_schema``.
CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
CK_STATEMENT_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_LINE_DIRECTION = f"direction IN ({quoted(DIRECTIONS)})"
CK_LINE_KIND = f"kind IN ({quoted(LINE_KINDS)})"
CK_LINE_AMOUNT = "amount > 0"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_bank_statements (
    id SERIAL PRIMARY KEY,
    sha256 VARCHAR(64) NOT NULL,
    format VARCHAR(8) NOT NULL,
    bank_account VARCHAR(26) NOT NULL,
    ledger_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    first_day DATE NOT NULL,
    last_day DATE NOT NULL,
    line_count INTEGER NOT NULL,
    debit_total BIGINT NOT NULL,
    credit_total BIGINT NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_bank_statements_sha UNIQUE (sha256),
    CONSTRAINT ck_ledger_bank_statements_currency CHECK ({CK_STATEMENT_CURRENCY})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_bank_lines (
    id BIGSERIAL PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES ledger_bank_statements(id) ON DELETE CASCADE,
    line_ref VARCHAR({LINE_REF_MAX}) NOT NULL,
    position INTEGER NOT NULL,
    bank_ref VARCHAR({BANK_REF_MAX}) NOT NULL DEFAULT '',
    booked_on DATE NOT NULL,
    direction VARCHAR(6) NOT NULL,
    amount BIGINT NOT NULL,
    title VARCHAR({TITLE_MAX}) NOT NULL DEFAULT '',
    counterparty_name VARCHAR({NAME_MAX}) NOT NULL DEFAULT '',
    counterparty_last4 VARCHAR(4) NULL,
    kind VARCHAR(16) NOT NULL,
    ref_id INTEGER NULL,
    counter_account VARCHAR({ACCOUNT_MAX}) NULL,
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE SET NULL,
    payroll BOOLEAN NOT NULL DEFAULT false,
    note VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    assigned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_ledger_bank_lines_ref UNIQUE (statement_id, line_ref),
    CONSTRAINT ck_ledger_bank_lines_direction CHECK ({CK_LINE_DIRECTION}),
    CONSTRAINT ck_ledger_bank_lines_kind CHECK ({CK_LINE_KIND}),
    CONSTRAINT ck_ledger_bank_lines_amount CHECK ({CK_LINE_AMOUNT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_ledger_bank_statements_account "
    "ON ledger_bank_statements (bank_account, last_day)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_bank_lines_statement "
    "ON ledger_bank_lines (statement_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_bank_lines_bank_ref "
    "ON ledger_bank_lines (bank_ref, booked_on, amount)",
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
    "DROP TABLE IF EXISTS ledger_bank_lines",
    "DROP TABLE IF EXISTS ledger_bank_statements",
)
