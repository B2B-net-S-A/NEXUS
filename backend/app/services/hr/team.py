"""„Ludzie → Mój zespół” (etap 2, D6, 17.10.2026): przełożony o swoich ludziach.

Jeden wiersz na bezpośredniego podwładnego (kartoteka, status ≠ ``exited``).
Ekran SKŁADA istniejące odczyty, nie liczy po swojemu:

* **dziś** — ``absence.absences_on`` (do kiedy, zastępca) + rodzaj z
  ``absence.month_absences``: przełożony należy do kręgu D6 (osoba, przełożony,
  Kadry, admin), więc rodzaj widzi; kto kogo dziś zastępuje — z tych samych
  nieobecności,
* **urlop i nieobecności** — saldo z ``leave_balance.balances_for`` (to samo,
  co osoba widzi w „Moim czasie”) tylko u osób z pulą; zaplanowane dni
  nieobecności (zatwierdzone po dziś i czekające) z ``leave_request_days`` —
  prawie wszyscy są na B2B albo zleceniu bez puli (decyzja Artura 17.10.2026),
* **bieżący miesiąc** — ``time_month.team_queue`` dla przełożonego (godziny,
  status timesheetu), norma jak w „Moim miesiącu” (dni robocze × 8 h),
* **premie w drodze** — ``payroll_bonuses.list_bonuses`` w zakresie przełożonego
  (propozycje i przyznane w otwartych miesiącach płac), ``bonus_payload`` BEZ
  ``rule_snapshot`` — przełożony widzi kwoty premii, nigdy stawek (D2),
* **do decyzji** — wnioski czekające i wysłane timesheety; propozycje premii
  tylko do wiadomości (decydują Płace — zasada „nikt nie przyznaje sobie”).
  Przełożony akceptuje i odrzuca je z ekranu tymi samymi trasami co
  „Akceptacje” (19.10.2026),
* **ten tydzień** (pn–pt, 19.10.2026) — stan dnia per osoba: w pracy,
  nieobecność, wniosek czeka, delegacja, zdalnie, dzień wolny firmy. Bez
  rodzaju nieobecności (D6): oczekujące tylko dla kręgu D6, praca zdalna
  i delegacja z ``leave_calendar.presence_between`` tylko przy module czasu.

Kadry i admin oglądają zespół dowolnego przełożonego (``?manager=``). Premie
widzi wtedy tylko osoba z Płacami albo sam przełożony — Kadry bez Płac nie
widzą kwot (``payroll_access``).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.models.user import User, UserRole
from app.services.hr import absence, leave_service, payroll_bonuses, people
from app.services.hr import modules as hr_modules
from app.services.hr.calendar import load_calendar
from app.services.hr.leave_balance import balances_for
from app.services.hr.leave_calendar import presence_between
from app.services.hr.leave_policy import actor_of, can_see_type, type_label
from app.services.hr.payroll_access import PayrollViewer, is_payroll
from app.services.hr.payroll_periods import closed_months
from app.services.hr.time_access import Actor
from app.services.hr.time_calendar import month_calendar, submission_deadline
from app.services.hr.time_entries import STANDARD
from app.services.hr.time_flow import approvals_link
from app.services.hr.time_month import team_queue

#: Premie „w drodze” — jeszcze nie wypłacone (miesiąc płac otwarty).
BONUS_IN_FLIGHT = ("proposed", "assigned")

#: Stan dnia w mini-tygodniu (pn–pt) — bez rodzaju nieobecności (D6).
#: ``unknown`` — urlopy zamknięte dla patrzącego: nieobecności nie są czytane,
#: więc dzień bez wpisu obecności nie jest „w pracy” (audyt 21.10.2026).
WEEK_STATES = ("work", "off", "absent", "pending", "business_trip", "remote", "unknown")


def day_state(
    *,
    working_day: bool,
    approved: Any,
    waiting: Any,
    presence: Optional[str],
    absences_known: bool,
) -> tuple[str, Optional[str]]:
    """Stan dnia i pół dnia. Pierwszeństwo: dzień wolny firmy, nieobecność,
    wniosek czeka, delegacja/zdalnie, w pracy — „w pracy” tylko, gdy
    nieobecności są znane (moduł urlopów otwarty dla patrzącego)."""

    if not working_day:
        return "off", None
    if approved is not None:
        return "absent", approved.half_day
    if waiting is not None:
        return "pending", waiting.half_day
    if presence is not None:
        return presence, None
    return ("work" if absences_known else "unknown"), None


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _num(value: Decimal) -> str:
    return f"{value:.1f}"


async def reports_of(
    db: AsyncSession, manager_id: int
) -> list[tuple[EmployeeProfile, User]]:
    """Podwładni jak ``people.direct_report_ids``: przełożony, który odszedł
    albo ma wyłączone konto, nie ma zespołu (także w podglądzie Kadr)."""

    if not await people.can_supervise(db, manager_id):
        return []
    rows = await db.execute(
        select(EmployeeProfile, User)
        .join(User, User.id == EmployeeProfile.user_id)
        .where(
            EmployeeProfile.manager_user_id == manager_id,
            EmployeeProfile.employment_status != "exited",
        )
        .order_by(User.name, User.id)
    )
    return [(profile, user) for profile, user in rows.all()]


async def managers(db: AsyncSession) -> list[dict[str, Any]]:
    """Przełożeni z liczbą podwładnych (wybór zespołu dla Kadr i admina).

    Bez tych, którzy odeszli albo mają wyłączone konto (``people.can_supervise``)
    — ich ludzi Kadry przepinają w „Strukturze”.
    """

    manager_profile = aliased(EmployeeProfile)
    rows = await db.execute(
        select(User.id, User.name, func.count(EmployeeProfile.id))
        .join(EmployeeProfile, EmployeeProfile.manager_user_id == User.id)
        .outerjoin(manager_profile, manager_profile.user_id == User.id)
        .where(
            EmployeeProfile.employment_status != "exited",
            User.is_active.is_(True),
            or_(
                manager_profile.id.is_(None),
                manager_profile.employment_status != "exited",
            ),
        )
        .group_by(User.id, User.name)
        .order_by(User.name, User.id)
    )
    return [
        {"user_id": user_id, "name": name, "reports": int(count)}
        for user_id, name, count in rows.all()
    ]


async def _today(
    db: AsyncSession,
    ids: list[int],
    today: date,
    forms: Optional[dict[int, str]] = None,
) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]]]:
    """Nieobecni dziś (z rodzajem — krąg D6) i kogo kto dziś zastępuje.

    Rodzaj w słowach formy (D4): na B2B „Przerwa w świadczeniu usług”.
    """

    forms = forms or {}
    found = await absence.absences_on(db, ids, today)
    types = {
        item.user_id: item.leave_type
        for item in await absence.month_absences(db, ids, today, today)
        if item.status == "approved" and item.start <= today <= item.end
    }
    absent = {
        user_id: {
            "absent": True,
            "until": item.until.isoformat(),
            "half_day": item.half_day,
            "leave_type": types.get(user_id),
            "leave_type_label": type_label(types.get(user_id), forms.get(user_id))
            if types.get(user_id)
            else "Nieobecność",
            "substitute_name": item.substitute_name,
        }
        for user_id, item in found.items()
    }
    covering: dict[int, list[str]] = defaultdict(list)
    everyone_absent = await absence.absent_on(db, today)
    if everyone_absent:
        names = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(
                        User.id.in_([item.user_id for item in everyone_absent])
                    )
                )
            ).all()
        )
        for item in everyone_absent:
            if item.substitute_user_id in ids and item.user_id in names:
                covering[item.substitute_user_id].append(names[item.user_id])
    return absent, covering


async def _upcoming_absence_days(
    db: AsyncSession, ids: list[int], today: date
) -> dict[int, dict[str, Decimal]]:
    """Dni nieobecności w tym roku po dziś: zatwierdzone i czekające.

    Te same aktywne wiersze ``leave_request_days`` co saldo, ale bez podziału
    na pulę — osoba na B2B albo zleceniu bez puli też planuje nieobecności.
    """

    rows = await db.execute(
        select(
            LeaveRequestDay.user_id,
            LeaveRequest.status,
            func.sum(LeaveRequestDay.fraction),
        )
        .join(LeaveRequest, LeaveRequest.id == LeaveRequestDay.leave_request_id)
        .where(
            LeaveRequestDay.user_id.in_(ids),
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day > today,
            extract("year", LeaveRequestDay.day) == today.year,
            LeaveRequest.status.in_(("approved", "pending")),
        )
        .group_by(LeaveRequestDay.user_id, LeaveRequest.status)
    )
    result: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"approved": Decimal("0"), "pending": Decimal("0")}
    )
    for user_id, status, total in rows.all():
        result[int(user_id)][status] = Decimal(total or 0)
    return result


async def _week(
    db: AsyncSession,
    viewer: User,
    pairs: list[tuple[EmployeeProfile, User]],
    today: date,
    *,
    with_absences: bool,
    with_presence: bool,
) -> tuple[list[dict[str, str]], dict[int, list[dict[str, Any]]]]:
    """Mini-tydzień pn–pt tygodnia z dziś: stan dnia per osoba.

    Nieobecność bez rodzaju (D6 — mini-tydzień mówi „nieobecność”, nawet gdy
    patrzący jest w kręgu); wniosek oczekujący tylko dla kręgu D6, jak
    w kalendarzu zespołu. Pierwszeństwo: dzień wolny firmy, nieobecność,
    wniosek czeka, delegacja, zdalnie, w pracy (``day_state``); bez modułu
    urlopów zamiast „w pracy” — ``unknown``.
    """

    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=offset) for offset in range(5)]
    calendar = await load_calendar(db, days[0], days[-1])
    ids = [profile.user_id for profile, _ in pairs]
    actor = actor_of(viewer)
    in_d6 = {
        profile.user_id
        for profile, _ in pairs
        if can_see_type(
            actor,
            subject_user_id=profile.user_id,
            subject_manager_id=profile.manager_user_id,
        )
    }
    absences = (
        await absence.month_absences(db, ids, days[0], days[-1], pending_for=in_d6)
        if with_absences
        else []
    )
    presence = (
        await presence_between(db, ids, days[0], days[-1]) if with_presence else {}
    )
    result: dict[int, list[dict[str, Any]]] = {}
    for user_id in ids:
        own = [item for item in absences if item.user_id == user_id]
        marks = {item["date"]: item["kind"] for item in presence.get(user_id, [])}
        row: list[dict[str, Any]] = []
        for day in days:
            covering = [item for item in own if item.start <= day <= item.end]
            state, half_day = day_state(
                working_day=calendar.is_working_day(day),
                approved=next((a for a in covering if a.status == "approved"), None),
                waiting=next((a for a in covering if a.status == "pending"), None),
                presence=marks.get(day.isoformat()),
                absences_known=with_absences,
            )
            row.append({"date": day.isoformat(), "state": state, "half_day": half_day})
        result[user_id] = row
    week_days = [{"date": day.isoformat(), "kind": calendar.kind(day)} for day in days]
    return week_days, result


async def _leave(
    db: AsyncSession, pairs: list[tuple[EmployeeProfile, User]], today: date
) -> dict[int, dict[str, Any]]:
    ids = [profile.user_id for profile, _ in pairs]
    upcoming = await _upcoming_absence_days(db, ids, today)
    # Saldo całego zespołu dwoma zapytaniami (te same liczby co „Mój czas”).
    balances = await balances_for(
        db,
        {profile.user_id: profile.employment_type for profile, _ in pairs},
        year=today.year,
        today=today,
    )
    result: dict[int, dict[str, Any]] = {}
    for profile, _ in pairs:
        balance = balances[profile.user_id]
        planned = upcoming.get(profile.user_id) or {
            "approved": Decimal("0"),
            "pending": Decimal("0"),
        }
        result[profile.user_id] = {
            "has_pool": bool(balance["has_pool"]),
            # Pula > 0 — to samo znaczenie co w `GET /api/hr/leave/balance`
            # (pula zerowa = dni bez wynagrodzenia); front decyduje po nim.
            "has_paid_pool": bool(balance["has_paid_pool"]),
            "remaining_days": balance["remaining_days"]
            if balance["has_pool"]
            else None,
            "planned_days": _num(planned["approved"]),
            "pending_days": _num(planned["pending"]),
        }
    return result


async def _month(
    db: AsyncSession, manager: User, ids: list[int], today: date
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    # Aktor = sam przełożony (bez praw Kadr i zastępstw): kolejka to dokładnie
    # jego zespół, nawet gdy ogląda Kadry albo przełożony sam ma Kadry.
    actor = Actor(
        user=manager,
        profile=None,
        is_admin=False,
        people_admin=False,
        payroll=False,
        report_ids=frozenset(ids),
    )
    queue = await team_queue(
        db, actor=actor, year=today.year, month=today.month, missing_before=today
    )
    working_days = sum(
        1
        for day in await month_calendar(db, today.year, today.month)
        if day.is_working_day
    )
    month = {
        "year": today.year,
        "month": today.month,
        "norm_hours": working_days * int(STANDARD),
        "deadline": submission_deadline(today.year, today.month).isoformat(),
    }
    rows = {
        item["user_id"]: {
            "hours": item["hours"],
            "status": item["status"],
            "timesheet_id": item["timesheet"]["id"] if item["timesheet"] else None,
            # Dni robocze przed dziś bez wpisu (szkic albo brak raportu) —
            # znacznik „brak dd.mm” w „Moim zespole” (22.10.2026).
            "missing_dates": item.get("missing_dates", []),
        }
        for item in queue
        if item["user_id"] in set(ids)
    }
    return month, rows


async def _bonuses(
    db: AsyncSession, manager: User, ids: list[int], today: date
) -> dict[int, dict[str, Any]]:
    viewer = PayrollViewer(
        user_id=manager.id, payroll=False, admin=False, report_ids=frozenset(ids)
    )
    bonuses = [
        bonus
        for bonus in await payroll_bonuses.list_bonuses(db, viewer, limit=500)
        if bonus.recipient_user_id in set(ids) and bonus.status in BONUS_IN_FLIGHT
    ]
    closed = await closed_months(
        db, sorted({(b.period_year, b.period_month) for b in bonuses})
    )
    bonuses = [b for b in bonuses if (b.period_year, b.period_month) not in closed]
    names = await payroll_bonuses.names_for(db, bonuses)
    result: dict[int, dict[str, Any]] = {}
    for user_id in ids:
        own = [b for b in bonuses if b.recipient_user_id == user_id]
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for bonus in own:
            totals[bonus.currency] += Decimal(bonus.amount)
        result[user_id] = {
            "count": len(own),
            "proposals": sum(1 for b in own if b.status == "proposed"),
            "totals": [
                {"currency": currency, "amount": f"{totals[currency]:.2f}"}
                for currency in sorted(totals)
            ],
            # Bez `rule_snapshot` — w nim są marża i stawki (D2).
            "items": [
                payroll_bonuses.bonus_payload(
                    b, names, with_snapshot=False, today=today
                )
                for b in own
            ],
        }
    return result


async def _to_decide(
    db: AsyncSession, viewer: User, ids: list[int], today: date
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    requests = list(
        await db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.user_id.in_(ids), LeaveRequest.status == "pending")
            .order_by(LeaveRequest.start_date)
        )
    )
    leave_items: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in await leave_service.serialize(db, requests, viewer=viewer, today=today):
        leave_items[item["user_id"]].append(
            {
                "id": item["id"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
                "half_day": item["half_day"],
                "leave_type_label": item["leave_type_label"],
                "days_total": item["days_total"],
                "created_at": item["created_at"],
            }
        )
    timesheets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for timesheet in await db.scalars(
        select(Timesheet)
        .where(
            Timesheet.user_id.in_(ids),
            Timesheet.status == "submitted",
            Timesheet.payroll_locked.is_(False),
        )
        .order_by(Timesheet.year, Timesheet.month)
    ):
        timesheets[timesheet.user_id].append(
            {
                "id": timesheet.id,
                "year": timesheet.year,
                "month": timesheet.month,
                "submitted_at": timesheet.submitted_at.isoformat()
                if timesheet.submitted_at
                else None,
                "link": approvals_link(
                    timesheet.year, timesheet.month, timesheet.user_id
                ),
            }
        )
    return leave_items, timesheets


def sees_bonuses_of(viewer: User, manager: User) -> bool:
    """Kwoty premii zespołu: sam przełożony albo Płace (admin ma Płace)."""

    return viewer.id == manager.id or is_payroll(viewer)


async def team_view(
    db: AsyncSession, *, viewer: User, manager: User, today: date
) -> dict[str, Any]:
    loaded = await hr_modules.load_modules(db)

    def is_open(key: str) -> bool:
        return hr_modules.module_open_for(viewer, loaded, key)

    pairs = await reports_of(db, manager.id)
    ids = [profile.user_id for profile, _ in pairs]
    show_bonuses = is_open("payroll") and sees_bonuses_of(viewer, manager)

    absent: dict[int, dict[str, Any]] = {}
    covering: dict[int, list[str]] = {}
    leave: dict[int, dict[str, Any]] = {}
    leave_items: dict[int, list[dict[str, Any]]] = {}
    if is_open("leave") and ids:
        absent, covering = await _today(
            db,
            ids,
            today,
            {profile.user_id: profile.employment_type for profile, _ in pairs},
        )
        leave = await _leave(db, pairs, today)
    month: Optional[dict[str, Any]] = None
    month_rows: dict[int, dict[str, Any]] = {}
    if is_open("time"):
        month, month_rows = await _month(db, manager, ids, today)
    bonuses: dict[int, dict[str, Any]] = {}
    if show_bonuses and ids:
        bonuses = await _bonuses(db, manager, ids, today)
    leave_items, timesheets = (
        await _to_decide(db, viewer, ids, today) if ids else ({}, {})
    )
    if not is_open("leave"):
        leave_items = {}
    week_days: Optional[list[dict[str, str]]] = None
    week: dict[int, list[dict[str, Any]]] = {}
    if (is_open("leave") or is_open("time")) and ids:
        week_days, week = await _week(
            db,
            viewer,
            pairs,
            today,
            with_absences=is_open("leave"),
            with_presence=is_open("time"),
        )
    if not is_open("time"):
        timesheets = {}

    # Forma umowy: przełożony swoich ludzi, admin i Finanse — Kadry oglądające
    # cudzy zespół jej nie dostają (``people.form_viewer``, 19.10.2026).
    form = await people.form_viewer(db, viewer)
    people_rows: list[dict[str, Any]] = []
    for profile, user in pairs:
        shown = people.form_payload(profile, form)
        people_rows.append(
            {
                "user_id": user.id,
                "name": user.name,
                "job_title": profile.job_title,
                "employment_type": shown["employment_type"],
                "employment_type_pending": shown["employment_type_pending"],
                "employment_status": profile.employment_status,
                # Uczeń/student na zleceniu (D8): sam znacznik — daty zwolnienia
                # ze składek widzą osoba i Płace (przegląd 17.10.2026).
                "student": shown.get("student_contribution_exempt"),
                "last_working_day": profile.last_working_day.isoformat()
                if profile.last_working_day
                else None,
                "today": absent.get(user.id, {"absent": False})
                if is_open("leave")
                else None,
                "covering_for": covering.get(user.id, []),
                "week": week.get(user.id) if week_days is not None else None,
                "leave": leave.get(user.id),
                "month": month_rows.get(user.id) if month is not None else None,
                "timesheet_required": profile.timesheet_required,
                "bonuses": bonuses.get(user.id) if show_bonuses else None,
                "to_decide": {
                    "leave_requests": leave_items.get(user.id, []),
                    "timesheets": timesheets.get(user.id, []),
                },
            }
        )
    return {
        "manager": {"user_id": manager.id, "name": manager.name},
        "is_own": viewer.id == manager.id,
        "today": today.isoformat(),
        "modules": {
            "leave": is_open("leave"),
            "time": is_open("time"),
            "payroll": is_open("payroll"),
        },
        "sees_bonuses": show_bonuses,
        "month": month,
        "week": {"days": week_days} if week_days is not None else None,
        "people": people_rows,
        "stats": {
            "people": len(people_rows),
            "absent_today": sum(
                1 for row in people_rows if row["today"] and row["today"]["absent"]
            ),
            "leave_requests": sum(
                len(row["to_decide"]["leave_requests"]) for row in people_rows
            ),
            "timesheets": sum(
                len(row["to_decide"]["timesheets"]) for row in people_rows
            ),
            "bonus_proposals": sum(
                row["bonuses"]["proposals"] for row in people_rows if row["bonuses"]
            )
            if show_bonuses
            else None,
        },
    }


def can_view_any_team(user: User) -> bool:
    return user.has_role(UserRole.admin) or people.is_people_admin(user)


__all__ = [
    "BONUS_IN_FLIGHT",
    "WEEK_STATES",
    "can_view_any_team",
    "day_state",
    "managers",
    "reports_of",
    "sees_bonuses_of",
    "team_view",
]
