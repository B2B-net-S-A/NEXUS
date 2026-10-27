"""Ile osób w bazie ma słowo wiersza wymagań — to samo zapytanie co „W bazie”.

Licznik w edytorze wierszy (`frontend/src/lib/requirement-rows-api.ts`,
`countPeople`) pyta `GET /api/candidates` o aktywnych i pasywnych, semantyka 2,
wiersz jako grupa `q_any_group`. Tu ten sam filtr idzie przez ten sam builder
listy (`_build_candidate_filtered_query`), więc serwer i ekran nie rozjadą się
przy zmianie wyszukiwania.

Liczymy tylko do progu (`LIMIT`): odczyt requestu potrzebuje odpowiedzi „czy
co najmniej 20 osób”, a pełna liczba popularnego słowa („Java”) to na kopii
produkcji ~20 s.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Lustro `CRITICAL_PEOPLE_MIN` z `frontend/src/lib/requirement-rows.ts`.
PEOPLE_MIN = 20


async def people_reach(
    db: AsyncSession, words: Sequence[str], *, cap: int = PEOPLE_MIN
) -> Optional[int]:
    """Liczba osób z którymkolwiek ze słów (najwyżej ``cap``).

    ``None``, gdy wiersza nie da się szukać (brak słów albo jednoliterowe
    słowo) — wtedy nie wiadomo nic, a nie „0 osób”.
    """
    from app.api.candidates import CandidateFilterSpec, _build_candidate_filtered_query
    from app.models.candidate import Candidate, CandidateStatus
    from app.services.keyword_terms import keyword_long_enough

    cleaned = [" ".join(word.replace("|", " ").split()) for word in words]
    # Builder odpowiada na jednoliterowe słowo 422 (`KeywordTooShort`).
    if not cleaned or not all(keyword_long_enough(word) for word in cleaned):
        return None
    spec = CandidateFilterSpec(
        status=[CandidateStatus.active, CandidateStatus.passive],
        q_any_group=["|".join(cleaned)],
        semantics_version=2,
    )
    query, _ = await _build_candidate_filtered_query(db, spec)
    capped = query.with_only_columns(Candidate.id).order_by(None).limit(cap).subquery()
    return int(await db.scalar(select(func.count()).select_from(capped)) or 0)
