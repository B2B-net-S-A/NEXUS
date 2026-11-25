"""Kontrola miesiąca (0784): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0784_month_check_cases.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

``month_check_cases`` — sprawa = rodzaj rozbieżności × osoba × miesiąc
(``over_working_days`` także × klient), klucz ``case_key``. ``state``:
``new`` (znalazł automat), ``to_correct`` (Finanse: do korekty faktury),
``explained`` (Finanse wpisały powód), ``closed`` (rozbieżność zniknęła
w kolejnym przebiegu). Kwota i numery faktur są w wierszu, bo mail do
Finansów i ekran mają pokazać to samo, co znalazł przebieg.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = (
    "hours_mismatch",
    "cost_without_sale",
    "sale_without_cost",
    "over_working_days",
)
STATES: tuple[str, ...] = ("new", "to_correct", "explained", "closed")
DATA_ISSUES: tuple[str, ...] = ("no_contract", "no_order")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS month_check_cases (
    id SERIAL PRIMARY KEY,
    case_key VARCHAR(96) NOT NULL,
    kind VARCHAR(24) NOT NULL,
    period_month VARCHAR(7) NOT NULL,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    data_issue VARCHAR(16) NULL,
    details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    state VARCHAR(12) NOT NULL DEFAULT 'new',
    reason TEXT NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_month_check_cases_key UNIQUE (case_key),
    CONSTRAINT ck_month_check_cases_kind CHECK (kind IN ({_quoted(KINDS)})),
    CONSTRAINT ck_month_check_cases_state CHECK (state IN ({_quoted(STATES)})),
    CONSTRAINT ck_month_check_cases_issue CHECK (data_issue IS NULL OR data_issue IN ({_quoted(DATA_ISSUES)})),
    CONSTRAINT ck_month_check_cases_period CHECK (period_month ~ '^[0-9]{{4}}-(0[1-9]|1[0-2])$'),
    CONSTRAINT ck_month_check_cases_explained CHECK (state <> 'explained' OR reason IS NOT NULL)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_month_check_cases_month "
    "ON month_check_cases (period_month, state)",
    "CREATE INDEX IF NOT EXISTS ix_month_check_cases_new "
    "ON month_check_cases (first_seen_at) WHERE state = 'new'",
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

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS month_check_cases",)
