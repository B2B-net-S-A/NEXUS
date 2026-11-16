"""Automaty księgi (K3a): PK cykliczne i RMK — SQL migracji ``0701_ledger_automations``.

Jedno źródło DDL dla ``alembic/versions/0701_ledger_automations.py``
i lustra ``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda
instrukcja idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

* ``ledger_recurring`` — wzór polecenia księgowania powtarzanego co miesiąc
  (np. najem, abonamenty, przeksięgowania stałe): nazwa, pozycje dekretu
  (JSON: strona, konto, kwota w groszach, MPK, kontrahent, opis), miesiąc
  pierwszy i ostatni (pierwsze dni miesięcy), aktywny.
* ``ledger_prepayments`` — rozliczenia międzyokresowe kosztów (RMK czynne, np.
  polisy opłacone z góry): kwota całkowita w groszach, konto kosztu i konto RMK
  (640), MPK, kontrahent, pierwszy miesiąc i liczba miesięcy. Co miesiąc rata
  = kwota / liczba miesięcy, ostatnia rata = reszta (suma rat = kwota).

Dokumenty z obu powstają w „Źródłach” księgi (to samo księgowanie miesiąca,
odcisk danych i problem do storna co faktury), moduł ``automations``.
"""

from __future__ import annotations

from app.services.ledger_schema import ACCOUNT_MAX, DESCRIPTION_MAX, MPK_MAX

NAME_MAX = 200
REFERENCE_MAX = 120
MONTHS_MAX = 120
RECURRING_LINES_MAX = 50

CK_RECURRING_MONTHS = "end_month IS NULL OR end_month >= start_month"
CK_RECURRING_FIRST = (
    "EXTRACT(DAY FROM start_month) = 1 "
    "AND (end_month IS NULL OR EXTRACT(DAY FROM end_month) = 1)"
)
CK_RECURRING_LINES = "jsonb_typeof(lines) = 'array'"
CK_PREPAYMENT_AMOUNT = "total_amount > 0"
CK_PREPAYMENT_MONTHS = f"months BETWEEN 1 AND {MONTHS_MAX}"
CK_PREPAYMENT_FIRST = "EXTRACT(DAY FROM start_month) = 1"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_recurring (
    id SERIAL PRIMARY KEY,
    name VARCHAR({NAME_MAX}) NOT NULL,
    description VARCHAR({DESCRIPTION_MAX}) NOT NULL DEFAULT '',
    lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    start_month DATE NOT NULL,
    end_month DATE NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ledger_recurring_months CHECK ({CK_RECURRING_MONTHS}),
    CONSTRAINT ck_ledger_recurring_first CHECK ({CK_RECURRING_FIRST}),
    CONSTRAINT ck_ledger_recurring_lines CHECK ({CK_RECURRING_LINES})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_prepayments (
    id SERIAL PRIMARY KEY,
    name VARCHAR({NAME_MAX}) NOT NULL,
    reference VARCHAR({REFERENCE_MAX}) NOT NULL DEFAULT '',
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE SET NULL,
    cost_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    prepaid_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    mpk VARCHAR({MPK_MAX}) NULL,
    total_amount BIGINT NOT NULL,
    start_month DATE NOT NULL,
    months SMALLINT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ledger_prepayments_amount CHECK ({CK_PREPAYMENT_AMOUNT}),
    CONSTRAINT ck_ledger_prepayments_months CHECK ({CK_PREPAYMENT_MONTHS}),
    CONSTRAINT ck_ledger_prepayments_first CHECK ({CK_PREPAYMENT_FIRST})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_ledger_recurring_active "
    "ON ledger_recurring (active, start_month)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_prepayments_active "
    "ON ledger_prepayments (active, start_month)",
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
    "DROP TABLE IF EXISTS ledger_prepayments",
    "DROP TABLE IF EXISTS ledger_recurring",
)
