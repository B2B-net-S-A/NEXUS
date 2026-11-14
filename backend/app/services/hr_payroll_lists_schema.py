"""Płace liczone w NEXUSIE (K7a) — SQL migracji ``0703_payroll_lists`` i lustra entrypointu.

Jedno źródło DDL dla ``alembic/versions/0703_payroll_lists.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``); każda instrukcja idempotentna.
Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar (etap K7).

* ``payroll_person_data`` — dane kadrowo-płacowe osoby: jeden zaszyfrowany
  JSON (``TokenCipher``: PESEL, dokument, data urodzenia, adres, urząd
  skarbowy, kod tytułu ZUS, PIT-2, koszty, ulgi, PPK, rachunek kontraktora).
  Jawne są tylko skróty HMAC (PESEL bez powtórzeń, rachunek do paczki), cztery
  ostatnie cyfry do maski i lista brakujących pól (nazwy, bez wartości).
  Osoba to konto (``user_id``, zespół) albo kandydat (``candidate_id``,
  zleceniobiorca u klienta bez konta) — dokładnie jedno z nich.
* ``payroll_parameter_versions`` — parametry płac od daty (pełny zestaw).
  Zmiana daty, która już ma wersję, zostawia starą jako zastąpioną (historia),
  wersja użyta przez zatwierdzoną listę jest nietykalna (serwis).
* ``payroll_lists`` — lista płac miesiąca pracy (okres Płac): szkic po
  „Przelicz”, zatwierdzona przez drugą osobę z Płac, anulowana z powodem.
  Jedna żywa lista na okres; data wypłaty wyznacza miesiąc ZUS i PIT.
  ``source_hash`` to skrót danych wejściowych z chwili przeliczenia (linie
  zamkniętego miesiąca, kwoty Płac, rozliczenia klientów, wersje danych osób
  i parametrów) — zatwierdzenie odmawia, gdy od tego czasu coś się zmieniło.
* ``payroll_list_lines`` — pozycje listy: osoba × tytuł (UoP, zlecenie,
  dzieło), źródło kwoty, wynik silnika (``result``) i problemy blokujące.
* ``payroll_gross_inputs`` — kwoty brutto wpisane przez Płace na miesiąc
  (zlecenie u klienta bez przyjętego rozliczenia, UoP z pensją miesięczną,
  dzieło); przeżywają „Przelicz” i anulowanie listy.
* ``payroll_year_openings`` — stan roku sprzed NEXUSA (eksport z Enovy):
  podstawa emerytalna narastająco, podstawa opodatkowania, przychód zwolniony,
  sumy do PIT-11.
"""

from __future__ import annotations

import json

from app.services.consultant_portal_schema import quoted
from app.services.hr.payroll_lists import params as payroll_params

PARAM_STATUSES: tuple[str, ...] = ("to_confirm", "confirmed")
PARAM_SOURCES: tuple[str, ...] = ("seed", "manual")
LIST_STATUSES: tuple[str, ...] = ("draft", "approved", "cancelled")
LINE_KINDS: tuple[str, ...] = ("uop", "zlecenie", "dzielo")
LINE_SOURCES: tuple[str, ...] = (
    "payroll_line",
    "client_settlement",
    "manual",
    "missing",
)
NAME_MAX = 255
NUMBER_MAX = 32
NOTE_MAX = 500
GROSS_MAX = "10000000"

CK_PERSON_SUBJECT = "(user_id IS NULL) <> (candidate_id IS NULL)"
CK_LAST4_PESEL = "pesel_last4 IS NULL OR pesel_last4 ~ '^[0-9]{4}$'"
CK_LAST4_ACCOUNT = "account_last4 IS NULL OR account_last4 ~ '^[0-9]{4}$'"
CK_MISSING = "jsonb_typeof(missing) = 'array'"

