"""„Ludzie w NEXUSIE” — Mój miesiąc: SQL migracji ``0459_hr_time`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0459_hr_time.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: obecność (tylko wyjątki), timesheety i wpisy, szablony opisów.

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

* ``attendance_days`` — WYŁĄCZNIE wyjątki od domyślnego miejsca pracy
  z kartoteki (dzień w biurze u osoby zdalnej, delegacja). Dzień bez wiersza
  = praca w ``employee_profiles.default_location``. Urlop NIE jest tu
  zapisywany — żyje w ``leave_request_days`` (w Compassie obecność i urlop
  były dwoma źródłami prawdy, a skasowanie wiersza obecności odblokowywało
  godziny w dniu urlopu).
* ``timesheets`` — osoba i miesiąc. Zwrot do poprawy = powrót do ``draft``
  z ``return_note`` (bez martwego statusu ``rejected``). Nikt nie akceptuje
  własnego (``approved_by <> user_id`` — w Compassie admin zatwierdzał sam
  siebie). ``payroll_locked`` ustawia zamknięcie miesiąca płac (E3).
  ``employment_type`` — forma współpracy z chwili akceptacji (cofnięcie
  akceptacji ją czyści): archiwum potwierdzeń godzin zlecenia (art. 8c) idzie
  za formą dokumentu, nie za obecną formą osoby; stare wiersze bez niej liczą
  się obecną formą (``time_retention.document_form``).
* ``timesheet_entries`` — wpis dnia: godziny, projekt (tekst), opis
  (wymagany), źródło; nadgodziny zawsze z uzasadnieniem ≥ 5 znaków.
* ``timesheet_templates`` — osobiste fragmenty opisów.
* ``timesheet_role_defaults`` — domyślne opisy Kadr: rola + projekt
  (dobór: rola+projekt > rola > projekt > globalny).
"""

from __future__ import annotations

from app.services.hr_foundation_schema import EMPLOYMENT_TYPES

ATTENDANCE_STATUSES: tuple[str, ...] = ("active", "business_trip")
LOCATIONS: tuple[str, ...] = ("onsite", "remote")
TIMESHEET_STATUSES: tuple[str, ...] = ("draft", "submitted", "approved")
ENTRY_SOURCES: tuple[str, ...] = ("manual", "leave_paid", "template", "compass_import")

#: Dzień pracy i sufit nadgodzin (reguły Compassa, faza 27a/45).
STANDARD_DAY_HOURS = 8
OVERTIME_MAX_HOURS = 16
OVERTIME_REASON_MIN_LENGTH = 5


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_ATTENDANCE_STATUS = f"status IN ({quoted(ATTENDANCE_STATUSES)})"
# Miejsce pracy ma tylko dzień pracy; delegacja nie ma biura ani domu.
CK_ATTENDANCE_LOCATION = (
    f"(status = 'active' AND location IN ({quoted(LOCATIONS)})) "
    "OR (status <> 'active' AND location IS NULL)"
)
CK_ATTENDANCE_NOTE = "note IS NULL OR char_length(note) <= 500"

CK_TIMESHEET_YEAR = "year BETWEEN 2020 AND 2100"
CK_TIMESHEET_MONTH = "month BETWEEN 1 AND 12"
CK_TIMESHEET_STATUS = f"status IN ({quoted(TIMESHEET_STATUSES)})"
CK_TIMESHEET_NO_SELF_APPROVAL = "approved_by IS NULL OR approved_by <> user_id"
CK_TIMESHEET_PDF_HASH = "pdf_hash IS NULL OR pdf_hash ~ '^[0-9a-f]{64}$'"
CK_TIMESHEET_EMPLOYMENT_TYPE = (
    f"employment_type IS NULL OR employment_type IN ({quoted(EMPLOYMENT_TYPES)})"
)

CK_ENTRY_HOURS = "hours >= 0 AND hours <= 24"
CK_ENTRY_DESCRIPTION = "char_length(btrim(description)) > 0"
CK_ENTRY_SOURCE = f"source IN ({quoted(ENTRY_SOURCES)})"
CK_ENTRY_OVERTIME = (
    "is_overtime = false OR (overtime_reason IS NOT NULL "
    f"AND char_length(btrim(overtime_reason)) >= {OVERTIME_REASON_MIN_LENGTH})"
)

