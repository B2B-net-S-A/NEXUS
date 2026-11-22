"""Sprawozdania roczne dla Rady (R4): SQL migracji ``0734_board_statements``
i lustra entrypointu.

``board_financial_statements`` — jeden wiersz na rok obrotowy: pozycje
bilansu i RZiS sprowadzone do wspólnych pól (``amounts``, PLN), surowe
pozycje pliku (``raw``) do sprawdzenia z PDF-em i źródło:

* ``xml`` — e-Sprawozdanie z eKRS (kolumna „rok bieżący” pliku),
* ``xml_prev`` — kolumna „rok poprzedni” z pliku za rok następny
  (tylko gdy roku nie ma z innego źródła),
* ``manual`` — wpisane przez admina z papierowego sprawozdania.

Rok z księgi NEXUSA liczy się na bieżąco i nie trafia do tabeli.
Decyzje Artura z 16.11.2026: Rada czyta, admin wgrywa.
"""

from __future__ import annotations

SOURCES: tuple[str, ...] = ("xml", "xml_prev", "manual")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_SOURCE = f"source IN ({_quoted(SOURCES)})"
CK_YEAR = "year BETWEEN 2000 AND 2100"
CK_AMOUNTS = "jsonb_typeof(amounts) = 'object'"
CK_RAW = "jsonb_typeof(raw) = 'object'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_financial_statements (
    id SERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    period_start DATE NULL,
    period_end DATE NULL,
    source VARCHAR(8) NOT NULL,
    schema_name VARCHAR(120) NULL,
    document_id INTEGER NULL REFERENCES board_documents(id) ON DELETE SET NULL,
    amounts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    note TEXT NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_financial_statements_source CHECK ({CK_SOURCE}),
    CONSTRAINT ck_board_financial_statements_year CHECK ({CK_YEAR}),
    CONSTRAINT ck_board_financial_statements_amounts CHECK ({CK_AMOUNTS}),
    CONSTRAINT ck_board_financial_statements_raw CHECK ({CK_RAW})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_financial_statements_year "
    "ON board_financial_statements (year)",
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

TABLES: tuple[str, ...] = ("board_financial_statements",)

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS board_financial_statements",)
