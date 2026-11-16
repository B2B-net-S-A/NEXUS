"""Budżet Rady (R3): SQL migracji ``0728_board_budgets`` i lustra entrypointu.

* ``board_budgets`` — budżet roku: status (szkic / przyjęty), uchwała Rady,
  która go przyjęła (wiersz z ``board_documents``), notatka.
* ``board_budget_lines`` — plan miesięczny w PLN netto: sprzedaż i koszty
  z faktur (ta sama miara co pulpit, żeby wykonanie dało się porównać).

Plan wpisuje admin (Zarząd); Rada czyta. Decyzje Artura z 16.11.2026.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = ("draft", "adopted")
LINES: tuple[str, ...] = ("sales", "costs")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_STATUS = f"status IN ({_quoted(STATUSES)})"
CK_YEAR = "year BETWEEN 2020 AND 2100"
CK_LINE = f"line IN ({_quoted(LINES)})"
CK_MONTH = "month BETWEEN 1 AND 12"
CK_AMOUNT = "amount >= 0"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_budgets (
    id SERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    status VARCHAR(8) NOT NULL DEFAULT 'draft',
    resolution_document_id INTEGER NULL REFERENCES board_documents(id) ON DELETE SET NULL,
    note TEXT NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_budgets_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_board_budgets_year CHECK ({CK_YEAR})
)""",
    f"""CREATE TABLE IF NOT EXISTS board_budget_lines (
    id SERIAL PRIMARY KEY,
    budget_id INTEGER NOT NULL REFERENCES board_budgets(id) ON DELETE CASCADE,
    month SMALLINT NOT NULL,
    line VARCHAR(8) NOT NULL,
    amount NUMERIC(14,2) NOT NULL,
    CONSTRAINT ck_board_budget_lines_month CHECK ({CK_MONTH}),
    CONSTRAINT ck_board_budget_lines_line CHECK ({CK_LINE}),
    CONSTRAINT ck_board_budget_lines_amount CHECK ({CK_AMOUNT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_budgets_year ON board_budgets (year)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_budget_lines_month_line "
    "ON board_budget_lines (budget_id, month, line)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL, *CONSTRAINT_DDL, *DATA_DDL)

TABLES: tuple[str, ...] = ("board_budgets", "board_budget_lines")

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS board_budget_lines",
    "DROP TABLE IF EXISTS board_budgets",
)