CK_TEMPLATE_NAME = "char_length(btrim(name)) BETWEEN 1 AND 80"
CK_TEMPLATE_DESCRIPTION = "char_length(btrim(description)) BETWEEN 1 AND 2000"
CK_ROLE_DEFAULT_LABEL = "char_length(btrim(label)) BETWEEN 1 AND 120"
CK_ROLE_DEFAULT_DESCRIPTION = (
    "char_length(btrim(default_description)) BETWEEN 1 AND 2000"
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS attendance_days (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    location VARCHAR(16) NULL,
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_attendance_days_user_day UNIQUE (user_id, day),
    CONSTRAINT ck_attendance_days_status CHECK ({CK_ATTENDANCE_STATUS}),
    CONSTRAINT ck_attendance_days_location CHECK ({CK_ATTENDANCE_LOCATION}),
    CONSTRAINT ck_attendance_days_note CHECK ({CK_ATTENDANCE_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS timesheets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    submitted_at TIMESTAMPTZ NULL,
    return_note TEXT NULL,
    returned_at TIMESTAMPTZ NULL,
    approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ NULL,
    pdf_hash VARCHAR(64) NULL,
    payroll_locked BOOLEAN NOT NULL DEFAULT false,
    employment_type VARCHAR(16) NULL,
    compass_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_timesheets_user_period UNIQUE (user_id, year, month),
    CONSTRAINT uq_timesheets_compass UNIQUE (compass_id),
    CONSTRAINT ck_timesheets_year CHECK ({CK_TIMESHEET_YEAR}),
    CONSTRAINT ck_timesheets_month CHECK ({CK_TIMESHEET_MONTH}),
    CONSTRAINT ck_timesheets_status CHECK ({CK_TIMESHEET_STATUS}),
    CONSTRAINT ck_timesheets_no_self_approval CHECK ({CK_TIMESHEET_NO_SELF_APPROVAL}),
    CONSTRAINT ck_timesheets_pdf_hash CHECK ({CK_TIMESHEET_PDF_HASH}),
    CONSTRAINT ck_timesheets_employment_type CHECK ({CK_TIMESHEET_EMPLOYMENT_TYPE})
)""",
    f"""CREATE TABLE IF NOT EXISTS timesheet_entries (
    id BIGSERIAL PRIMARY KEY,
    timesheet_id INTEGER NOT NULL REFERENCES timesheets(id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    hours NUMERIC(4,2) NOT NULL,
    project VARCHAR(200) NULL,
    description TEXT NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'manual',
    is_overtime BOOLEAN NOT NULL DEFAULT false,
    overtime_reason TEXT NULL,
    overtime_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_timesheet_entries_hours CHECK ({CK_ENTRY_HOURS}),
    CONSTRAINT ck_timesheet_entries_description CHECK ({CK_ENTRY_DESCRIPTION}),
    CONSTRAINT ck_timesheet_entries_source CHECK ({CK_ENTRY_SOURCE}),
    CONSTRAINT ck_timesheet_entries_overtime CHECK ({CK_ENTRY_OVERTIME})
)""",
    f"""CREATE TABLE IF NOT EXISTS timesheet_templates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    project VARCHAR(200) NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_timesheet_templates_user_name UNIQUE (user_id, name),
    CONSTRAINT ck_timesheet_templates_name CHECK ({CK_TEMPLATE_NAME}),
    CONSTRAINT ck_timesheet_templates_description CHECK ({CK_TEMPLATE_DESCRIPTION})
)""",
    f"""CREATE TABLE IF NOT EXISTS timesheet_role_defaults (
    id SERIAL PRIMARY KEY,
    label VARCHAR(120) NOT NULL,
    applies_to_role VARCHAR(40) NULL,
    project VARCHAR(200) NULL,
    default_description TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_timesheet_role_defaults_label CHECK ({CK_ROLE_DEFAULT_LABEL}),
    CONSTRAINT ck_timesheet_role_defaults_description CHECK ({CK_ROLE_DEFAULT_DESCRIPTION})
)""",
)

# Kolumny dopisane po pierwszej wersji 0459 (17.10.2026) — w bazie z wcześniejszą
# wersją tabeli; świeża baza ma je już z CREATE TABLE.
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE timesheets ADD COLUMN IF NOT EXISTS employment_type VARCHAR(16) NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_timesheets_period_status "
    "ON timesheets (year, month, status)",
    "CREATE INDEX IF NOT EXISTS ix_timesheet_entries_timesheet_date "
    "ON timesheet_entries (timesheet_id, work_date)",
    "CREATE INDEX IF NOT EXISTS ix_timesheet_role_defaults_active "
    "ON timesheet_role_defaults (is_active, applies_to_role)",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_timesheets_employment_type'
              AND conrelid = 'timesheets'::regclass
        ) THEN
            ALTER TABLE timesheets ADD CONSTRAINT ck_timesheets_employment_type
                CHECK ({CK_TIMESHEET_EMPLOYMENT_TYPE});
        END IF;
    END $$""",
)
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "attendance_days",
    "timesheets",
    "timesheet_entries",
    "timesheet_templates",
    "timesheet_role_defaults",
)

DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
