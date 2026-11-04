"""``scripts/staging/sanitize.sql`` odwołuje się do istniejących tabel i kolumn.

Sanitizacja biegnie na kopii produkcji z ``ON_ERROR_STOP``: przemianowana
tabela albo kolumna zatrzymałaby odtworzenie stagingu dopiero na laptopie.
Test porównuje nazwy z plikiem SQL z modelami SQLAlchemy, bez bazy.
"""

from __future__ import annotations

import re
from pathlib import Path

import app.models  # noqa: F401 — rejestruje wszystkie tabele w metadanych
from app.core.database import Base

SANITIZE = Path(__file__).resolve().parents[2] / "scripts" / "staging" / "sanitize.sql"


def _statements() -> list[str]:
    text = re.sub(r"--[^\n]*", "", SANITIZE.read_text(encoding="utf-8"))
    return [s.strip() for s in text.split(";") if s.strip()]


def test_sanitize_tables_and_columns_exist():
    tables = Base.metadata.tables
    seen = set()
    for stmt in _statements():
        update = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.*?)(?:\s+WHERE\s|$)", stmt, re.S)
        delete = re.match(r"DELETE\s+FROM\s+(\w+)", stmt)
        if update:
            table, assignments = update.group(1), update.group(2)
            assert table in tables, f"brak tabeli {table}"
            for column in re.findall(r"(\w+)\s*=", assignments):
                assert column in tables[table].c, f"brak kolumny {table}.{column}"
            seen.add(table)
        elif delete:
            assert delete.group(1) in tables, f"brak tabeli {delete.group(1)}"
            seen.add(delete.group(1))
    assert {"m365_connections", "graph_subscriptions", "service_account_keys"} <= seen
