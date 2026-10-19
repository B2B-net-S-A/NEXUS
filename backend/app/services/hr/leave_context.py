"""Kontekst wniosku: kto z działu też jest nieobecny, jaka praca w NEXUSIE
wypada w tym czasie i kogo zaproponować na zastępcę.

To ostrzeżenia, nie blokady — decyzję podejmuje człowiek. Nic tu nie
zdradza rodzaju cudzej nieobecności (D6): o kolegach z działu mówimy
„nieobecny w dniach …”.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr.people import DIRECTORY_STATUSES

#: Rodzaje wydarzeń, które ktoś musi przejąć, gdy osoba jest nieobecna.
WORK_EVENT_TYPES: tuple[EventType, ...] = (
    EventType.client_interview,
    EventType.prep_call,
    EventType.interview,
    EventType.screening,
)
WORK_EVENT_LABELS: dict[str, str] = {
    "client_interview": "Rozmowa u klienta",
    "prep_call": "Prep z kandydatem",
    "interview": "Rozmowa",
    "screening": "Screening",
}
_WORK_ITEMS_LIMIT = 8
_SUGGESTED = 3


async def busy_user_ids(
    db: AsyncSession,
    start: date,
    end: date,
    *,
    exclude_request_id: object | None = None,
    approved_only: bool = False,
) -> dict[int, tuple[date, date]]:
    """Osoby z aktywną nieobecnością w okresie → zakres jej dni w tym okresie.

    ``approved_only`` — tylko zatwierdzone (podgląd własnego wniosku: oczekujące
    cudze wnioski widzi tylko krąg D6, jak w kalendarzu zespołu).
    """

    statement = (
        select(
            LeaveRequestDay.user_id,
            func.min(LeaveRequestDay.day),
            func.max(LeaveRequestDay.day),
        )
        .where(
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day >= start,
            LeaveRequestDay.day <= end,
        )
        .group_by(LeaveRequestDay.user_id)
    )
    if exclude_request_id is not None:
        statement = statement.where(
            LeaveRequestDay.leave_request_id != exclude_request_id
        )
    if approved_only:
        statement = statement.join(
            LeaveRequest, LeaveRequest.id == LeaveRequestDay.leave_request_id
        ).where(LeaveRequest.status == "approved")
    rows = (await db.execute(statement)).all()
    return {user_id: (first, last) for user_id, first, last in rows}


async def department_absences(
    db: AsyncSession,
    *,
    user_id: int,
    department: Optional[str],
    start: date,
    end: date,
    approved_only: bool = False,
) -> list[dict[str, Any]]:
    if not department:
        return []
    busy = await busy_user_ids(db, start, end, approved_only=approved_only)
    busy.pop(user_id, None)
    if not busy:
        return []
    rows = (
        await db.execute(
            select(User.id, User.name)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(
                User.id.in_(busy),
                User.is_active.is_(True),
                EmployeeProfile.department == department,
                EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES),
            )
            .order_by(User.name)
        )
    ).all()
    return [
        {
            "user_id": uid,
            "name": name,
            "start_date": busy[uid][0].isoformat(),
            "end_date": busy[uid][1].isoformat(),
        }
        for uid, name in rows
    ]


async def work_in_period(
    db: AsyncSession,
    *,
    user_id: int,
    start: date,
    end: date,
    with_titles: bool = False,
) -> dict[str, Any]:
    """Zaplanowane rozmowy i prepy osoby w okresie (z kalendarza NEXUSA).

    Tytuły (``with_titles``) tylko dla samej osoby: niosą nazwiska kandydatów
    („Rozmowa u klienta: …”), a Kadry i przełożony nie muszą mieć dostępu do
    rekrutacji — im wystarczą liczby i rodzaje.
    """

    owner = func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by)
    window = (
        CalendarEvent.start_time >= local_day_start_utc(start),
        CalendarEvent.start_time < local_day_start_utc(end + timedelta(days=1)),
    )
    filters = (
        owner == user_id,
        CalendarEvent.status == EventStatus.scheduled,
        CalendarEvent.all_day.is_(False),
        CalendarEvent.event_type.in_(WORK_EVENT_TYPES),
        *window,
    )
    total = await db.scalar(select(func.count(CalendarEvent.id)).where(*filters))
    rows = (
        await db.execute(
            select(
                CalendarEvent.event_type,
                CalendarEvent.start_time,
                CalendarEvent.title,
            )
            .where(*filters)
            .order_by(CalendarEvent.start_time)
            .limit(_WORK_ITEMS_LIMIT)
        )
    ).all()
    by_kind: dict[str, int] = {}
    kind_rows = (
        await db.execute(
            select(CalendarEvent.event_type, func.count(CalendarEvent.id))
            .where(*filters)
            .group_by(CalendarEvent.event_type)
        )
    ).all()
    for event_type, count in kind_rows:
        by_kind[event_type.value] = int(count)
    return {
        "total": int(total or 0),
        "by_kind": [
            {"kind": kind, "label": WORK_EVENT_LABELS.get(kind, kind), "count": count}
            for kind, count in sorted(by_kind.items())
        ],
        "items": [
            {
                "kind": event_type.value,
                "label": WORK_EVENT_LABELS.get(event_type.value, event_type.value),
                "starts_at": start_time.isoformat(),
                "title": title if with_titles else None,
            }
            for event_type, start_time, title in rows
        ],
    }


@dataclass(frozen=True)
class RequestWindow:
    """Wiersz kolejki do kontekstu zbiorczego: osoba, jej dział i okres."""

    user_id: int
    department: Optional[str]
    start: date
    end: date


async def department_absences_many(
    db: AsyncSession, windows: Sequence[RequestWindow]
) -> list[list[dict[str, Any]]]:
    """``department_absences`` dla wielu wierszy kolejki naraz.

    Jedno zapytanie o aktywne dni w łącznym oknie wszystkich wierszy i jedno
    o osoby z tych działów; rozkład na wiersze w Pythonie (te same reguły:
    inni z działu, aktywne konto, status z katalogu, kolejność po nazwisku).
    """

    result: list[list[dict[str, Any]]] = [[] for _ in windows]
    wanted = [index for index, window in enumerate(windows) if window.department]
    if not wanted:
        return result
    first = min(windows[index].start for index in wanted)
    last = max(windows[index].end for index in wanted)
    days: dict[int, list[date]] = defaultdict(list)
    for user_id, day in (
        await db.execute(
            select(LeaveRequestDay.user_id, LeaveRequestDay.day).where(
                LeaveRequestDay.active.is_(True),
                LeaveRequestDay.day >= first,
                LeaveRequestDay.day <= last,
            )
        )
    ).all():
        days[int(user_id)].append(day)
    if not days:
        return result
    people = (
        await db.execute(
            select(User.id, User.name, EmployeeProfile.department)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(
                User.id.in_(sorted(days)),
                User.is_active.is_(True),
                EmployeeProfile.department.in_(
                    sorted({windows[index].department for index in wanted})
                ),
                EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES),
            )
            .order_by(User.name, User.id)
        )
    ).all()
    for index in wanted:
        window = windows[index]
        for user_id, name, department in people:
            if department != window.department or user_id == window.user_id:
                continue
            inside = [day for day in days[user_id] if window.start <= day <= window.end]
            if not inside:
                continue
            result[index].append(
                {
                    "user_id": user_id,
                    "name": name,
                    "start_date": min(inside).isoformat(),
                    "end_date": max(inside).isoformat(),
                }
            )
    return result


async def work_summaries(
    db: AsyncSession, windows: Sequence[RequestWindow]
) -> list[dict[str, Any]]:
    """Liczby z ``work_in_period`` (bez listy wydarzeń) dla wielu wierszy:
    jedno zapytanie o wydarzenia wszystkich osób w łącznym oknie."""

    empty = {"total": 0, "by_kind": []}
    if not windows:
        return []
    owner = func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by)
    first = local_day_start_utc(min(window.start for window in windows))
    last = local_day_start_utc(
        max(window.end for window in windows) + timedelta(days=1)
    )
    events: dict[int, list[tuple[str, Any]]] = defaultdict(list)
    for user_id, event_type, start_time in (
        await db.execute(
            select(owner, CalendarEvent.event_type, CalendarEvent.start_time).where(
                owner.in_(sorted({window.user_id for window in windows})),
                CalendarEvent.status == EventStatus.scheduled,
                CalendarEvent.all_day.is_(False),
                CalendarEvent.event_type.in_(WORK_EVENT_TYPES),
                CalendarEvent.start_time >= first,
                CalendarEvent.start_time < last,
            )
        )
    ).all():
        events[int(user_id)].append((event_type.value, start_time))
    result: list[dict[str, Any]] = []
    for window in windows:
        start = local_day_start_utc(window.start)
        end = local_day_start_utc(window.end + timedelta(days=1))
        kinds = Counter(
            kind
            for kind, moment in events.get(window.user_id, [])
            if start <= moment < end
        )
        if not kinds:
            result.append(dict(empty))
            continue
        result.append(
            {
                "total": sum(kinds.values()),
                "by_kind": [
                    {
                        "kind": kind,
                        "label": WORK_EVENT_LABELS.get(kind, kind),
                        "count": count,
                    }
                    for kind, count in sorted(kinds.items())
                ],
            }
        )
    return result


@dataclass(frozen=True)
class SubstituteCandidate:
    user_id: int
    name: str
    job_title: Optional[str]
    department: Optional[str]
    same_department: bool
    shared_role: bool
    suggested: bool


async def substitute_candidates(
    db: AsyncSession,
    *,
    subject: User,
    department: Optional[str],
    start: date,
    end: date,
) -> list[SubstituteCandidate]:
    """Aktywne osoby z kartoteką, w pracy przez cały okres; najpierw ten sam dział.

    Wyżej stoją osoby z tą samą rolą (reguła ``compatible_substitute`` silnika
    zastępstw). Pierwsze trzy oznaczamy jako propozycje — wybór należy do osoby.
    """

    busy = await busy_user_ids(db, start, end)
    rows = (
        await db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(
                User.is_active.is_(True),
                User.id != subject.id,
                EmployeeProfile.employment_status.in_(("active", "onboarding")),
                or_(
                    EmployeeProfile.last_working_day.is_(None),
                    EmployeeProfile.last_working_day >= end,
                ),
            )
            .order_by(User.name, User.id)
        )
    ).all()
    subject_roles = set(subject.get_all_roles())
    scored: list[tuple[int, str, SubstituteCandidate]] = []
    for user, profile in rows:
        if user.id in busy:
            continue
        same_department = bool(department) and profile.department == department
        shared_role = bool(subject_roles & set(user.get_all_roles()))
        score = (2 if same_department else 0) + (1 if shared_role else 0)
        scored.append(
            (
                -score,
                user.name or "",
                SubstituteCandidate(
                    user_id=user.id,
                    name=user.name,
                    job_title=profile.job_title,
                    department=profile.department,
                    same_department=same_department,
                    shared_role=shared_role,
                    suggested=False,
                ),
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]))
    result: list[SubstituteCandidate] = []
    for index, (negative_score, _, candidate) in enumerate(scored):
        suggested = index < _SUGGESTED and negative_score < 0
        result.append(replace(candidate, suggested=suggested))
    return result


def candidate_payload(candidate: SubstituteCandidate) -> dict[str, Any]:
    return asdict(candidate)


async def overlapping_request(
    db: AsyncSession, *, user_id: int, start: date, end: date
) -> Optional[LeaveRequest]:
    return await db.scalar(
        select(LeaveRequest)
        .where(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status.in_(("pending", "approved")),
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
        .order_by(LeaveRequest.start_date)
        .limit(1)
    )
