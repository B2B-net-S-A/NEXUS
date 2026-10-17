"""„Ludzie w NEXUSIE” — Płace i premie: SQL migracji ``0460_hr_payroll`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0460_hr_payroll.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: historia stawek, premie, okresy płacowe i zamrożone linie.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele:

* ``employee_rates`` — stawka godzinowa pracownika od 1. dnia miesiąca
  (``effective_to`` = ostatni dzień przed kolejną stawką). Jedna otwarta
  stawka na osobę (indeks częściowy). Poprzednią domyka serwis w tej samej
  transakcji — Compass robił to wyzwalaczem, którego nie widać w kodzie.
* ``hr_bonuses`` — premie: ręczne (Płace albo przełożony), propozycje
  automatów (placement z kontraktu NEXUSA, Liga) i import z Compassa.
  ``source_key`` czyni automaty idempotentnymi; ``rule_snapshot`` zapisuje,
  jakie reguły i liczby dały kwotę. Nikt nie proponuje ani nie zatwierdza
  premii samemu sobie (CHECK-i). Anulowanie jest miękkie (Compass kasował
  premię z placementu na twardo).
* ``payroll_periods`` — miesiąc płac: otwarty (raport liczony z danych) albo
  zamknięty (linie zamrożone). Ponowne otwarcie zostawia ślad.
* ``payroll_lines`` — zamrożone linie zamkniętego miesiąca: osoba × waluta
  (godziny zatwierdzone, stawka, kwota za godziny, premie, razem).
"""

from __future__ import annotations

CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
BONUS_CATEGORIES: tuple[str, ...] = (
    "sales",
    "delivery_lead",
    "recruiter",
    "custom",
    "league",
)
BONUS_STATUSES: tuple[str, ...] = ("proposed", "assigned", "cancelled")
BONUS_SOURCES: tuple[str, ...] = (
    "manual",
    "contract_placement",
    "league",
    "compass_import",
)
#: Źródła, które muszą nieść ``source_key`` (automaty są idempotentne po kluczu).
AUTOMATED_SOURCES: tuple[str, ...] = ("contract_placement", "league")
PERIOD_STATUSES: tuple[str, ...] = ("open", "closed")
TIMESHEET_STATUSES: tuple[str, ...] = ("draft", "submitted", "approved")

#: Górna granica stawki — NUMERIC(12,2) (jak ``user_rates`` w Compassie).
RATE_MAX = "9999999.99"
#: Granice kwoty premii z Compassa (``BONUS_MIN_AMOUNT`` / ``BONUS_MAX_AMOUNT``).
BONUS_MAX = "1000000"
REASON_MAX_LENGTH = 500
DESCRIPTION_MAX_LENGTH = 1000


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_RATE_VALUE = f"hourly_rate >= 0 AND hourly_rate <= {RATE_MAX}"
CK_RATE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_RATE_FIRST_DAY = "EXTRACT(DAY FROM effective_from) = 1"
CK_RATE_RANGE = "effective_to IS NULL OR effective_to >= effective_from"
CK_RATE_REASON = f"reason IS NULL OR char_length(reason) <= {REASON_MAX_LENGTH}"
#: Indeks częściowy: jedna otwarta stawka na osobę.
OPEN_RATE_WHERE = "effective_to IS NULL"

CK_BONUS_NOT_SELF_PROPOSED = "proposed_by IS NULL OR proposed_by <> recipient_user_id"
CK_BONUS_NOT_SELF_ASSIGNED = "assigned_by IS NULL OR assigned_by <> recipient_user_id"
CK_BONUS_AMOUNT = f"amount > 0 AND amount <= {BONUS_MAX}"
CK_BONUS_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_BONUS_CATEGORY = f"category IN ({quoted(BONUS_CATEGORIES)})"
CK_BONUS_STATUS = f"status IN ({quoted(BONUS_STATUSES)})"
CK_BONUS_SOURCE = f"source IN ({quoted(BONUS_SOURCES)})"
CK_BONUS_YEAR = "period_year BETWEEN 2020 AND 2100"
CK_BONUS_MONTH = "period_month BETWEEN 1 AND 12"
CK_BONUS_AUTOMATED_KEY = (
    f"source NOT IN ({quoted(AUTOMATED_SOURCES)}) OR source_key IS NOT NULL"
)
CK_BONUS_ASSIGNED_AT = "status <> 'assigned' OR assigned_at IS NOT NULL"
CK_BONUS_DESCRIPTION = (
    f"description IS NULL OR char_length(description) <= {DESCRIPTION_MAX_LENGTH}"
)

CK_PERIOD_YEAR = "year BETWEEN 2020 AND 2100"
CK_PERIOD_MONTH = "month BETWEEN 1 AND 12"
CK_PERIOD_STATUS = f"status IN ({quoted(PERIOD_STATUSES)})"
CK_PERIOD_CLOSED_AT = "status <> 'closed' OR closed_at IS NOT NULL"

