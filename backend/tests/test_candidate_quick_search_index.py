"""Szybkie wyszukiwanie kandydatów stoi na indeksach z migracji 0662.

Indeks działa tylko na identycznym wyrażeniu. Rozjazd tekstu w kodzie, migracji
albo lustrze ``entrypoint.sh`` niczego nie psuje widocznie, a wyszukiwarka
wraca do seq scanu 68 tys. wierszy (audyt 08.11.2026, S4/W6). Stąd porównanie
źródeł i plan zapytania na żywej bazie.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import or_, select, text

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.api.search import _CANDIDATE_IDENTITY_FOLDED_SQL, _candidate_quick_match
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.candidate_search_predicates import PHONE_DIGITS_SQL

_BACKEND = Path(__file__).resolve().parents[1]
_SOURCES = {
    "migracja": _BACKEND / "alembic/versions/0662_candidate_quick_search_indexes.py",
    "entrypoint": _BACKEND / "entrypoint.sh",
}


def _compact(sql: str) -> str:
    """Bez nazwy tabeli, spacji i łączeń literałów Pythona."""
    return re.sub(r'["\s]', "", sql.replace("candidates.", ""))


@pytest.mark.parametrize("source", sorted(_SOURCES))
@pytest.mark.parametrize(
    "expression",
    [_CANDIDATE_IDENTITY_FOLDED_SQL, PHONE_DIGITS_SQL],
    ids=["identity", "phone"],
)
def test_index_ddl_uses_the_exact_query_expression(source, expression):
    assert _compact(expression) in _compact(
        _SOURCES[source].read_text(encoding="utf-8")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "index"),
    [
        ("nieistniejaca-fraza", "ix_candidates_quick_identity_trgm"),
        ("Jerzy Leśniawski", "ix_candidates_quick_identity_trgm"),
        ("600 700 800", "ix_candidates_phone_digits_trgm"),
    ],
)
async def test_quick_match_can_use_the_trigram_index(query, index):
    """Plan z wyłączonym seq scanem: wyrażenie w zapytaniu pasuje do indeksu."""
    stmt = select(Candidate.id).where(or_(*_candidate_quick_match(query)))
    async with AsyncSessionLocal() as db:
        dialect = (await db.connection()).dialect
        compiled = stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = await db.execute(text("EXPLAIN " + str(compiled).replace(":", "\\:")))
        rendered = "\n".join(row[0] for row in plan)
    assert index in rendered, rendered