CK_PARAM_STATUS = f"status IN ({quoted(PARAM_STATUSES)})"
CK_PARAM_SOURCE = f"source IN ({quoted(PARAM_SOURCES)})"
CK_PARAM_OBJECT = "jsonb_typeof(params) = 'object'"
CK_PARAM_FIRST_DAY = "EXTRACT(DAY FROM effective_from) = 1"
CK_PARAM_CONFIRMED = "status <> 'confirmed' OR confirmed_at IS NOT NULL"
CK_PARAM_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"
PARAM_LIVE_WHERE = "replaced_at IS NULL"

CK_LIST_STATUS = f"status IN ({quoted(LIST_STATUSES)})"
CK_LIST_YEAR = "year BETWEEN 2020 AND 2100"
CK_LIST_MONTH = "month BETWEEN 1 AND 12"
CK_LIST_TOTALS = "jsonb_typeof(totals) = 'object'"
CK_LIST_PROBLEMS = "jsonb_typeof(problems) = 'array'"
CK_LIST_APPROVED = "status <> 'approved' OR approved_at IS NOT NULL"
CK_LIST_CANCELLED = "status <> 'cancelled' OR cancelled_at IS NOT NULL"
#: Druga osoba: liczący listę jej nie zatwierdza (także po ponownym „Przelicz”).
CK_LIST_SECOND_PERSON = (
    "approved_by IS NULL OR computed_by IS NULL OR approved_by <> computed_by"
)
CK_LIST_REASON = f"cancel_reason IS NULL OR char_length(cancel_reason) <= {NOTE_MAX}"
LIST_LIVE_WHERE = "status <> 'cancelled'"

CK_LINE_SUBJECT = CK_PERSON_SUBJECT
CK_LINE_KIND = f"kind IN ({quoted(LINE_KINDS)})"
CK_LINE_SOURCE = f"source IN ({quoted(LINE_SOURCES)})"
CK_LINE_GROSS = f"gross IS NULL OR (gross >= 0 AND gross <= {GROSS_MAX})"
CK_LINE_BASIS = "jsonb_typeof(basis) = 'object'"
CK_LINE_RESULT = "jsonb_typeof(result) = 'object'"
CK_LINE_PROBLEMS = "jsonb_typeof(problems) = 'array'"
CK_LINE_PAYEE = "payee_last4 IS NULL OR payee_last4 ~ '^[0-9]{4}$'"

CK_INPUT_SUBJECT = "(user_id IS NULL) <> (contract_id IS NULL)"
CK_INPUT_KIND = f"kind IN ({quoted(LINE_KINDS)})"
CK_INPUT_GROSS = f"gross >= 0 AND gross <= {GROSS_MAX}"
CK_INPUT_NOTE = f"char_length(note) BETWEEN 3 AND {NOTE_MAX}"