CK_LINE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_LINE_NON_NEGATIVE = "hours >= 0 AND overtime_hours >= 0 AND bonus_total >= 0"
CK_LINE_TIMESHEET_STATUS = (
    f"timesheet_status IS NULL OR timesheet_status IN ({quoted(TIMESHEET_STATUSES)})"
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS employee_rates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    hourly_rate NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    reason TEXT NULL,
    set_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    compass_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_employee_rates_user_from UNIQUE (user_id, effective_from),
    CONSTRAINT uq_employee_rates_compass UNIQUE (compass_id),
    CONSTRAINT ck_employee_rates_value CHECK ({CK_RATE_VALUE}),
    CONSTRAINT ck_employee_rates_currency CHECK ({CK_RATE_CURRENCY}),
    CONSTRAINT ck_employee_rates_first_day CHECK ({CK_RATE_FIRST_DAY}),
    CONSTRAINT ck_employee_rates_range CHECK ({CK_RATE_RANGE}),
    CONSTRAINT ck_employee_rates_reason CHECK ({CK_RATE_REASON})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_bonuses (
    id SERIAL PRIMARY KEY,
    recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    proposed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    amount NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    category VARCHAR(16) NOT NULL,
    period_year SMALLINT NOT NULL,
    period_month SMALLINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'proposed',
    source VARCHAR(24) NOT NULL DEFAULT 'manual',
    source_key VARCHAR(160) NULL,
    rule_snapshot JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    eligible_on DATE NULL,
    description TEXT NULL,
    assigned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancel_reason VARCHAR(40) NULL,
    cancel_note TEXT NULL,
    compass_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_bonuses_source_key UNIQUE (source_key),
    CONSTRAINT uq_hr_bonuses_compass UNIQUE (compass_id),
    CONSTRAINT ck_hr_bonuses_not_self_proposed CHECK ({CK_BONUS_NOT_SELF_PROPOSED}),
    CONSTRAINT ck_hr_bonuses_not_self_assigned CHECK ({CK_BONUS_NOT_SELF_ASSIGNED}),
    CONSTRAINT ck_hr_bonuses_amount CHECK ({CK_BONUS_AMOUNT}),
    CONSTRAINT ck_hr_bonuses_currency CHECK ({CK_BONUS_CURRENCY}),
    CONSTRAINT ck_hr_bonuses_category CHECK ({CK_BONUS_CATEGORY}),
    CONSTRAINT ck_hr_bonuses_status CHECK ({CK_BONUS_STATUS}),
    CONSTRAINT ck_hr_bonuses_source CHECK ({CK_BONUS_SOURCE}),
    CONSTRAINT ck_hr_bonuses_year CHECK ({CK_BONUS_YEAR}),
    CONSTRAINT ck_hr_bonuses_month CHECK ({CK_BONUS_MONTH}),
    CONSTRAINT ck_hr_bonuses_automated_key CHECK ({CK_BONUS_AUTOMATED_KEY}),
    CONSTRAINT ck_hr_bonuses_assigned_at CHECK ({CK_BONUS_ASSIGNED_AT}),
    CONSTRAINT ck_hr_bonuses_description CHECK ({CK_BONUS_DESCRIPTION})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_periods (
    id SERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMPTZ NULL,
    reopened_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    reopened_at TIMESTAMPTZ NULL,
    reopen_reason TEXT NULL,
    close_count SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_payroll_periods_year_month UNIQUE (year, month),
    CONSTRAINT ck_payroll_periods_year CHECK ({CK_PERIOD_YEAR}),
    CONSTRAINT ck_payroll_periods_month CHECK ({CK_PERIOD_MONTH}),
    CONSTRAINT ck_payroll_periods_status CHECK ({CK_PERIOD_STATUS}),
    CONSTRAINT ck_payroll_periods_closed_at CHECK ({CK_PERIOD_CLOSED_AT})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_lines (
    id BIGSERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    person_name VARCHAR(255) NOT NULL,
    employment_type VARCHAR(16) NULL,
    currency VARCHAR(3) NOT NULL,
    hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    overtime_hours NUMERIC(7,2) NOT NULL DEFAULT 0,
    hourly_rate NUMERIC(12,2) NULL,
    hours_amount NUMERIC(14,2) NULL,
    bonus_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    total NUMERIC(14,2) NOT NULL DEFAULT 0,
    paid_leave_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    other_leave_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    timesheet_status VARCHAR(16) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_payroll_lines_period_user_currency UNIQUE (period_id, user_id, currency),
    CONSTRAINT ck_payroll_lines_currency CHECK ({CK_LINE_CURRENCY}),
    CONSTRAINT ck_payroll_lines_non_negative CHECK ({CK_LINE_NON_NEGATIVE}),
    CONSTRAINT ck_payroll_lines_timesheet_status CHECK ({CK_LINE_TIMESHEET_STATUS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_rates_open "
    f"ON employee_rates (user_id) WHERE {OPEN_RATE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_hr_bonuses_period "
    "ON hr_bonuses (period_year, period_month, status)",
    "CREATE INDEX IF NOT EXISTS ix_hr_bonuses_recipient "
    "ON hr_bonuses (recipient_user_id, period_year, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_hr_bonuses_contract ON hr_bonuses (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_lines_user ON payroll_lines (user_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = (
    "employee_rates",
    "hr_bonuses",
    "payroll_periods",
    "payroll_lines",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
