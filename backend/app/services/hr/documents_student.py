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

Usunięcie oświadczenia jako pomyłki (``documents.remove``, 19.10.2026) cofa
to, co ono wpisało (``unsync``): gdy data w kartotece równa się jego „ważny
do”, wraca data najnowszego pozostałego, jeszcze ważnego oświadczenia
(``restored``), a bez takiego zwolnienie znika (``cleared``) — inaczej Płace
nie naliczyłyby składek osobie, która nie ma już podstawy zwolnienia. Data
wpisana ręcznie (inna niż dokumentu) zostaje (``kept``). Usunięcie po
terminie przechowywania (retencja) kartoteki nie rusza — po latach od
odejścia data nic już nie zmienia.
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


async def _remaining_until(db: AsyncSession, user_id: int) -> Optional[date]:
    """„Ważny do” najnowszego żywego oświadczenia, które jeszcze obowiązuje."""

    return await db.scalar(
        select(HrDocument.valid_until)
        .where(
            HrDocument.user_id == user_id,
            HrDocument.purpose == PURPOSE,
            HrDocument.deleted_at.is_(None),
            HrDocument.valid_until >= business_today(),
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


def after_removal(
    *,
    exempt: bool,
    current_until: Optional[date],
    removed_until: Optional[date],
    remaining_until: Optional[date],
) -> tuple[str, Optional[dict[str, Any]]]:
    """Co zapisać w kartotece po usunięciu oświadczenia: (status, pola albo ``None``).

    Data w kartotece różna od „ważny do” usuniętego dokumentu nie pochodzi
    z niego (wpisały ją Kadry albo inne oświadczenie) — zostaje.
    """

    if not exempt or current_until is None or current_until != removed_until:
        return "kept", None
    if remaining_until is not None:
        return "restored", {"contribution_exempt_until": remaining_until}
    return "cleared", {
        "student_contribution_exempt": False,
        "contribution_exempt_until": None,
    }


async def unsync(
    db: AsyncSession, *, document: HrDocument, actor: User
) -> dict[str, Any]:
    """Cofa datę zwolnienia, którą wpisało usunięte oświadczenie (po ``mark_deleted``)."""

    profile = await people.profile_of(db, document.user_id)
    if profile is None:
        return {"status": "no_profile", "until": None}
    if profile.employment_type != EmploymentType.zlecenie:
        return {"status": "not_zlecenie", "until": None}
    status, values = after_removal(
        exempt=profile.student_contribution_exempt,
        current_until=profile.contribution_exempt_until,
        removed_until=document.valid_until,
        remaining_until=await _remaining_until(db, document.user_id),
    )
    if values is None:
        return {"status": status, "until": profile.contribution_exempt_until}
    await people.update_profile(
        db, user_id=document.user_id, values=values, actor=actor
    )
    return {"status": status, "until": values["contribution_exempt_until"]}


__all__ = [
    "PURPOSE",
    "after_removal",
    "latest_document_id",
    "latest_until",
    "sync",
    "unsync",
]
