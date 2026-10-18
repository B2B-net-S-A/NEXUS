"""Oświadczenie o statusie ucznia/studenta zasila kartotekę (etap 5, E4).

Przypomnienie dla Płac o końcu zwolnienia ze składek już istnieje
(``student_reminders``, etap 2, D8) i liczy się od kartoteki:
``student_contribution_exempt`` + ``contribution_exempt_until``. E-teczka nie
dokłada drugiego przypomnienia — „ważny do” oświadczenia wpisuje się w tę datę
przez zwykły zapis kartoteki (``people.update_profile``: reguły formy, ślad
``profile_updated``), a przypomnienie przychodzi 30 dni wcześniej samo.

Reguła daty (Kadry wpisują wcześniejszą z dwóch: koniec statusu albo dzień
przed 26. urodzinami — NEXUS nie zna daty urodzenia):

* zwolnienie dotyczy tylko zlecenia — inna forma: kartoteka bez zmian
  (``not_zlecenie``),
* oświadczenie już nieważne (data w przeszłości): bez zmian (``past``),
* w kartotece brak daty albo data pochodzi z poprzedniego oświadczenia:
  nowa data (``updated``) — przedłużenie legitymacji przesuwa przypomnienie,
* w kartotece jest wcześniejsza data wpisana ręcznie (np. dzień przed
  26. urodzinami): zostaje (``kept_earlier``) — oświadczenie jej nie przesunie.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_document import HrDocument
from app.models.user import User
from app.services.hr import people
from app.services.hr_foundation_schema import EmploymentType

PURPOSE = "student_status"


async def latest_until(
    db: AsyncSession, user_id: int, *, exclude_id: Optional[int] = None
) -> Optional[date]:
    """„Ważny do” najnowszego żywego oświadczenia osoby (przed zapisem nowego)."""

    query = (
        select(HrDocument.valid_until)
        .where(
            HrDocument.user_id == user_id,
            HrDocument.purpose == PURPOSE,
            HrDocument.deleted_at.is_(None),
        )
        .order_by(HrDocument.created_at.desc(), HrDocument.id.desc())
        .limit(1)
    )
    if exclude_id is not None:
        query = query.where(HrDocument.id != exclude_id)
    return await db.scalar(query)


async def latest_document_id(db: AsyncSession, user_id: int) -> Optional[int]:
    """Najnowsze żywe oświadczenie osoby — tylko ono zasila kartotekę przy zmianie daty."""

    return await db.scalar(
        select(HrDocument.id)
        .where(
            HrDocument.user_id == user_id,
            HrDocument.purpose == PURPOSE,
            HrDocument.deleted_at.is_(None),
        )
        .order_by(HrDocument.created_at.desc(), HrDocument.id.desc())
        .limit(1)
    )


async def sync(
    db: AsyncSession,
    *,
    user_id: int,
    until: date,
    came_from: Optional[date],
    actor: User,
) -> dict[str, Any]:
    """Wpisuje datę oświadczenia w kartotekę według reguły z docstringu modułu.

    ``came_from`` — data, którą wpisało wcześniej oświadczenie (poprzednie
    oświadczenie albo stara data tego samego); równa dacie w kartotece znaczy,
    że kartoteka ją dostała z dokumentu i może się przesunąć.
    """

    profile = await people.profile_of(db, user_id)
    if profile is None:
        return {"status": "no_profile", "until": None}
    if profile.employment_type != EmploymentType.zlecenie:
        return {"status": "not_zlecenie", "until": None}
    if until < business_today():
        return {"status": "past", "until": None}
    current = (
        profile.contribution_exempt_until
        if profile.student_contribution_exempt
        else None
    )
    if current is not None and current != came_from and current < until:
        return {"status": "kept_earlier", "until": current}
    await people.update_profile(
        db,
        user_id=user_id,
        values={
            "student_contribution_exempt": True,
            "contribution_exempt_until": until,
        },
        actor=actor,
    )
    return {"status": "updated", "until": until}


__all__ = ["PURPOSE", "latest_document_id", "latest_until", "sync"]
