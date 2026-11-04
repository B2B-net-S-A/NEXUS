"""Lista osób dla Compassa (Akademia czyta ją z NEXUSA po przełączeniu).

Kierunek odwrotny niż przepływ 2 sprzed przełączenia (NEXUS ciągnął roster
Compassa i wyłączał konta ``exited``): po przeniesieniu kartoteki źródłem
prawdy o zatrudnieniu jest NEXUS, a Compass zostaje z Akademią.

CZEGO LISTA NIE ODDAJE: stawek, premii, nieobecności, powodu odejścia, formy
zatrudnienia ani telefonu. Akademia potrzebuje odpowiedzi „kto u nas pracuje,
komu podlega i od kiedy/do kiedy” — tylko tyle tu jest.

Osoby, które odeszły, ZOSTAJĄ na liście ze statusem ``exited`` (Compass
odbiera Akademię jawnym statusem, nie ciszą — brak osoby na liście nie jest
dowodem odejścia, ta sama zasada co w ``compass_lifecycle``). Pusta lista jest
awarią po naszej stronie (``RosterEmptyError``), nie stanem „wszyscy odeszli”.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import local_now
from app.models.hr_profile import EmployeeProfile
from app.models.user import User

#: Pola osoby w liście — kontrakt z odbiorcą w Compassie (bez kwot i nieobecności).
ROSTER_FIELDS: tuple[str, ...] = (
    "email",
    "name",
    "employment_status",
    "account_active",
    "manager_email",
    "department",
    "job_title",
    "work_start_date",
    "last_working_day",
    "exited_at",
)


class RosterEmptyError(RuntimeError):
    """Brak kartotek — odmowa eksportu (odbiorca wyłącza dostęp na tej liście)."""


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


async def roster_payload(db: AsyncSession) -> dict[str, Any]:
    manager = aliased(User)
    rows = (
        await db.execute(
            select(EmployeeProfile, User, manager.email)
            .join(User, User.id == EmployeeProfile.user_id)
            .outerjoin(manager, manager.id == EmployeeProfile.manager_user_id)
            .order_by(User.id)
        )
    ).all()
    people: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile, user, manager_email in rows:
        email = (user.email or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        people.append(
            {
                "email": email,
                "name": user.name,
                "employment_status": profile.employment_status,
                "account_active": bool(user.is_active),
                "manager_email": (manager_email or "").strip().lower() or None,
                "department": profile.department,
                "job_title": profile.job_title,
                "work_start_date": _iso(profile.work_start_date),
                "last_working_day": _iso(profile.last_working_day),
                "exited_at": _iso(profile.exited_at),
            }
        )
    if not people:
        raise RosterEmptyError("empty_roster")
    return {
        "count": len(people),
        "generated_at": local_now().isoformat(),
        "people": people,
    }
