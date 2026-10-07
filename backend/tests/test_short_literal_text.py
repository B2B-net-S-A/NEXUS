"""Krótki tekst dosłowny (≤ 2 znaki) w v2 = całe słowo przez indeks (07.10.2026).

Indeks trigramowy nie działa dla tekstu krótszego niż 3 znaki, więc podłańcuch
czytał całe CV, profile i notatki: na produkcji „c#” w trybie dosłownym
trwało 10–30 s. v1 (alerty zapisanych wyszukiwań) zostaje przy podłańcuchu.

Baza testowa jest wspólna i nieczyszczona — asercje dotyczą własnych wierszy.
"""

import uuid

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services import keyword_corpus
from app.services.candidate_search_predicates import literal_text_clause


async def _people() -> dict[str, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        rows = {
            "csharp_cv": Candidate(
                name="Ala",
                lastname=f"Sharp-{tag}",
                raw_cv_text="Senior C# developer, .NET",
            ),
            "glued": Candidate(
                name="Ola",
                lastname=f"Glued-{tag}",
                raw_cv_text="Projekt abc#x w firmie",
            ),
            "surname_go": Candidate(
                name="Ewa", lastname="Go", raw_cv_text=f"Opis {tag}"
            ),
            "unrelated": Candidate(
                name="Jan", lastname=f"Other-{tag}", raw_cv_text="Python developer"
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        return {key: c.id for key, c in rows.items()}


async def _matching(q: str, ids: dict[str, int], *, short_whole_word: bool) -> set[str]:
    clause = literal_text_clause(q, short_whole_word=short_whole_word)
    assert clause is not None
    async with AsyncSessionLocal() as db:
        found = set(
            (
                await db.scalars(
                    select(Candidate.id).where(clause, Candidate.id.in_(ids.values()))
                )
            ).all()
        )
    return {key for key, cid in ids.items() if cid in found}


async def test_v2_short_text_is_a_whole_word_through_the_index():
    ids = await _people()
    with keyword_corpus.force_folded_search(True):
        assert await _matching("c#", ids, short_whole_word=True) == {"csharp_cv"}
        assert await _matching("go", ids, short_whole_word=True) == {"surname_go"}


def test_v2_short_text_does_not_scan_cv_with_ilike():
    with keyword_corpus.force_folded_search(True):
        sql = str(literal_text_clause("c#", short_whole_word=True))
    assert "keyword_fold_fts" in sql
    assert "raw_cv_text" not in sql


def test_v1_and_longer_text_keep_the_substring_path():
    with keyword_corpus.force_folded_search(True):
        v1 = str(literal_text_clause("c#", short_whole_word=False))
        longer = str(literal_text_clause("c#x", short_whole_word=True))
    assert "raw_cv_text" in v1
    assert "keyword_fold_fts" not in v1
    assert "keyword_fold_fts" not in longer


def test_without_the_folded_corpus_short_text_stays_substring():
    with keyword_corpus.force_folded_search(False):
        sql = str(literal_text_clause("c#", short_whole_word=True))
    assert "raw_cv_text" in sql
