"""Księgowość w Finansach (E2): SQL migracji ``0696_finance_posting`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0696_finance_posting.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

* ``finance_accounts`` — plan kont Symfonii FK (numer, nazwa, rodzaj, aktywne).
  Numeru się nie zmienia ani nie kasuje (wyłącza się), bo zasiew przy starcie
  dokłada brakujące konta wzorcowe po numerze.
* ``finance_posting_rules`` — reguły dekretu: kategoria wpisu kosztowego
  i opcjonalnie kontrahent → konto kosztu, konto VAT, odliczenie, rejestr, typ
  dokumentu i wzór opisu. Jedna reguła ogólna na kategorię i jedna na parę
  kategoria + kontrahent. Reguł się nie kasuje (wyłącza się) — z tego samego
  powodu co kont.
* ``finance_posting_batches`` — paczki eksportu do Symfonii: numer, miesiąc,
  kto i kiedy, lista wpisów, plik (bajty i SHA-256 — ponowne pobranie daje ten
  sam plik), stan ``exported`` → ``booked`` albo ``cancelled``.
* ``finance_cost_entries.decree`` — dekret wpisu (JSONB: rejestr, typ, opis,
  pozycje Wn/Ma w groszach) i ``batch_id`` — paczka, w której wpis czeka na
  zaksięgowanie.

Zasiew planu kont bierze tylko konta wzorcowe zmierzone w eBI24 13.11.2026
(bez kont analitycznych kontrahentów — te są w kartotece).
"""

from __future__ import annotations

from app.services import finance_ledger_schema as ledger
from app.services.consultant_portal_schema import quoted

ACCOUNT_KINDS: tuple[str, ...] = ("cost", "vat", "settlement", "revenue")
DEDUCTIONS: tuple[str, ...] = ("full", "none")
REGISTERS: tuple[str, ...] = ("purchase", "sale")
BATCH_STATUSES: tuple[str, ...] = ("exported", "booked", "cancelled")
#: Historia wpisu: E1 i dekret, paczka, zaksięgowanie (E2).
EVENT_ACTIONS: tuple[str, ...] = (
    *ledger.EVENT_ACTIONS,
    "decree",
    "export",
    "unexport",
    "book",
)

ACCOUNT_MAX = ledger.ACCOUNT_MAX
ACCOUNT_NAME_MAX = 255
DOC_TYPE_MAX = 8
SERVICE_MAX = 120
TEMPLATE_MAX = 200
BATCH_NUMBER_MAX = 20
FILE_NAME_MAX = 120

CK_ACCOUNT_KIND = f"kind IN ({quoted(ACCOUNT_KINDS)})"
CK_RULE_CATEGORY = f"category IN ({quoted(ledger.CATEGORIES)})"
CK_RULE_DEDUCTION = f"deduction IN ({quoted(DEDUCTIONS)})"
CK_RULE_REGISTER = f"register IN ({quoted(REGISTERS)})"
CK_RULE_VAT = "deduction = 'none' OR vat_account IS NOT NULL"
CK_BATCH_STATUS = f"status IN ({quoted(BATCH_STATUSES)})"
CK_EVENT_ACTION = f"action IN ({quoted(EVENT_ACTIONS)})"

