"""Zajęcia wierzytelności i spory przy płatnościach kontraktorów (23.11.2026).

Jedno źródło SQL dla migracji ``0764_contractor_payment_blocks`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Każda instrukcja idempotentna,
same dodania — stary kod działa na nowym schemacie.

* ``contractor_garnishments`` — zajęcie wierzytelności kontraktora (komornik,
  e-Urząd Skarbowy, inny organ) na kontrakcie: organ, sygnatura, data
  doręczenia, należność, koszty, odsetki (brak / kwota / stopa od dnia /
  nieustalone), rachunek organu, uchylenie (data, kto, uwaga).
* ``contractor_payment_holds`` — „Spór / wstrzymane” na rozliczeniu
  kontraktora (``client_settlements``): powód, kto i kiedy zdecydował, kto
  zwolnił. Jedno aktywne wstrzymanie na rozliczenie (indeks częściowy),
  zwolnione zostają jako ślad.
* ``finance_payment_batch_items.garnishments`` — przelewy do organów
  wydzielone z płatności faktury przy tworzeniu paczki (kwota, rachunek,
  tytuł, sygnatura z chwili paczki). ``amount`` pozycji zostaje całą kwotą
  zapłaty faktury; kontraktor dostaje ``amount`` minus te przelewy.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

AUTHORITY_KINDS: tuple[str, ...] = ("bailiff", "tax_office", "other")
INTEREST_MODES: tuple[str, ...] = ("none", "fixed", "rate", "unknown")

NAME_MAX = 255
CASE_MAX = 120
ACCOUNT_MAX = 34
NOTE_MAX = 500

CK_AUTHORITY_KIND = f"authority_kind IN ({quoted(AUTHORITY_KINDS)})"
CK_INTEREST_MODE = f"interest_mode IN ({quoted(INTEREST_MODES)})"
CK_PRINCIPAL = "principal_amount > 0"
CK_COSTS = "costs_amount >= 0"
CK_INTEREST_AMOUNT = "interest_amount IS NULL OR interest_amount >= 0"
CK_INTEREST_RATE = (
    "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate < 100)"
)
ACTIVE_HOLD_WHERE = "released_at IS NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS contractor_garnishments (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    authority_kind VARCHAR(16) NOT NULL,
    authority_name VARCHAR({NAME_MAX}) NOT NULL,
    case_number VARCHAR({CASE_MAX}) NOT NULL,
    served_on DATE NOT NULL,
    principal_amount NUMERIC(14, 2) NOT NULL,
    costs_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    interest_mode VARCHAR(10) NOT NULL DEFAULT 'unknown',
    interest_amount NUMERIC(14, 2) NULL,
    interest_rate NUMERIC(6, 3) NULL,
    interest_from DATE NULL,
    authority_account VARCHAR({ACCOUNT_MAX}) NULL,
    note VARCHAR({NOTE_MAX}) NULL,
    lifted_on DATE NULL,
    lifted_note VARCHAR({NOTE_MAX}) NULL,
    lifted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    lifted_at TIMESTAMPTZ NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_contractor_garnishments_authority_kind CHECK ({CK_AUTHORITY_KIND}),
    CONSTRAINT ck_contractor_garnishments_interest_mode CHECK ({CK_INTEREST_MODE}),
    CONSTRAINT ck_contractor_garnishments_principal CHECK ({CK_PRINCIPAL}),
    CONSTRAINT ck_contractor_garnishments_costs CHECK ({CK_COSTS}),
    CONSTRAINT ck_contractor_garnishments_interest_amount CHECK ({CK_INTEREST_AMOUNT}),
    CONSTRAINT ck_contractor_garnishments_interest_rate CHECK ({CK_INTEREST_RATE})
)""",
    f"""CREATE TABLE IF NOT EXISTS contractor_payment_holds (
    id SERIAL PRIMARY KEY,
    settlement_id INTEGER NOT NULL REFERENCES client_settlements(id) ON DELETE CASCADE,
    reason VARCHAR({NOTE_MAX}) NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    released_at TIMESTAMPTZ NULL,
    release_note VARCHAR({NOTE_MAX}) NULL
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE finance_payment_batch_items "
    "ADD COLUMN IF NOT EXISTS garnishments JSONB NOT NULL DEFAULT '[]'::jsonb",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contractor_garnishments_contract "
    "ON contractor_garnishments (contract_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_contractor_payment_holds_active "
    f"ON contractor_payment_holds (settlement_id) WHERE {ACTIVE_HOLD_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_contractor_payment_holds_settlement "
    "ON contractor_payment_holds (settlement_id, id)",
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
    "ALTER TABLE finance_payment_batch_items DROP COLUMN IF EXISTS garnishments",
    "DROP TABLE IF EXISTS contractor_payment_holds",
    "DROP TABLE IF EXISTS contractor_garnishments",
)
