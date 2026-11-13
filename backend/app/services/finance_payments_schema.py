"""Przelewy i zapłaty faktur kosztowych (E3): SQL migracji ``0699_finance_payments``.

Jedno źródło instrukcji dla ``alembic/versions/0699_finance_payments.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Warstwa płatności leży obok kolejki kosztów (``finance_cost_entries``, 0695),
nie w niej — kolejka E1 zostaje bez zmian:

* ``finance_cost_payments`` — stan zapłaty wpisu (1:1, powstaje przy pierwszej
  zmianie): ``unpaid / in_batch / paid / partially_paid``, ręczny rachunek
  odbiorcy, suma zapłat, data i źródło ostatniej zapłaty. Faktury osób zespołu
  nie mają tu wiersza — ich zapłatę prowadzą Płace (rozliczenie miesiąca),
  kolejka czyta stan z ``payroll_settlements``.
* ``finance_counterparty_accounts`` — rachunek kontrahenta z kartoteki
  (zapamiętany przy ręcznym wpisie na fakturze, gdy ktoś zaznaczy
  „zapamiętaj”), z historią zmian w ``finance_counterparty_account_events``.
* ``finance_payment_batches`` i ``finance_payment_batch_items`` — paczka
  przelewów (jedna waluta) i jej pozycje z trybem (zwykły, MPP, konto US),
  rachunkiem, tytułem i wynikiem białej listy z dnia paczki. Wpis może być
  w jednej aktywnej pozycji naraz (indeks częściowy — dwie równoległe paczki
  nie wezmą tej samej faktury).
* ``finance_cost_payment_records`` — zapłaty: obciążenia z wyciągu
  (dopasowane, do sprawdzenia, pominięte) i ręczne „Opłacono”. Ten sam plik
  drugi raz nic nie dopisuje (skrót pliku + numer pozycji, indeks unikalny).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

# Pełna lista akcji (E1 + E2 + E3): przebudowa z samą listą E1 wyrzuciłaby akcje dekretu (E2).
from app.services.finance_posting_schema import CK_EVENT_ACTION

PAYMENT_STATES: tuple[str, ...] = ("unpaid", "in_batch", "paid", "partially_paid")
PAID_SOURCES: tuple[str, ...] = ("statement", "manual", "other_path")
MODES: tuple[str, ...] = ("standard", "mpp", "tax_office")
BATCH_FORMATS: tuple[str, ...] = ("elixir", "csv")
BATCH_STATUSES: tuple[str, ...] = ("active", "cancelled")
ITEM_STATUSES: tuple[str, ...] = ("active", "released", "done")
RECORD_KINDS: tuple[str, ...] = ("statement_line", "manual")
RECORD_STATUSES: tuple[str, ...] = ("matched", "unmatched", "ignored")
ACCOUNT_SOURCES: tuple[str, ...] = ("manual", "ksef_factor", "ksef", "counterparty")

ACCOUNT_MAX = 34
TITLE_MAX = 300
REASON_MAX = 500
NAME_MAX = 255
LINE_REF_MAX = 64

CK_PAYMENT_STATE = f"state IN ({quoted(PAYMENT_STATES)})"
CK_PAID_SOURCE = f"paid_source IS NULL OR paid_source IN ({quoted(PAID_SOURCES)})"
CK_PAID_AMOUNT = "paid_amount >= 0"
CK_BATCH_FORMAT = f"format IN ({quoted(BATCH_FORMATS)})"
CK_BATCH_STATUS = f"status IN ({quoted(BATCH_STATUSES)})"
CK_BATCH_ELIXIR_PLN = "format <> 'elixir' OR currency = 'PLN'"
CK_ITEM_STATUS = f"status IN ({quoted(ITEM_STATUSES)})"
CK_ITEM_MODE = f"mode IN ({quoted(MODES)})"
CK_ITEM_AMOUNT = "amount > 0"
CK_ITEM_ACCOUNT_SOURCE = (
    f"account_source IS NULL OR account_source IN ({quoted(ACCOUNT_SOURCES)})"
)
CK_RECORD_KIND = f"kind IN ({quoted(RECORD_KINDS)})"
CK_RECORD_STATUS = f"match_status IN ({quoted(RECORD_STATUSES)})"
CK_RECORD_MATCHED = "match_status <> 'matched' OR entry_id IS NOT NULL"
CK_RECORD_STATEMENT = (
    "kind <> 'statement_line' OR "
    "(statement_sha256 IS NOT NULL AND statement_line_ref IS NOT NULL)"
)

ACTIVE_ITEM_WHERE = "status = 'active'"
STATEMENT_WHERE = "kind = 'statement_line'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS finance_cost_payments (
    entry_id INTEGER PRIMARY KEY REFERENCES finance_cost_entries(id) ON DELETE CASCADE,
    state VARCHAR(16) NOT NULL DEFAULT 'unpaid',
    account VARCHAR({ACCOUNT_MAX}) NULL,
    paid_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    paid_on DATE NULL,
    paid_source VARCHAR(12) NULL,
    account_changed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    account_changed_at TIMESTAMPTZ NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_finance_cost_payments_state CHECK ({CK_PAYMENT_STATE}),
    CONSTRAINT ck_finance_cost_payments_source CHECK ({CK_PAID_SOURCE}),
    CONSTRAINT ck_finance_cost_payments_amount CHECK ({CK_PAID_AMOUNT})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_counterparty_accounts (
    counterparty_id INTEGER PRIMARY KEY REFERENCES finance_counterparties(id) ON DELETE CASCADE,
    account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_payment_batches (
    id SERIAL PRIMARY KEY,
    currency VARCHAR(3) NOT NULL,
    format VARCHAR(8) NOT NULL,
    execution_date DATE NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'active',
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    changed_at TIMESTAMPTZ NULL,
    downloaded_at TIMESTAMPTZ NULL,
    file_sha256 VARCHAR(64) NULL,
    CONSTRAINT ck_finance_payment_batches_format CHECK ({CK_BATCH_FORMAT}),
    CONSTRAINT ck_finance_payment_batches_status CHECK ({CK_BATCH_STATUS}),
    CONSTRAINT ck_finance_payment_batches_elixir_pln CHECK ({CK_BATCH_ELIXIR_PLN})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_payment_batch_items (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES finance_payment_batches(id) ON DELETE CASCADE,
    entry_id INTEGER NOT NULL REFERENCES finance_cost_entries(id) ON DELETE CASCADE,
    status VARCHAR(10) NOT NULL DEFAULT 'active',
    mode VARCHAR(10) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    vat_amount NUMERIC(14, 2) NULL,
    currency VARCHAR(3) NOT NULL,
    account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    account_source VARCHAR(16) NULL,
    recipient_name VARCHAR({NAME_MAX}) NOT NULL,
    title_lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    white_list JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    acknowledged_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_finance_payment_batch_items_status CHECK ({CK_ITEM_STATUS}),
    CONSTRAINT ck_finance_payment_batch_items_mode CHECK ({CK_ITEM_MODE}),
    CONSTRAINT ck_finance_payment_batch_items_amount CHECK ({CK_ITEM_AMOUNT}),
    CONSTRAINT ck_finance_payment_batch_items_account_source CHECK ({CK_ITEM_ACCOUNT_SOURCE})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_counterparty_account_events (
    id SERIAL PRIMARY KEY,
    counterparty_id INTEGER NOT NULL REFERENCES finance_counterparties(id) ON DELETE CASCADE,
    entry_id INTEGER NULL REFERENCES finance_cost_entries(id) ON DELETE SET NULL,
    old_account VARCHAR({ACCOUNT_MAX}) NULL,
    new_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    actor_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_cost_payment_records (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    entry_id INTEGER NULL REFERENCES finance_cost_entries(id) ON DELETE SET NULL,
    match_status VARCHAR(10) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    booked_on DATE NOT NULL,
    title VARCHAR({TITLE_MAX}) NULL,
    counterparty_name VARCHAR({NAME_MAX}) NULL,
    counterparty_last4 VARCHAR(4) NULL,
    reason VARCHAR({REASON_MAX}) NULL,
    candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    statement_sha256 VARCHAR(64) NULL,
    statement_format VARCHAR(8) NULL,
    statement_line_ref VARCHAR({LINE_REF_MAX}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_finance_cost_payment_records_kind CHECK ({CK_RECORD_KIND}),
    CONSTRAINT ck_finance_cost_payment_records_status CHECK ({CK_RECORD_STATUS}),
    CONSTRAINT ck_finance_cost_payment_records_matched CHECK ({CK_RECORD_MATCHED}),
    CONSTRAINT ck_finance_cost_payment_records_statement CHECK ({CK_RECORD_STATEMENT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_payments_state "
    "ON finance_cost_payments (state)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_payment_batch_items_active "
    f"ON finance_payment_batch_items (entry_id) WHERE {ACTIVE_ITEM_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_finance_payment_batch_items_batch "
    "ON finance_payment_batch_items (batch_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_finance_payment_batch_items_entry "
    "ON finance_payment_batch_items (entry_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_cost_payment_records_statement "
    "ON finance_cost_payment_records (statement_sha256, statement_line_ref) "
    f"WHERE {STATEMENT_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_payment_records_entry "
    "ON finance_cost_payment_records (entry_id)",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_payment_records_status "
    "ON finance_cost_payment_records (match_status, booked_on)",
    "CREATE INDEX IF NOT EXISTS ix_finance_counterparty_account_events_party "
    "ON finance_counterparty_account_events (counterparty_id, id)",
)

#: Zmiana rachunku odbiorcy trafia do historii wpisu (akcja ``account``,
#: ``EVENT_ACTIONS`` w ``finance_ledger_schema``) — CHECK z 0695 jej nie znał.
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_finance_cost_entry_events_action'
          AND pg_get_constraintdef(oid) LIKE '%''account''%'
          AND pg_get_constraintdef(oid) LIKE '%unexport%'
    ) THEN
        ALTER TABLE finance_cost_entry_events
            DROP CONSTRAINT IF EXISTS ck_finance_cost_entry_events_action;
        ALTER TABLE finance_cost_entry_events
            ADD CONSTRAINT ck_finance_cost_entry_events_action CHECK ({CK_EVENT_ACTION});
    END IF;
END $$""",
)

DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DELETE FROM finance_cost_entry_events WHERE action = 'account'",
    "DROP TABLE IF EXISTS finance_counterparty_account_events",
    "DROP TABLE IF EXISTS finance_cost_payment_records",
    "DROP TABLE IF EXISTS finance_payment_batch_items",
    "DROP TABLE IF EXISTS finance_payment_batches",
    "DROP TABLE IF EXISTS finance_counterparty_accounts",
    "DROP TABLE IF EXISTS finance_cost_payments",
)
