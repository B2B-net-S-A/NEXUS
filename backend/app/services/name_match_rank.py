"""Kolejność trafień po nazwie: dokładne pole, potem prefiks, potem reszta.

Wspólne dla `/api/search/global`, `/api/search/` (#3431) i
`GET /api/candidates?sort=relevance`, z którego paleta ⌘K bierze kandydatów
rekrutera. Bez tego progu „Kotow” dawało Kotowskich, Kotowiczów i Kotów przed
osobą o nazwisku dokładnie „Kotow” (staging, 14 i 16.11.2026).
"""

from typing import Any

from sqlalchemy import case, func, or_

from app.models.candidate import Candidate
from app.services.polish_ilike import escape_like, fold_polish_query, polish_folded


def match_rank(q: str, *, exact: list[Any], prefix: list[Any]) -> Any:
    """0 = całe pole równe frazie, 1 = pole zaczyna się od frazy, 2 = reszta.

    Pola porównujemy po foldzie polskich znaków, jak ``WHERE`` wyszukiwarki;
    ``ILIKE`` bez ``%`` to równość bez wielkości liter."""
    folded = escape_like(fold_polish_query(" ".join(q.split())))
    return case(
        (or_(*(polish_folded(e).ilike(folded, escape="\\") for e in exact)), 0),
        (or_(*(polish_folded(e).ilike(f"{folded}%", escape="\\") for e in prefix)), 1),
        else_=2,
    )


def candidate_name_rank(q: str) -> Any:
    """Nazwisko, imię z nazwiskiem (obie kolejności) i e-mail przed prefiksem."""
    first = func.coalesce(Candidate.name, "")
    last = func.coalesce(Candidate.lastname, "")
    first_last = first + " " + last
    last_first = last + " " + first
    return match_rank(
        q,
        exact=[last, first_last, last_first, func.coalesce(Candidate.email, "")],
        prefix=[last, first, first_last, last_first],
    )
