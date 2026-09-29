"""Zasiew bazy wiedzy „po ludzku” z plików w repo.

``app/data/plain_knowledge/terms.json`` i ``roles.json`` to wiedza OGÓLNA
(technologie, role) z researchu w internecie, przejrzana przez człowieka
(``scripts/build_plain_knowledge.py``). Opisy klientów NIE są w repo — repo jest
publiczne, a lista klientów to informacja handlowa; idą ``--apply`` na produkcji.

Zasiew biegnie w migracji 0402 i przy każdym starcie (entrypoint), więc
poprawka pliku w repo dociera bez nowej migracji. Wiersz poprawiony w
aplikacji (``origin='manual'``) NIGDY nie jest nadpisywany; wiersz z zasiewu
albo dopisany przez AI dostaje treść z pliku (plik jest przejrzany przez
człowieka, research AI — nie).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "plain_knowledge"

_TERM_COLUMNS = (
    "term_key",
    "display_name",
    "summary",
    "does",
    "cv_hints",
    "confused_with",
    "sources",
)
_ROLE_COLUMNS = (
    "slug",
    "name",
    "summary",
    "example",
    "day_to_day",
    "candidate_questions",
    "typical_skills",
    "match_rules",
    "sources",
)
_JSON_COLUMNS = frozenset(
    {
        "cv_hints",
        "sources",
        "day_to_day",
        "candidate_questions",
        "typical_skills",
        "match_rules",
    }
)


def _load(name: str, key: str, base: Path | None = None) -> list[dict[str, Any]]:
    path = (base or DATA_DIR) / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get(key) if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def term_rows(base: Path | None = None) -> list[dict[str, Any]]:
    return [
        r
        for r in _load("terms.json", "terms", base)
        if r.get("term_key") and r.get("display_name")
    ]


def role_rows(base: Path | None = None) -> list[dict[str, Any]]:
    return [
        r for r in _load("roles.json", "roles", base) if r.get("slug") and r.get("name")
    ]


def _upsert_sql(table: str, columns: tuple[str, ...], key: str, style: str) -> str:
    """Ten sam upsert w dwóch stylach parametrów: `$n` (asyncpg) i `:nazwa` (migracja)."""
    if style == "dollar":
        values = ", ".join(
            f"${i + 1}" + ("::jsonb" if c in _JSON_COLUMNS else "")
            for i, c in enumerate(columns)
        )
    else:
        values = ", ".join(
            f"CAST(:{c} AS jsonb)" if c in _JSON_COLUMNS else f":{c}" for c in columns
        )
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}, origin, status) "
        f"VALUES ({values}, 'seed', 'ready') "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates}, origin = 'seed', "
        f"status = 'ready', claimed_at = NULL, updated_at = now() "
        f"WHERE {table}.origin <> 'manual'"
    )


TERM_SQL_NAMED = _upsert_sql("plain_terms", _TERM_COLUMNS, "term_key", "named")
TERM_SQL_DOLLAR = _upsert_sql("plain_terms", _TERM_COLUMNS, "term_key", "dollar")
ROLE_SQL_NAMED = _upsert_sql("role_profiles", _ROLE_COLUMNS, "slug", "named")
ROLE_SQL_DOLLAR = _upsert_sql("role_profiles", _ROLE_COLUMNS, "slug", "dollar")


def _value(row: dict[str, Any], col: str) -> Any:
    value = row.get(col)
    if col in _JSON_COLUMNS:
        empty: Any = {} if col == "match_rules" else []
        return json.dumps(value if value is not None else empty, ensure_ascii=False)
    if col == "term_key" and isinstance(value, str):
        return value.strip().lower()
    return value


def seed_sync(conn, base: Path | None = None) -> tuple[int, int]:
    """Zasiew na połączeniu SQLAlchemy (migracja). Zwraca (terminy, role)."""
    from sqlalchemy import text

    terms = term_rows(base)
    roles = role_rows(base)
    for row in terms:
        conn.execute(text(TERM_SQL_NAMED), {c: _value(row, c) for c in _TERM_COLUMNS})
    for row in roles:
        conn.execute(text(ROLE_SQL_NAMED), {c: _value(row, c) for c in _ROLE_COLUMNS})
    return len(terms), len(roles)


async def seed_async(conn, base: Path | None = None) -> tuple[int, int]:
    """Zasiew na połączeniu asyncpg (entrypoint)."""
    terms = term_rows(base)
    roles = role_rows(base)
    for row in terms:
        await conn.execute(TERM_SQL_DOLLAR, *[_value(row, c) for c in _TERM_COLUMNS])
    for row in roles:
        await conn.execute(ROLE_SQL_DOLLAR, *[_value(row, c) for c in _ROLE_COLUMNS])
    return len(terms), len(roles)
