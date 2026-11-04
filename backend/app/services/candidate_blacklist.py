"""Czarna lista „u nas” — kto, kiedy i dlaczego (okno „Czarna lista…”, 17.10.2026).

Do 17.10.2026 globalną czarną listę ustawiało pole „Status → Zablokowany”
w środku formularza „Edytuj dane”: bez powodu i bez śladu poza „Zaktualizowano
profil”. Pomiar produkcji 17.10: 37 osób zablokowanych (wszystkie z dopisków
Traffita w imieniu), ręcznie w NEXUSIE — raz; informacja o czarnej liście
żyła w notatkach. Teraz status zmienia się wyłącznie przez
``api/candidate_blacklist.py``, a kolumny ``blacklisted_*`` mówią, kto, kiedy
i dlaczego. Czarna lista „u klienta” to dalej wpis rejestru konfliktów
(ostrzeżenie, nie blokada — decyzja z 17.09.2026).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.user import User, UserRole
from app.schemas.candidate import CandidateBlacklistInfo

#: Powód: po przycięciu co najmniej tyle znaków (okno i serwer).
REASON_MIN_LENGTH = 5
REASON_MAX_LENGTH = 2000

#: Kto zdejmuje czarną listę „u nas” (decyzja Artura 17.10.2026). Dodaje każdy
#: z zapisem kandydata — także rekruter, który i wcześniej mógł ustawić status.
REMOVER_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


def blacklist_info(
    candidate: Any, by_name: Optional[str] = None
) -> Optional[CandidateBlacklistInfo]:
    """Projekcja dla odpowiedzi; ``None``, gdy osoba nie jest na liście."""
    if candidate.status != CandidateStatus.blacklisted:
        return None
    return CandidateBlacklistInfo(
        since=candidate.blacklisted_at,
        by_user_id=candidate.blacklisted_by_user_id,
        by_name=by_name,
        reason=candidate.blacklist_reason,
    )


async def load_blacklist_info(
    db: AsyncSession, candidate: Candidate
) -> Optional[CandidateBlacklistInfo]:
    """Jak :func:`blacklist_info`, z imieniem autora — jedno wąskie zapytanie."""
    if candidate.status != CandidateStatus.blacklisted:
        return None
    by_name = (
        await db.scalar(
            select(User.name).where(User.id == candidate.blacklisted_by_user_id)
        )
        if candidate.blacklisted_by_user_id is not None
        else None
    )
    return blacklist_info(candidate, by_name)


def mark_blacklisted(
    candidate: Candidate, *, user_id: int, reason: str, at: datetime
) -> None:
    candidate.status = CandidateStatus.blacklisted
    candidate.blacklisted_at = at
    candidate.blacklisted_by_user_id = user_id
    candidate.blacklist_reason = reason


def clear_blacklist(candidate: Candidate) -> None:
    """Zdjęcie z listy: status „aktywny”, kolumny puste — historia zostaje
    w aktywności ``candidate_blacklist_removed`` (z powodem dodania i zdjęcia)."""
    candidate.status = CandidateStatus.active
    candidate.blacklisted_at = None
    candidate.blacklisted_by_user_id = None
    candidate.blacklist_reason = None


__all__ = [
    "REASON_MAX_LENGTH",
    "REASON_MIN_LENGTH",
    "REMOVER_ROLES",
    "blacklist_info",
    "clear_blacklist",
    "load_blacklist_info",
    "mark_blacklisted",
]