RULE_GENERAL_WHERE = "counterparty_id IS NULL"
RULE_COUNTERPARTY_WHERE = "counterparty_id IS NOT NULL"
ENTRY_BATCH_WHERE = "batch_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS finance_accounts (
    id SERIAL PRIMARY KEY,
    number VARCHAR({ACCOUNT_MAX}) NOT NULL,
    name VARCHAR({ACCOUNT_NAME_MAX}) NOT NULL,
    kind VARCHAR(12) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_finance_accounts_number UNIQUE (number),
    CONSTRAINT ck_finance_accounts_kind CHECK ({CK_ACCOUNT_KIND})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_posting_rules (
    id SERIAL PRIMARY KEY,
    category VARCHAR(12) NOT NULL,
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE CASCADE,
    cost_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    vat_account VARCHAR({ACCOUNT_MAX}) NULL,
    deduction VARCHAR(8) NOT NULL,
    register VARCHAR(10) NOT NULL,
    doc_type VARCHAR({DOC_TYPE_MAX}) NOT NULL,
    service_label VARCHAR({SERVICE_MAX}) NOT NULL,
    description_template VARCHAR({TEMPLATE_MAX}) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_finance_posting_rules_category CHECK ({CK_RULE_CATEGORY}),
    CONSTRAINT ck_finance_posting_rules_deduction CHECK ({CK_RULE_DEDUCTION}),
    CONSTRAINT ck_finance_posting_rules_register CHECK ({CK_RULE_REGISTER}),
    CONSTRAINT ck_finance_posting_rules_vat CHECK ({CK_RULE_VAT})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_posting_batches (
    id SERIAL PRIMARY KEY,
    number VARCHAR({BATCH_NUMBER_MAX}) NOT NULL,
    month DATE NOT NULL,
    status VARCHAR(10) NOT NULL,
    file_format VARCHAR(20) NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NOT NULL,
    file_content BYTEA NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    entry_ids INTEGER[] NOT NULL,
    entry_count INTEGER NOT NULL,
    debit_total BIGINT NOT NULL,
    credit_total BIGINT NOT NULL,
    has_payroll BOOLEAN NOT NULL DEFAULT FALSE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    booked_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    booked_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_finance_posting_batches_number UNIQUE (number),
    CONSTRAINT ck_finance_posting_batches_status CHECK ({CK_BATCH_STATUS})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE finance_cost_entries ADD COLUMN IF NOT EXISTS decree JSONB NULL",
    "ALTER TABLE finance_cost_entries ADD COLUMN IF NOT EXISTS batch_id INTEGER NULL "
    "REFERENCES finance_posting_batches(id) ON DELETE SET NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_posting_rules_general "
    f"ON finance_posting_rules (category) WHERE {RULE_GENERAL_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_posting_rules_counterparty "
    "ON finance_posting_rules (category, counterparty_id) "
    f"WHERE {RULE_COUNTERPARTY_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_finance_posting_batches_month "
    "ON finance_posting_batches (month, id)",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_entries_batch "
    f"ON finance_cost_entries (batch_id) WHERE {ENTRY_BATCH_WHERE}",
)

#: Nowe akcje historii. Warunek w DO, żeby entrypoint nie przebudowywał
#: CHECK-a przy każdym starcie (pełny skan tabeli pod blokadą).
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_finance_cost_entry_events_action'
          AND pg_get_constraintdef(oid) LIKE '%unexport%'
    ) THEN
        ALTER TABLE finance_cost_entry_events
            DROP CONSTRAINT IF EXISTS ck_finance_cost_entry_events_action;
        ALTER TABLE finance_cost_entry_events
            ADD CONSTRAINT ck_finance_cost_entry_events_action CHECK ({CK_EVENT_ACTION});
    END IF;
END $$""",
)

#: Konta wzorcowe z pomiaru dekretów eBI24 (13.11.2026, 1 442 dokumenty).
#: Nazwy robocze — Finanse poprawiają je na ekranie „Plan kont”.
SEED_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("402-203", "Usługi obce — kontraktorzy", "cost"),
    ("402-202", "Usługi obce", "cost"),
    ("402-215", "Usługi obce", "cost"),
    ("409-906", "Pozostałe koszty", "cost"),
    ("409-998", "Pozostałe koszty", "cost"),
    ("221", "VAT naliczony", "vat"),
    ("222", "VAT należny", "vat"),
    ("202-2-10", "Rozrachunki z odbiorcami UE", "settlement"),
    ("760-5", "Przychody", "revenue"),
    ("701-4-1", "Sprzedaż usług — kraj", "revenue"),
    ("702-65-1", "Sprzedaż — kraj", "revenue"),
    ("701-10-1", "Sprzedaż usług — UE", "revenue"),
)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_SEED_ACCOUNT_ROWS = ", ".join(
    f"({_literal(number)}, {_literal(name)}, {_literal(kind)})"
    for number, name, kind in SEED_ACCOUNTS
)

DATA_DDL: tuple[str, ...] = (
    "INSERT INTO finance_accounts (number, name, kind) "
    f"VALUES {_SEED_ACCOUNT_ROWS} "
    "ON CONFLICT ON CONSTRAINT uq_finance_accounts_number DO NOTHING",
    # Reguła domyślna: faktura kontraktora → 402-203, VAT 221, Zakup, FVZ.
    # Tylko gdy kategoria nie ma żadnej reguły ogólnej (także wyłączonej).
    "INSERT INTO finance_posting_rules "
    "(category, cost_account, vat_account, deduction, register, doc_type, "
    "service_label, description_template) "
    "SELECT 'contractor', '402-203', '221', 'full', 'purchase', 'FVZ', "
    "'Usługi IT', '{usługa} {MM}/{RRRR}' "
    "WHERE NOT EXISTS (SELECT 1 FROM finance_posting_rules "
    "WHERE category = 'contractor' AND counterparty_id IS NULL)",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DELETE FROM finance_cost_entry_events "
    "WHERE action IN ('decree', 'export', 'unexport', 'book')",
    "ALTER TABLE finance_cost_entry_events "
    "DROP CONSTRAINT IF EXISTS ck_finance_cost_entry_events_action",
    "ALTER TABLE finance_cost_entry_events "
    f"ADD CONSTRAINT ck_finance_cost_entry_events_action CHECK ({ledger.CK_EVENT_ACTION})",
    "DROP INDEX IF EXISTS ix_finance_cost_entries_batch",
    "ALTER TABLE finance_cost_entries DROP COLUMN IF EXISTS batch_id",
    "ALTER TABLE finance_cost_entries DROP COLUMN IF EXISTS decree",
    "DROP TABLE IF EXISTS finance_posting_batches",
    "DROP TABLE IF EXISTS finance_posting_rules",
    "DROP TABLE IF EXISTS finance_accounts",
)
