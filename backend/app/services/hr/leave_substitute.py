"""Zastępca nieobecnego przełożonego („Ludzie w NEXUSIE”, plan §4).

Przełożony na zatwierdzonym urlopie, który obejmuje cały dzisiejszy dzień
(kalendarz firmy), wskazał we wniosku zastępcę. Do końca tego urlopu zastępca:

* widzi wnioski urlopowe podwładnych przełożonego w „Akceptacjach” i decyduje
  o nich — o rodzajach planowych; L4 i pokrewne tylko przyjmuje do wiadomości
  (``leave_policy.SUBSTITUTE_VISIBLE_TYPES``),
* akceptuje ich timesheety (``time_access``),
* dostaje powiadomienie o nowym wniosku obok przełożonego.

Bez wniosku o pół dnia (przełożony jest wtedy w pracy przez część dnia) i bez
osobnego sprzątania: zakres kończy się sam z ostatnim dniem urlopu. Zastępca
nie decyduje o własnym wniosku ani o wniosku zastępowanego przełożonego —
zakres to wyłącznie jego podwładni.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest
from app.models.hr_profile import EmployeeProfile
from app.models.user import User


@dataclass(frozen=True)
class Cover:
    """Zastępstwo na dziś: kogo osoba zastępuje i do kiedy."""

    manager_user_id: int
    manager_name: str
    until: date


def _covering_today(today: date):
    return (
        LeaveRequest.status == "approved",
        LeaveRequest.half_day.is_(None),
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today,
    )


async def covers_of(db: AsyncSession, substitute_id: int, today: date) -> list[Cover]:
    """Przełożeni (aktywne konta), których ``substitute_id`` zastępuje dziś."""

    rows = await db.execute(
        select(LeaveRequest.user_id, User.name, LeaveRequest.end_date)
        .join(User, User.id == LeaveRequest.user_id)
        .where(
            LeaveRequest.substitute_user_id == substitute_id,
            LeaveRequest.user_id != substitute_id,
            User.is_active.is_(True),
            *_covering_today(today),
        )
        .order_by(LeaveRequest.end_date, LeaveRequest.user_id)
    )
    return [
        Cover(manager_user_id=user_id, manager_name=name or "", until=until)
        for user_id, name, until in rows.all()
    ]


async def covered_reports(
    db: AsyncSession, substitute_id: int, today: date
) -> dict[int, Cover]:
    """Podwładni przełożonych zastępowanych dziś przez osobę: id → zastępstwo.

    Bez osób, które odeszły, i bez samego zastępcy (o sobie nie decyduje).
    """

    covers = {c.manager_user_id: c for c in await covers_of(db, substitute_id, today)}
    if not covers:
        return {}
    rows = await db.execute(
        select(EmployeeProfile.user_id, EmployeeProfile.manager_user_id).where(
            EmployeeProfile.manager_user_id.in_(sorted(covers)),
            EmployeeProfile.employment_status != "exited",
            EmployeeProfile.user_id != substitute_id,
        )
    )
    return {user_id: covers[manager_id] for user_id, manager_id in rows.all()}


@dataclass(frozen=True)
class StandIn:
    """Zastępca przełożonego na dziś (do powiadomień o nowym wniosku)."""

    user_id: int
    manager_name: str


async def stand_in_for(
    db: AsyncSession, manager_id: Optional[int], today: date
) -> Optional[StandIn]:
    """Zastępca (aktywne konto) przełożonego, który jest dziś na urlopie."""

    if manager_id is None:
        return None
    row = (
        await db.execute(
            select(LeaveRequest.substitute_user_id, User.name)
            .join(User, User.id == LeaveRequest.user_id)
            .where(
                LeaveRequest.user_id == manager_id,
                LeaveRequest.substitute_user_id.is_not(None),
                *_covering_today(today),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    substitute_id, manager_name = row
    substitute = await db.get(User, substitute_id)
    if substitute is None or not substitute.is_active:
        return None
    return StandIn(user_id=substitute_id, manager_name=manager_name or "")


async def covering_payload(
    db: AsyncSession, user_id: int, today: date
) -> list[dict[str, Any]]:
    """Kogo osoba zastępuje dziś — do konfiguracji „Ludzi” i ekranu akceptacji."""

    covers = await covers_of(db, user_id, today)
    if not covers:
        return []
    reports = await covered_reports(db, user_id, today)
    counts: dict[int, int] = {}
    for cover in reports.values():
        counts[cover.manager_user_id] = counts.get(cover.manager_user_id, 0) + 1
    return [
        {
            "manager_user_id": cover.manager_user_id,
            "manager_name": cover.manager_name,
            "until": cover.until.isoformat(),
            "reports": counts.get(cover.manager_user_id, 0),
        }
        for cover in covers
    ]
