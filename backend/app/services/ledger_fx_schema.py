"""Waluty w księdze (K4c-1) — SQL migracji ``0707_ledger_fx``.

Jedno źródło DDL dla ``alembic/versions/0707_ledger_fx.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``, po K4a i K4b); każda
instrukcja idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

* ``ledger_bank_statements.currency`` — wyciągi rachunków w EUR i USD (te same
  waluty co E8 i R9); CHECK z K4a (tylko PLN) zamieniony w miejscu.
* ``ledger_bank_lines`` — ``amount`` jest w walucie wyciągu (grosze/centy);
  operacja walutowa ma też kwotę w PLN po średnim kursie NBP z ostatniego dnia
  roboczego przed operacją (art. 30 ust. 2 pkt 2 ustawy o rachunkowości), kurs
  i jego datę.
* ``ledger_lines.fx_rate`` / ``fx_date`` — kurs pozycji, gdy inny niż kurs
  dokumentu (WB z rachunku walutowego: każda operacja ma swój dzień kursu).
* ``ledger_settlements.currency`` / ``amount_cur`` / ``credit_amount`` —
  rozliczenie pary w tej samej walucie obcej: kwota w walucie, ``amount`` =
  udział PLN pozycji Wn, ``credit_amount`` = udział PLN pozycji Ma (różnicę
  udziałów księguje dokument różnicy kursowej, źródło ``fx_difference``).
"""

from __future__ import annotations

from app.services import ledger_bank_schema as bank
from app.services.consultant_portal_schema import quoted

CURRENCIES = bank.CURRENCIES
FX_RATE_SCALE = "NUMERIC(14, 6)"

CK_BANK_LINE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_BANK_LINE_FX = (
    "currency = 'PLN' OR (amount_pln IS NOT NULL AND fx_rate IS NOT NULL "
    "AND fx_date IS NOT NULL)"
)
CK_SETTLEMENT_CURRENCY = (
    "(currency IS NULL) = (amount_cur IS NULL) "
    "AND (amount_cur IS NULL OR amount_cur > 0) "
    "AND (credit_amount IS NULL OR (credit_amount > 0 AND currency IS NOT NULL))"
)

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE ledger_bank_lines ADD COLUMN IF NOT EXISTS currency VARCHAR(3) "
    "NOT NULL DEFAULT 'PLN'",
    "ALTER TABLE ledger_bank_lines ADD COLUMN IF NOT EXISTS amount_pln BIGINT NULL",
    f"ALTER TABLE ledger_bank_lines ADD COLUMN IF NOT EXISTS fx_rate {FX_RATE_SCALE} NULL",
    "ALTER TABLE ledger_bank_lines ADD COLUMN IF NOT EXISTS fx_date DATE NULL",
    f"ALTER TABLE ledger_lines ADD COLUMN IF NOT EXISTS fx_rate {FX_RATE_SCALE} NULL",
    "ALTER TABLE ledger_lines ADD COLUMN IF NOT EXISTS fx_date DATE NULL",
    "ALTER TABLE ledger_settlements ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NULL",
    "ALTER TABLE ledger_settlements ADD COLUMN IF NOT EXISTS amount_cur BIGINT NULL",
    "ALTER TABLE ledger_settlements ADD COLUMN IF NOT EXISTS credit_amount BIGINT NULL",
)

INDEX_DDL: tuple[str, ...] = ()


def _replace_check(table: str, name: str, expression: str, marker: str) -> str:
    """CHECK zamieniony tylko, gdy jego treść nie ma jeszcze ``marker`` (bez
    przebudowy przy każdym starcie entrypointu — pełny skan pod blokadą)."""

    return f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{name}'
          AND pg_get_constraintdef(oid) LIKE '%{marker}%'
    ) THEN
        ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name};
        ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression});
    END IF;
END $$"""


def _add_check(table: str, name: str, expression: str) -> str:
    return f"""DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
        ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression});
    END IF;
END $$"""


CONSTRAINT_DDL: tuple[str, ...] = (
    _replace_check(
        "ledger_bank_statements",
        "ck_ledger_bank_statements_currency",
        bank.CK_STATEMENT_CURRENCY,
        "EUR",
    ),
    _add_check(
        "ledger_bank_lines", "ck_ledger_bank_lines_currency", CK_BANK_LINE_CURRENCY
    ),
    _add_check("ledger_bank_lines", "ck_ledger_bank_lines_fx", CK_BANK_LINE_FX),
    _add_check(
        "ledger_settlements",
        "ck_ledger_settlements_currency",
        CK_SETTLEMENT_CURRENCY,
    ),
)

#: Kwota w PLN operacji z wyciągów sprzed K4c (same PLN) = kwota operacji.
DATA_DDL: tuple[str, ...] = (
    "UPDATE ledger_bank_lines SET amount_pln = amount "
    "WHERE amount_pln IS NULL AND currency = 'PLN'",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE ledger_settlements DROP CONSTRAINT IF EXISTS ck_ledger_settlements_currency",
    "ALTER TABLE ledger_settlements DROP COLUMN IF EXISTS credit_amount",
    "ALTER TABLE ledger_settlements DROP COLUMN IF EXISTS amount_cur",
    "ALTER TABLE ledger_settlements DROP COLUMN IF EXISTS currency",
    "ALTER TABLE ledger_lines DROP COLUMN IF EXISTS fx_date",
    "ALTER TABLE ledger_lines DROP COLUMN IF EXISTS fx_rate",
    "ALTER TABLE ledger_bank_lines DROP CONSTRAINT IF EXISTS ck_ledger_bank_lines_fx",
    "ALTER TABLE ledger_bank_lines DROP CONSTRAINT IF EXISTS ck_ledger_bank_lines_currency",
    "ALTER TABLE ledger_bank_lines DROP COLUMN IF EXISTS fx_date",
    "ALTER TABLE ledger_bank_lines DROP COLUMN IF EXISTS fx_rate",
    "ALTER TABLE ledger_bank_lines DROP COLUMN IF EXISTS amount_pln",
    "ALTER TABLE ledger_bank_lines DROP COLUMN IF EXISTS currency",
)
