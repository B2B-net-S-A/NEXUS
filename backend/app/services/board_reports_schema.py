"""Gotówka i archiwum raportów Rady (R7): SQL migracji ``0737_board_reports``
i lustra entrypointu.

* ``board_cash_positions`` — stan środków pieniężnych na dzień, wpisany przez
  admina (Zarząd) z wyciągów. Księga NEXUSA nie trzyma jeszcze sald rachunków,
  a flaga „zapłacono” z eBI24 jest niewiarygodna — stąd wpis ręczny.
* ``board_reports`` — zamrożone raporty PDF (miesięczny, roczny, budżet):
  admin zapisuje raport w archiwum, żeby Rada miała tę samą wersję liczb, o
  której rozmawiała, choć faktury kosztowe później jeszcze spływają.

Decyzje z 18.11.2026 (uwagi Rady do pulpitu): Rada czyta, admin wpisuje.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("monthly", "annual", "budget")
NOTE_MAX = 500


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_KIND = f"kind IN ({_quoted(KINDS)})"
CK_YEAR = "year BETWEEN 2000 AND 2100"
CK_MONTH = "month IS NULL OR month BETWEEN 1 AND 12"
CK_MONTHLY_HAS_MONTH = "(kind = 'monthly') = (month IS NOT NULL)"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_cash_positions (
    id SERIAL PRIMARY KEY,
    as_of DATE NOT NULL,
    amount NUMERIC(16,2) NOT NULL,
    note VARCHAR({NOTE_MAX}) NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE IF NOT EXISTS board_reports (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(8) NOT NULL,
    year SMALLINT NOT NULL,
    month SMALLINT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_reports_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_board_reports_year CHECK ({CK_YEAR}),
    CONSTRAINT ck_board_reports_month CHECK ({CK_MONTH}),
    CONSTRAINT ck_board_reports_monthly_has_month CHECK ({CK_MONTHLY_HAS_MONTH})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_cash_positions_as_of "
    "ON board_cash_positions (as_of)",
    "CREATE INDEX IF NOT EXISTS ix_board_reports_period "
    "ON board_reports (kind, year, month)",
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

TABLES: tuple[str, ...] = ("board_cash_positions", "board_reports")

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS board_reports",
    "DROP TABLE IF EXISTS board_cash_positions",
)
