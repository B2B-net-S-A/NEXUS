"""Rozrachunki z rozliczaniem pozycji (K4b) — SQL migracji ``0706_ledger_settlements``.

Jedno źródło DDL dla ``alembic/versions/0706_ledger_settlements.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda instrukcja
idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

* ``ledger_settlements`` — rozliczenie dwóch pozycji rozrachunkowych: zapisu
  po stronie Wn i zapisu po stronie Ma tego samego konta kontrahenta
  (analityka konta ze słownikiem „kontrahent”, np. ``200-1234``), kwota
  w groszach. Pozycje to zapisy zatwierdzonych dokumentów, więc się nie
  zmieniają; rozliczenie można cofnąć (``removed_at`` / ``removed_by`` —
  wiersz zostaje jako ślad). Sposób: ``bank`` (operacja wyciągu dopasowana do
  faktury w E3/E8), ``correction`` (korekta faktury sprzedaży z fakturą
  pierwotną), ``zero`` (pozycje kontrahenta, które razem dają zero),
  ``manual``. Data rozliczenia = późniejsza z dat operacji obu dokumentów
  (rozrachunki „na dzień”). Wrażliwość ``payroll`` (D2) ma rozliczenie
  dokumentów płacowych — oba zapisy muszą mieć tę samą.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted
from app.services.ledger_schema import ACCOUNT_MAX, SENSITIVITIES

METHODS: tuple[str, ...] = ("bank", "correction", "zero", "manual")

CK_AMOUNT = "amount > 0"
CK_METHOD = f"method IN ({quoted(METHODS)})"
CK_LINES = "debit_line_id <> credit_line_id"
CK_SENSITIVITY = f"sensitivity IS NULL OR sensitivity IN ({quoted(SENSITIVITIES)})"
ACTIVE_WHERE = "removed_at IS NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_settlements (
    id BIGSERIAL PRIMARY KEY,
    account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    debit_line_id BIGINT NOT NULL REFERENCES ledger_lines(id) ON DELETE CASCADE,
    credit_line_id BIGINT NOT NULL REFERENCES ledger_lines(id) ON DELETE CASCADE,
    amount BIGINT NOT NULL,
    settled_on DATE NOT NULL,
    method VARCHAR(12) NOT NULL,
    sensitivity VARCHAR(8) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    removed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_ledger_settlements_amount CHECK ({CK_AMOUNT}),
    CONSTRAINT ck_ledger_settlements_method CHECK ({CK_METHOD}),
    CONSTRAINT ck_ledger_settlements_lines CHECK ({CK_LINES}),
    CONSTRAINT ck_ledger_settlements_sensitivity CHECK ({CK_SENSITIVITY})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_ledger_settlements_debit "
    f"ON ledger_settlements (debit_line_id) WHERE {ACTIVE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_ledger_settlements_credit "
    f"ON ledger_settlements (credit_line_id) WHERE {ACTIVE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_ledger_settlements_account "
    f"ON ledger_settlements (account, settled_on) WHERE {ACTIVE_WHERE}",
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

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS ledger_settlements",)
