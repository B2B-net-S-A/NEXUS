"""Narzędzia, standardy i pojęcia AI w słowniku umiejętności (28.09.2026).

Pomiar na produkcji: wiersz wymagań „Jira” w „Szukaj ręcznie” nie był
technologią (słownik miał 196 pozycji, bez narzędzi), więc schodził do
„Mile widziane” — DL wpisywał wymaganie, a lista go nie wymagała. Lista
pozycji żyje w ``app/data/skill_catalog_tools.json``; migracja 0397 zasiewa ją
idempotentnie i nie nadpisuje niczego, co admin zapisał w Ustawieniach →
Słownik umiejętności.

Kategorie są spoza ``skill_normalize.TECH_CATEGORIES``: generator CV
(pogrubienia), przegląd DZ i „Podobne rekrutacje” czytają tylko tamte, więc
te pozycje zmieniają wyszukiwanie i rozpoznawanie umiejętności w scoringu,
a nie wygląd CV ani podobieństwo rekrutacji.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "skill_catalog_tools.json"
CATEGORIES = frozenset({"tools", "standards", "ai"})


@lru_cache(maxsize=1)
def entries() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """(nazwa, kategoria, aliasy małymi literami)."""
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))["skills"]
    return tuple(
        (name, category, tuple(a.lower() for a in aliases))
        for name, category, aliases in raw
    )


# Istniejąca nazwa albo alias wygrywa: zasiew tylko dokłada.
SEED_SKILL_SQL = """
INSERT INTO skills (canonical_name, category)
SELECT CAST(:name AS text), CAST(:category AS text)
WHERE NOT EXISTS (SELECT 1 FROM skills WHERE lower(canonical_name) = lower(:name))
  AND NOT EXISTS (SELECT 1 FROM skill_aliases WHERE lower(alias) = lower(:name))
ON CONFLICT (canonical_name) DO NOTHING
"""

SEED_ALIAS_SQL = """
INSERT INTO skill_aliases (skill_id, alias)
SELECT s.id, CAST(:alias AS text) FROM skills s
WHERE s.canonical_name = :name AND s.category = :category
  AND NOT EXISTS (SELECT 1 FROM skill_aliases WHERE lower(alias) = lower(:alias))
  AND NOT EXISTS (SELECT 1 FROM skills WHERE lower(canonical_name) = lower(:alias))
ON CONFLICT (alias) DO NOTHING
"""


def seed(conn) -> None:
    """Zasiew na połączeniu SQLAlchemy (migracja)."""
    from sqlalchemy import text

    for name, category, aliases in entries():
        conn.execute(text(SEED_SKILL_SQL), {"name": name, "category": category})
        for alias in aliases:
            conn.execute(
                text(SEED_ALIAS_SQL),
                {"alias": alias, "name": name, "category": category},
            )
