"""Płace K7b — SQL migracji ``0719_payroll_salaries`` i lustra entrypointu.

Jedno źródło DDL dla migracji i ``entrypoint.sh`` (przez ``hr_schema_bundle``);
każda instrukcja idempotentna. Reguły: ``docs/claude/finanse-insights/ksiega-nexusa-k7b-place-uop.md``.

* ``payroll_salaries`` — pensja zasadnicza osoby na umowie o pracę (kwota za
  pełny miesiąc i wymiar etatu) od 1. dnia miesiąca, z historią. Widzą i
  zmieniają tylko Płace i administrator (D2); swojej nie zmienia się samemu.
* ``payroll_components`` — składniki miesiąca wpisane przez Płace: zmienne
  (w podstawie chorobowego i średniej urlopowej, np. nadgodziny), inne (poza
  podstawami, np. nagroda), podstawa chorobowego wpisana ręcznie i dni
  urlopu do ekwiwalentu wpisane ręcznie. Jeden wiersz na okres × osoba × rodzaj.
* ``payroll_absence_marks`` — oznaczenie Płac przy zwolnieniu lekarskim
  z modułu urlopów: 80% / 100% / zasiłek z ZUS od 1. dnia i zwolnienie
  z okresu wyczekiwania (wypadek w drodze). Rodzaj nieobecności to dana
  o zdrowiu — tabela tylko dla Płac (D6).
* ``payroll_basis_months`` — historia podstaw sprzed NEXUSA (jednorazowy
  import z Enovy, decyzja Artura 16.11.2026): miesiąc osoby ze składnikami
  stałymi i zmiennymi oraz godzinami. Miesiąc z zatwierdzoną listą NEXUSA
  bierze się z listy, nie stąd (jedno źródło miesiąca).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted
from app.services.hr_payroll_lists_schema import (
    GROSS_MAX,
    LINE_SOURCES,
    NOTE_MAX,
)

COMPONENT_KINDS: tuple[str, ...] = ("variable", "other", "sick_base", "equivalent_days")
SICK_RATES: tuple[str, ...] = ("80", "100", "zus")
BASIS_SOURCES: tuple[str, ...] = ("enova",)
HOURS_MAX = "744"

CK_SALARY_AMOUNT = f"monthly_amount > 0 AND monthly_amount <= {GROSS_MAX}"
CK_SALARY_FTE = "fte > 0 AND fte <= 1"
CK_SALARY_FIRST_DAY = "EXTRACT(DAY FROM effective_from) = 1"
CK_SALARY_RANGE = "effective_to IS NULL OR effective_to >= effective_from"
CK_SALARY_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"

CK_COMPONENT_KIND = f"kind IN ({quoted(COMPONENT_KINDS)})"
CK_COMPONENT_AMOUNT = f"amount >= 0 AND amount <= {GROSS_MAX}"
CK_COMPONENT_NOTE = f"char_length(note) BETWEEN 3 AND {NOTE_MAX}"

CK_MARK_RATE = f"sick_rate IN ({quoted(SICK_RATES)})"
CK_MARK_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX}"

CK_BASIS_YEAR = "year BETWEEN 2020 AND 2100"
CK_BASIS_MONTH = "month BETWEEN 1 AND 12"
CK_BASIS_AMOUNTS = (
    f"fixed_paid >= 0 AND fixed_paid <= {GROSS_MAX} "
    f"AND fixed_full >= 0 AND fixed_full <= {GROSS_MAX} "
    f"AND variable >= 0 AND variable <= {GROSS_MAX} "
    f"AND leave_variable >= 0 AND leave_variable <= {GROSS_MAX}"
)
CK_BASIS_HOURS = (
    f"nominal_hours >= 0 AND nominal_hours <= {HOURS_MAX} "
    "AND worked_hours >= 0 AND worked_hours <= nominal_hours "
    "AND paid_hours >= worked_hours AND paid_hours <= nominal_hours"
)
CK_BASIS_SOURCE = f"source IN ({quoted(BASIS_SOURCES)})"

#: Źródło pozycji listy rozszerzone o pensję (0719).
CK_LINE_SOURCE = f"source IN ({quoted(LINE_SOURCES)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS payroll_salaries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    monthly_amount NUMERIC(12,2) NOT NULL,
    fte NUMERIC(4,3) NOT NULL DEFAULT 1,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    note VARCHAR({NOTE_MAX}) NULL,
    set_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    set_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_salaries_amount CHECK ({CK_SALARY_AMOUNT}),
    CONSTRAINT ck_payroll_salaries_fte CHECK ({CK_SALARY_FTE}),
    CONSTRAINT ck_payroll_salaries_first_day CHECK ({CK_SALARY_FIRST_DAY}),
    CONSTRAINT ck_payroll_salaries_range CHECK ({CK_SALARY_RANGE}),
    CONSTRAINT ck_payroll_salaries_note CHECK ({CK_SALARY_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_components (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    kind VARCHAR(16) NOT NULL,
    amount NUMERIC(14,2) NOT NULL,
    note VARCHAR({NOTE_MAX}) NOT NULL,
    entered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_components_kind CHECK ({CK_COMPONENT_KIND}),
    CONSTRAINT ck_payroll_components_amount CHECK ({CK_COMPONENT_AMOUNT}),
    CONSTRAINT ck_payroll_components_note CHECK ({CK_COMPONENT_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_absence_marks (
    leave_request_id UUID PRIMARY KEY REFERENCES leave_requests(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    sick_rate VARCHAR(4) NOT NULL DEFAULT '80',
    waiting_exempt BOOLEAN NOT NULL DEFAULT false,
    note VARCHAR({NOTE_MAX}) NULL,
    set_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    set_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_absence_marks_rate CHECK ({CK_MARK_RATE}),
    CONSTRAINT ck_payroll_absence_marks_note CHECK ({CK_MARK_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_basis_months (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    fixed_paid NUMERIC(14,2) NOT NULL,
    fixed_full NUMERIC(14,2) NOT NULL,
    variable NUMERIC(14,2) NOT NULL DEFAULT 0,
    leave_variable NUMERIC(14,2) NOT NULL DEFAULT 0,
    nominal_hours NUMERIC(6,2) NOT NULL,
    worked_hours NUMERIC(6,2) NOT NULL,
    paid_hours NUMERIC(6,2) NOT NULL,
    full_month BOOLEAN NOT NULL DEFAULT true,
    source VARCHAR(8) NOT NULL DEFAULT 'enova',
    file_sha256 VARCHAR(64) NULL,
    entered_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_basis_months_year CHECK ({CK_BASIS_YEAR}),
    CONSTRAINT ck_payroll_basis_months_month CHECK ({CK_BASIS_MONTH}),
    CONSTRAINT ck_payroll_basis_months_amounts CHECK ({CK_BASIS_AMOUNTS}),
    CONSTRAINT ck_payroll_basis_months_hours CHECK ({CK_BASIS_HOURS}),
    CONSTRAINT ck_payroll_basis_months_source CHECK ({CK_BASIS_SOURCE})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_salaries_user_from "
    "ON payroll_salaries (user_id, effective_from)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_components_period_user_kind "
    "ON payroll_components (period_id, user_id, kind)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_absence_marks_user "
    "ON payroll_absence_marks (user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_basis_months_user_month "
    "ON payroll_basis_months (user_id, year, month)",
)

#: Pozycja listy z pensji (``source='salary'``): CHECK z 0704 nie znał tej
#: wartości. Zmieniamy go tylko, gdy definicja w bazie jej nie zawiera — inaczej
#: każdy start brałby blokadę tabeli.
CONSTRAINT_DDL: tuple[str, ...] = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_payroll_list_lines_source' "
    "AND pg_get_constraintdef(oid) LIKE '%salary%') THEN "
    "ALTER TABLE payroll_list_lines DROP CONSTRAINT IF EXISTS ck_payroll_list_lines_source; "
    "ALTER TABLE payroll_list_lines ADD CONSTRAINT ck_payroll_list_lines_source "
    f"CHECK ({CK_LINE_SOURCE}); "
    "END IF; END $$",
)

DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "payroll_salaries",
    "payroll_components",
    "payroll_absence_marks",
    "payroll_basis_months",
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
