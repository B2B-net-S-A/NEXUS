"""Jedno dopasowanie rozmowy CloudTalk do kandydata — webhook i backfill (INT-01).

Dopasowanie idzie po ostatnich 9 cyfrach telefonu. Do 09.2026 webhook
odmawiał zgadywania przy kilku trafieniach (F-12), a backfill w
``tasks/cloudtalk_sync.py`` brał pierwszego z brzegu (``LIMIT 1``) — nagranie
i transkrypt jednej osoby lądowały na profilu innej. Obie ścieżki czytają teraz
tę funkcję: dokładnie jedno trafienie → kandydat, zero albo kilka → brak.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from app.models.candidate import Candidate
from app.services.dedup_service import _normalize_phone


@dataclass(frozen=True)
class CallCandidateMatch:
    last9: str | None
    candidate_ids: tuple[int, ...]

    @property
    def candidate_id(self) -> int | None:
        return self.candidate_ids[0] if len(self.candidate_ids) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidate_ids) > 1


async def match_call_candidate(db, phone: str | None) -> CallCandidateMatch:
    """Kandydaci o tych samych 9 końcowych cyfrach (najwyżej 2 — więcej nie trzeba)."""
    last9 = _normalize_phone(phone or "")
    if not last9:
        return CallCandidateMatch(last9=None, candidate_ids=())
    normalized_col = func.right(
        func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
    )
    ids = (
        await db.scalars(
            select(Candidate.id)
            .where(Candidate.phone.isnot(None))
            .where(normalized_col == last9)
            .order_by(Candidate.id)
            .limit(2)
        )
    ).all()
    return CallCandidateMatch(last9=last9, candidate_ids=tuple(ids))