CK_OPENING_SUBJECT = CK_PERSON_SUBJECT
CK_OPENING_YEAR = "year BETWEEN 2020 AND 2100"
CK_OPENING_MONTH = "through_month BETWEEN 1 AND 12"
CK_OPENING_AMOUNTS = "jsonb_typeof(amounts) = 'object'"
CK_OPENING_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS payroll_person_data (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    data_encrypted TEXT NOT NULL,
    pesel_hmac VARCHAR(64) NULL,
    pesel_last4 VARCHAR(4) NULL,
    account_hmac VARCHAR(64) NULL,
    account_last4 VARCHAR(4) NULL,
    missing JSONB NOT NULL DEFAULT '[]'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_person_data_subject CHECK ({CK_PERSON_SUBJECT}),
    CONSTRAINT ck_payroll_person_data_pesel_last4 CHECK ({CK_LAST4_PESEL}),
    CONSTRAINT ck_payroll_person_data_account_last4 CHECK ({CK_LAST4_ACCOUNT}),
    CONSTRAINT ck_payroll_person_data_missing CHECK ({CK_MISSING})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_parameter_versions (
    id SERIAL PRIMARY KEY,
    effective_from DATE NOT NULL,
    params JSONB NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'to_confirm',
    source VARCHAR(8) NOT NULL DEFAULT 'manual',
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ NULL,
    replaced_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    replaced_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_payroll_parameter_versions_status CHECK ({CK_PARAM_STATUS}),
    CONSTRAINT ck_payroll_parameter_versions_source CHECK ({CK_PARAM_SOURCE}),
    CONSTRAINT ck_payroll_parameter_versions_params CHECK ({CK_PARAM_OBJECT}),
    CONSTRAINT ck_payroll_parameter_versions_first_day CHECK ({CK_PARAM_FIRST_DAY}),
    CONSTRAINT ck_payroll_parameter_versions_confirmed CHECK ({CK_PARAM_CONFIRMED}),
    CONSTRAINT ck_payroll_parameter_versions_note CHECK ({CK_PARAM_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_lists (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE RESTRICT,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    number VARCHAR({NUMBER_MAX}) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'draft',
    pay_date DATE NOT NULL,
    parameter_version_id INTEGER NOT NULL
        REFERENCES payroll_parameter_versions(id) ON DELETE RESTRICT,
    totals JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    problems JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_hash VARCHAR(64) NOT NULL DEFAULT '',
    computed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancel_reason TEXT NULL,
    transfers_created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    transfers_created_at TIMESTAMPTZ NULL,
    paid_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    paid_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_payroll_lists_number UNIQUE (number),
    CONSTRAINT ck_payroll_lists_status CHECK ({CK_LIST_STATUS}),
    CONSTRAINT ck_payroll_lists_year CHECK ({CK_LIST_YEAR}),
    CONSTRAINT ck_payroll_lists_month CHECK ({CK_LIST_MONTH}),
    CONSTRAINT ck_payroll_lists_totals CHECK ({CK_LIST_TOTALS}),
    CONSTRAINT ck_payroll_lists_problems CHECK ({CK_LIST_PROBLEMS}),
    CONSTRAINT ck_payroll_lists_approved CHECK ({CK_LIST_APPROVED}),
    CONSTRAINT ck_payroll_lists_cancelled CHECK ({CK_LIST_CANCELLED}),
    CONSTRAINT ck_payroll_lists_second_person CHECK ({CK_LIST_SECOND_PERSON}),
    CONSTRAINT ck_payroll_lists_reason CHECK ({CK_LIST_REASON})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_list_lines (
    id BIGSERIAL PRIMARY KEY,
    list_id INTEGER NOT NULL REFERENCES payroll_lists(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    person_name VARCHAR({NAME_MAX}) NOT NULL,
    kind VARCHAR(10) NOT NULL,
    source VARCHAR(20) NOT NULL,
    gross NUMERIC(14,2) NULL,
    net NUMERIC(14,2) NULL,
    pit NUMERIC(14,2) NULL,
    social_employee NUMERIC(14,2) NULL,
    health NUMERIC(14,2) NULL,
    employer_social NUMERIC(14,2) NULL,
    employer_cost NUMERIC(14,2) NULL,
    basis JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    problems JSONB NOT NULL DEFAULT '[]'::jsonb,
    payee_last4 VARCHAR(4) NULL,
    payee_hmac VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_list_lines_subject CHECK ({CK_LINE_SUBJECT}),
    CONSTRAINT ck_payroll_list_lines_kind CHECK ({CK_LINE_KIND}),
    CONSTRAINT ck_payroll_list_lines_source CHECK ({CK_LINE_SOURCE}),
    CONSTRAINT ck_payroll_list_lines_gross CHECK ({CK_LINE_GROSS}),
    CONSTRAINT ck_payroll_list_lines_basis CHECK ({CK_LINE_BASIS}),
    CONSTRAINT ck_payroll_list_lines_result CHECK ({CK_LINE_RESULT}),
    CONSTRAINT ck_payroll_list_lines_problems CHECK ({CK_LINE_PROBLEMS}),
    CONSTRAINT ck_payroll_list_lines_payee CHECK ({CK_LINE_PAYEE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_gross_inputs (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    kind VARCHAR(10) NOT NULL,
    gross NUMERIC(14,2) NOT NULL,
    note VARCHAR({NOTE_MAX}) NOT NULL,
    entered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_gross_inputs_subject CHECK ({CK_INPUT_SUBJECT}),
    CONSTRAINT ck_payroll_gross_inputs_kind CHECK ({CK_INPUT_KIND}),
    CONSTRAINT ck_payroll_gross_inputs_gross CHECK ({CK_INPUT_GROSS}),
    CONSTRAINT ck_payroll_gross_inputs_note CHECK ({CK_INPUT_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_year_openings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    year SMALLINT NOT NULL,
    through_month SMALLINT NOT NULL,
    amounts JSONB NOT NULL,
    note VARCHAR({NOTE_MAX}) NULL,
    entered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_year_openings_subject CHECK ({CK_OPENING_SUBJECT}),
    CONSTRAINT ck_payroll_year_openings_year CHECK ({CK_OPENING_YEAR}),
    CONSTRAINT ck_payroll_year_openings_month CHECK ({CK_OPENING_MONTH}),
    CONSTRAINT ck_payroll_year_openings_amounts CHECK ({CK_OPENING_AMOUNTS}),
    CONSTRAINT ck_payroll_year_openings_note CHECK ({CK_OPENING_NOTE})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_person_data_user "
    "ON payroll_person_data (user_id) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_person_data_candidate "
    "ON payroll_person_data (candidate_id) WHERE candidate_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_person_data_pesel "
    "ON payroll_person_data (pesel_hmac) WHERE pesel_hmac IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_parameter_versions_live "
    f"ON payroll_parameter_versions (effective_from) WHERE {PARAM_LIVE_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_lists_live "
    f"ON payroll_lists (period_id) WHERE {LIST_LIVE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_payroll_lists_pay_date "
    "ON payroll_lists (pay_date) WHERE status = 'approved'",
    "CREATE INDEX IF NOT EXISTS ix_payroll_list_lines_list "
    "ON payroll_list_lines (list_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_list_lines_user "
    "ON payroll_list_lines (list_id, user_id, kind) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_list_lines_contract "
    "ON payroll_list_lines (list_id, contract_id) WHERE contract_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_payroll_list_lines_user "
    "ON payroll_list_lines (user_id) WHERE user_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_payroll_list_lines_candidate "
    "ON payroll_list_lines (candidate_id) WHERE candidate_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_gross_inputs_user "
    "ON payroll_gross_inputs (period_id, user_id, kind) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_gross_inputs_contract "
    "ON payroll_gross_inputs (period_id, contract_id) WHERE contract_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_year_openings_user "
    "ON payroll_year_openings (user_id, year) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_year_openings_candidate "
    "ON payroll_year_openings (candidate_id, year) WHERE candidate_id IS NOT NULL",
)

CONSTRAINT_DDL: tuple[str, ...] = ()


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_SEED_JSON = json.dumps(payroll_params.SEED_2026, sort_keys=True)

#: Zasiew parametrów 2026 „do potwierdzenia przez Płace” — raz (znacznik: wiersz
#: ``source='seed'`` z tą datą, także zastąpiony), więc zmiana Płac go nie wraca.
DATA_DDL: tuple[str, ...] = (
    "INSERT INTO payroll_parameter_versions "
    "(effective_from, params, status, source, note) "
    f"SELECT DATE {_sql_text(payroll_params.SEED_EFFECTIVE_FROM)}, "
    f"{_sql_text(_SEED_JSON)}::jsonb, 'to_confirm', 'seed', "
    f"{_sql_text(payroll_params.SEED_NOTE)} "
    "WHERE NOT EXISTS (SELECT 1 FROM payroll_parameter_versions "
    "WHERE source = 'seed' AND effective_from = "
    f"DATE {_sql_text(payroll_params.SEED_EFFECTIVE_FROM)})",
)

TABLES: tuple[str, ...] = (
    "payroll_person_data",
    "payroll_parameter_versions",
    "payroll_lists",
    "payroll_list_lines",
    "payroll_gross_inputs",
    "payroll_year_openings",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)
)
