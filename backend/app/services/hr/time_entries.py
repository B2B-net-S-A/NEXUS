"""Timesheet i jego wpisy: limity dnia, nadgodziny, urlop, blokada płac.

Reguły (Compass, faza 27a/45 + audyt 22.09) i naprawy:

* limit dnia 8 h liczony na SUMĘ wpisów dnia; ponad 8 h (do 16 h) to
  nadgodziny — tylko z prawem (``can_log_overtime`` z kartoteki albo
  Kadry/admin) i z uzasadnieniem ≥ 5 znaków,
* nadgodziną jest wpis, który przekracza 8 h SUMY dnia (w Compassie flagę
  liczono z godzin jednego wpisu, więc 5 h + 5 h przechodziło bez
  uzasadnienia),
* suma liczona pod blokadą wiersza timesheetu (``SELECT … FOR UPDATE``) —
  w Compassie dwa równoległe zapisy przechodziły kontrolę razem,
* pełny dzień urlopu (także oczekującego) blokuje wpis, pół dnia zajmuje 4 h;
  płatny dzień puli B2B to auto-wpis ``leave_paid`` („Praca
  standardowa”), którego nie edytuje się ręcznie,
* ``payroll_locked`` (zamknięty miesiąc płac) blokuje każdą zmianę — 409.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr import time_leave_bridge as bridge
from app.services.hr import time_retention
from app.services.hr.employment_terms import capitalize, terms
from app.services.hr.time_access import Actor
from app.services.hr.time_calendar import month_range
from app.services.hr.time_hash import HashEntry, compute_timesheet_hash
from app.services.hr_time_schema import (
    OVERTIME_MAX_HOURS,
    OVERTIME_REASON_MIN_LENGTH,
    STANDARD_DAY_HOURS,
)

STANDARD = Decimal(STANDARD_DAY_HOURS)
OVERTIME_MAX = Decimal(OVERTIME_MAX_HOURS)
MAX_DESCRIPTION = 2000
MAX_PROJECT = 200
MAX_OVERTIME_REASON = 1000

LOCKED_DETAIL = (
    "Ten miesiąc jest zamknięty w płacach — zmiany wymagają ponownego otwarcia "
    "miesiąca przez Płace."
)
CHANGED_DETAIL = "Timesheet zmienił się w międzyczasie. Odśwież widok."


def standard_description(employment_type: Optional[str]) -> str:
    """Opis auto-wpisu płatnej puli i domyślny opis „Wypełnij miesiąc”.

    Na karcie dzień puli wygląda jak dzień pracy (decyzja Compassa z
    03.06.2026). Słowo z formy: B2B i zlecenie „Realizacja usług zgodnie
    z umową”, UoP „Praca standardowa” (decyzja Artura 28.10.2026).
    """

    return terms(employment_type)["standard_description"]


class TimeError(Exception):
    """Błąd z komunikatem dla użytkownika (po polsku) i kodem HTTP."""

    status_code = 422

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class TimeConflict(TimeError):
    status_code = 409


class TimeForbidden(TimeError):
    status_code = 403


class TimeNotFound(TimeError):
    status_code = 404


# ── Timesheet ─────────────────────────────────────────────────────────────────


async def find_timesheet(
    db: AsyncSession, user_id: int, year: int, month: int
) -> Optional[Timesheet]:
    return await db.scalar(
        select(Timesheet).where(
            Timesheet.user_id == user_id,
            Timesheet.year == year,
            Timesheet.month == month,
        )
    )


async def ensure_timesheet(
    db: AsyncSession, user_id: int, year: int, month: int
) -> Timesheet:
    """Timesheet osoby za miesiąc; brak = nowy szkic (wyścig rozstrzyga UNIQUE)."""

    validate_period(year, month)
    # Miesiąc już zamknięty w płacach: nowy timesheet od razu zablokowany —
    # inaczej godziny wpisane po zamknięciu ominęłyby zamrożone linie płac.
    from app.services.hr import payroll_periods

    locked = await payroll_periods.is_closed(db, year, month)
    await db.execute(
        insert(Timesheet)
        .values(user_id=user_id, year=year, month=month, payroll_locked=locked)
        .on_conflict_do_nothing(constraint="uq_timesheets_user_period")
    )
    timesheet = await find_timesheet(db, user_id, year, month)
    assert timesheet is not None
    return timesheet


async def open_draft(
    db: AsyncSession,
    user_id: int,
    year: int,
    month: int,
    *,
    employment_type: Optional[str],
) -> Timesheet:
    """Timesheet pod blokadą na czas zapisu; brak = nowy szkic z auto-wpisami.

    Wiersz timesheetu powstaje przy pierwszym ZAPISIE miesiąca (wpis,
    „Wypełnij miesiąc”, kopia, wysyłka) albo w hakach urlopu — nie przy
    odczycie (``time_month.month_view`` pokazuje szkic bez zapisu). Szkic
    poza zamkniętym miesiącem płac dostaje przy tym auto-wpisy płatnej puli
    kontraktora (``sync_leave_paid``), tak jak dotąd przy otwarciu miesiąca.
    """

    found = await ensure_timesheet(db, user_id, year, month)
    timesheet = await lock_timesheet(db, found.id)
    if timesheet.status == "draft" and not timesheet.payroll_locked:
        await sync_leave_paid(db, timesheet=timesheet, employment_type=employment_type)
    return timesheet


async def lock_timesheet(db: AsyncSession, timesheet_id: int) -> Timesheet:
    """Blokada wiersza na czas zapisu — suma dnia i przejścia liczone atomowo."""

    timesheet = await db.scalar(
        select(Timesheet)
        .where(Timesheet.id == timesheet_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if timesheet is None:
        raise TimeNotFound("Nie ma takiego timesheetu.")
    return timesheet


def validate_period(year: int, month: int) -> None:
    if not 2020 <= year <= 2100 or not 1 <= month <= 12:
        raise TimeError("Nieprawidłowy miesiąc.")


def assert_not_locked(timesheet: Timesheet) -> None:
    if timesheet.payroll_locked:
        raise TimeConflict(LOCKED_DETAIL)


async def entries_of(db: AsyncSession, timesheet_id: int) -> list[TimesheetEntry]:
    rows = await db.scalars(
        select(TimesheetEntry)
        .where(TimesheetEntry.timesheet_id == timesheet_id)
        .order_by(TimesheetEntry.work_date, TimesheetEntry.id)
    )
    return list(rows)


def hash_of(entries: list[TimesheetEntry]) -> str:
    return compute_timesheet_hash(
        HashEntry(
            work_date=entry.work_date,
            hours=entry.hours,
            project=entry.project,
            description=entry.description,
        )
        for entry in entries
    )


async def recompute_hash_if_set(db: AsyncSession, timesheet: Timesheet) -> bool:
    """Po legalnej zmianie wpisów zaakceptowanego timesheetu (urlop) — nowa suma."""

    if not timesheet.pdf_hash:
        return False
    await db.flush()
    fresh = hash_of(await entries_of(db, timesheet.id))
    if fresh == timesheet.pdf_hash:
        return False
    timesheet.pdf_hash = fresh
    return True


# ── Urlop dnia ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DayLeave:
    """Jak urlop dnia wpływa na godziny."""

    leave: bridge.LeaveDay
    paid_work: bool  # auto-wpis leave_paid zamiast blokady

    @property
    def blocks_day(self) -> bool:
        """Pełny dzień urlopu — także płatny z auto-wpisem — nie przyjmuje godzin."""

        return self.leave.is_full

    @property
    def occupied_hours(self) -> Decimal:
        """Godziny dnia zajęte przez urlop (poza auto-wpisem, który liczy się sam)."""

        if self.paid_work:
            return Decimal("0")
        return STANDARD * min(self.leave.fraction, Decimal("1"))

    @property
    def paid_hours(self) -> Decimal:
        return STANDARD * self.leave.fraction if self.paid_work else Decimal("0")

    @property
    def manual_cap(self) -> Decimal:
        """Najwięcej zwykłych ręcznych godzin dnia (pół dnia urlopu → 4 h)."""

        return max(STANDARD - self.occupied_hours - self.paid_hours, Decimal("0"))


def employed_on(subject: EmployeeProfile, day: date) -> bool:
    """Dzień mieści się w zatrudnieniu z kartoteki (brak daty = bez granicy)."""

    if subject.work_start_date is not None and day < subject.work_start_date:
        return False
    if subject.last_working_day is not None and day > subject.last_working_day:
        return False
    return True


async def leave_map(
    db: AsyncSession,
    *,
    user_id: int,
    employment_type: Optional[str],
    start: date,
    end: date,
) -> dict[date, DayLeave]:
    days = await bridge.leave_days(db, [user_id], start, end)
    return {
        item.day: DayLeave(leave=item, paid_work=item.is_paid_work_for(employment_type))
        for item in days
    }


# ── Walidacja pól ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntryInput:
    work_date: date
    hours: Decimal
    project: Optional[str]
    description: str
    overtime_reason: Optional[str] = None


def clean_hours(raw: Any) -> Decimal:
    try:
        hours = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise TimeError("Godziny muszą być liczbą.") from None
    if not hours.is_finite() or hours <= 0:
        raise TimeError("Godziny muszą być większe od zera.")
    if hours > OVERTIME_MAX:
        raise TimeError(f"Maksymalnie {OVERTIME_MAX_HOURS} h na dzień.")
    if hours != hours.quantize(Decimal("0.01")):
        raise TimeError("Godziny podaje się z dokładnością do 0,01 h.")
    return hours.quantize(Decimal("0.01"))


def clean_description(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    if not text:
        raise TimeError("Opis jest wymagany.")
    if len(text) > MAX_DESCRIPTION:
        raise TimeError(f"Opis może mieć najwyżej {MAX_DESCRIPTION} znaków.")
    return text


def clean_project(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()
    if len(text) > MAX_PROJECT:
        raise TimeError(f"Nazwa projektu może mieć najwyżej {MAX_PROJECT} znaków.")
    return text or None


def _assert_in_month(timesheet: Timesheet, work_date: date) -> None:
    if (work_date.year, work_date.month) != (timesheet.year, timesheet.month):
        raise TimeError(
            f"Data {work_date.isoformat()} nie należy do miesiąca tego timesheetu "
            f"({timesheet.year}-{timesheet.month:02d})."
        )


def _assert_day_open(day_leave: Optional[DayLeave], work_date: date) -> Decimal:
    """Godziny zajęte przez urlop; pełny dzień urlopu rzuca błąd."""

    if day_leave is None:
        return Decimal("0")
    if day_leave.blocks_day:
        if day_leave.leave.status == "pending":
            raise TimeError(
                f"{work_date.isoformat()} — wniosek urlopowy na ten dzień czeka na "
                "decyzję. Godziny wpiszesz po jego odrzuceniu albo anulowaniu."
            )
        raise TimeError(
            f"{work_date.isoformat()} to dzień urlopu — w dniu nieobecności "
            "nie wpisuje się godzin."
        )
    return day_leave.occupied_hours


# ── Zapis wpisów ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OvertimeDecision:
    is_overtime: bool
    reason: Optional[str]


async def _day_hours(
    db: AsyncSession, timesheet_id: int, work_date: date, *, exclude_id: Optional[int]
) -> Decimal:
    statement = select(TimesheetEntry.hours).where(
        TimesheetEntry.timesheet_id == timesheet_id,
        TimesheetEntry.work_date == work_date,
    )
    if exclude_id is not None:
        statement = statement.where(TimesheetEntry.id != exclude_id)
    rows = await db.scalars(statement)
    return sum((Decimal(value) for value in rows), Decimal("0"))


def _decide_overtime(
    *,
    actor: Actor,
    other_hours: Decimal,
    hours: Decimal,
    occupied: Decimal,
    reason: Optional[str],
    work_date: date,
    form: Optional[str],
) -> OvertimeDecision:
    total = other_hours + hours + occupied
    words = terms(form)
    if total <= STANDARD:
        return OvertimeDecision(False, None)
    if not actor.overtime_allowed:
        if occupied > 0:
            raise TimeError(
                f"{work_date.isoformat()} to pół dnia urlopu — można wpisać najwyżej "
                f"{_fmt(STANDARD - occupied)} h (już wpisane: {_fmt(other_hours)} h)."
            )
        raise TimeForbidden(
            f"Suma godzin {work_date.isoformat()} przekroczyłaby {STANDARD_DAY_HOURS} h "
            f"(już wpisane: {_fmt(other_hours)} h). {capitalize(words['overtime'])} "
            f"wpisuje osoba z uprawnieniem do {words['overtime_genitive']} albo Kadry."
        )
    if total > OVERTIME_MAX:
        raise TimeError(
            f"Suma godzin {work_date.isoformat()} przekroczyłaby {OVERTIME_MAX_HOURS} h "
            f"(już wpisane: {_fmt(other_hours + occupied)} h)."
        )
    text = (reason or "").strip()
    if len(text) < OVERTIME_REASON_MIN_LENGTH:
        raise TimeError(
            f"{words['overtime_reason_required']} (co najmniej "
            f"{OVERTIME_REASON_MIN_LENGTH} znaków)."
        )
    if len(text) > MAX_OVERTIME_REASON:
        raise TimeError(
            f"Uzasadnienie może mieć najwyżej {MAX_OVERTIME_REASON} znaków."
        )
    return OvertimeDecision(True, text)


def _fmt(value: Decimal) -> str:
    text = format(value.normalize(), "f") if value else "0"
    return text.replace(".", ",")


async def _normalize_day_overtime(
    db: AsyncSession, timesheet_id: int, work_date: date, occupied: Decimal
) -> None:
    """Dzień wrócił do ≤ 8 h — żaden jego wpis nie jest już nadgodziną."""

    await db.flush()
    total = await _day_hours(db, timesheet_id, work_date, exclude_id=None)
    if total + occupied > STANDARD:
        return
    await db.execute(
        update(TimesheetEntry)
        .where(
            TimesheetEntry.timesheet_id == timesheet_id,
            TimesheetEntry.work_date == work_date,
            TimesheetEntry.is_overtime.is_(True),
        )
        .values(is_overtime=False, overtime_reason=None, overtime_by=None)
        .execution_options(synchronize_session="fetch")
    )


def assert_editable(timesheet: Timesheet, *, as_approver: bool) -> None:
    assert_not_locked(timesheet)
    allowed = ("draft", "submitted") if as_approver else ("draft",)
    if timesheet.status in allowed:
        return
    if timesheet.status == "approved":
        raise TimeConflict(
            "Timesheet jest zaakceptowany — poprawka wymaga cofnięcia akceptacji."
        )
    raise TimeConflict(
        "Timesheet czeka na akceptację — poprawki wprowadza akceptujący albo "
        "zwraca go do Ciebie."
    )


async def add_entry(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    subject: EmployeeProfile,
    actor: Actor,
    data: EntryInput,
    source: str = "manual",
) -> TimesheetEntry:
    """Nowy wpis; ``timesheet`` musi być zablokowany (``lock_timesheet``)."""

    _assert_in_month(timesheet, data.work_date)
    leaves = await leave_map(
        db,
        user_id=timesheet.user_id,
        employment_type=subject.employment_type,
        start=data.work_date,
        end=data.work_date,
    )
    occupied = _assert_day_open(leaves.get(data.work_date), data.work_date)
    other = await _day_hours(db, timesheet.id, data.work_date, exclude_id=None)
    decision = _decide_overtime(
        actor=actor,
        other_hours=other,
        hours=data.hours,
        occupied=occupied,
        reason=data.overtime_reason,
        work_date=data.work_date,
        form=subject.employment_type,
    )
    entry = TimesheetEntry(
        timesheet_id=timesheet.id,
        work_date=data.work_date,
        hours=data.hours,
        project=data.project,
        description=data.description,
        source=source,
        is_overtime=decision.is_overtime,
        overtime_reason=decision.reason,
        overtime_by=actor.user_id if decision.is_overtime else None,
        created_by=actor.user_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def update_entry(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    subject: EmployeeProfile,
    actor: Actor,
    entry: TimesheetEntry,
    changes: dict[str, Any],
) -> TimesheetEntry:
    if entry.source == "leave_paid":
        raise TimeConflict(
            "Ten wpis powstał z płatnego urlopu — zmień albo anuluj wniosek urlopowy."
        )
    old_date = entry.work_date
    work_date = changes.get("work_date", entry.work_date)
    hours = changes.get("hours", Decimal(entry.hours))
    _assert_in_month(timesheet, work_date)
    leaves = await leave_map(
        db,
        user_id=timesheet.user_id,
        employment_type=subject.employment_type,
        start=min(work_date, old_date),
        end=max(work_date, old_date),
    )
    occupied = _assert_day_open(leaves.get(work_date), work_date)
    # Sam opis albo projekt nie zmienia sumy dnia — nadgodziny zostają, jak
    # były (bez tego poprawka literówki w dniu z nadgodzinami dawała 422,
    # a u przełożonego bez prawa do nadgodzin 403; audyt 19.10.2026).
    reason_changed = "overtime_reason" in changes and (
        changes["overtime_reason"] or None
    ) != (entry.overtime_reason or None)
    text_only = (
        work_date == old_date and hours == Decimal(entry.hours) and not reason_changed
    )
    if not text_only:
        other = await _day_hours(db, timesheet.id, work_date, exclude_id=entry.id)
        decision = _decide_overtime(
            actor=actor,
            other_hours=other,
            hours=hours,
            occupied=occupied,
            reason=changes.get("overtime_reason", entry.overtime_reason),
            work_date=work_date,
            form=subject.employment_type,
        )
    entry.work_date = work_date
    entry.hours = hours
    if "project" in changes:
        entry.project = changes["project"]
    if "description" in changes:
        entry.description = changes["description"]
    if not text_only:
        entry.is_overtime = decision.is_overtime
        entry.overtime_reason = decision.reason
        entry.overtime_by = actor.user_id if decision.is_overtime else None
    if entry.source == "template":
        entry.source = "manual"
    await db.flush()
    if old_date != work_date:
        old_leave = leaves.get(old_date)
        await _normalize_day_overtime(
            db,
            timesheet.id,
            old_date,
            old_leave.occupied_hours if old_leave else Decimal("0"),
        )
    await _normalize_day_overtime(db, timesheet.id, work_date, occupied)
    return entry


async def delete_entry(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    subject: EmployeeProfile,
    entry: TimesheetEntry,
) -> None:
    if entry.source == "leave_paid":
        raise TimeConflict(
            "Ten wpis powstał z płatnego urlopu — zmień albo anuluj wniosek urlopowy."
        )
    # Przyjęte potwierdzenie godzin zlecenia po terminie wypłaty zostaje 3 lata
    # (art. 8c) — trasy i tak edytują tylko szkic, to pilnuje każdej ścieżki.
    refusal = time_retention.delete_refusal(
        timesheet, current_form=subject.employment_type
    )
    if refusal is not None:
        raise TimeConflict(refusal)
    work_date = entry.work_date
    await db.delete(entry)
    # Usunięty wpis nie zostawia śladu w wierszach — nagłówek niesie zmianę
    # (ponowny import z Compassa nie przywróci wpisu skasowanego w NEXUSIE).
    timesheet.updated_at = func.now()
    await db.flush()
    leaves = await leave_map(
        db,
        user_id=timesheet.user_id,
        employment_type=subject.employment_type,
        start=work_date,
        end=work_date,
    )
    day_leave = leaves.get(work_date)
    await _normalize_day_overtime(
        db,
        timesheet.id,
        work_date,
        day_leave.occupied_hours if day_leave else Decimal("0"),
    )


async def entry_with_timesheet(
    db: AsyncSession, entry_id: int
) -> tuple[TimesheetEntry, Timesheet]:
    entry = await db.get(TimesheetEntry, entry_id)
    if entry is None:
        raise TimeNotFound("Nie ma takiego wpisu.")
    timesheet = await lock_timesheet(db, entry.timesheet_id)
    entry = await db.get(TimesheetEntry, entry_id, populate_existing=True)
    if entry is None:
        raise TimeNotFound("Nie ma takiego wpisu.")
    return entry, timesheet


# ── Płatny urlop kontraktora (auto-wpisy) ─────────────────────────────────────


def planned_leave_paid(
    leaves: dict[date, DayLeave], entries: Iterable[TimesheetEntry]
) -> dict[date, Decimal]:
    """Auto-wpisy ``leave_paid``, które ma mieć szkic: dzień → godziny.

    Jedna reguła dla zapisu (``sync_leave_paid``) i odczytu szkicu
    (``time_month.month_view``): pełny dzień płatnej puli = 8 h, połowa = 4 h,
    a połowy nie dokładamy, gdy ręczne godziny dnia przekraczają już 4 h.
    """

    manual_hours: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for entry in entries:
        if entry.source != "leave_paid":
            manual_hours[entry.work_date] += Decimal(entry.hours)
    desired: dict[date, Decimal] = {}
    for day, day_leave in leaves.items():
        if not day_leave.paid_work:
            continue
        hours = day_leave.paid_hours
        if not day_leave.leave.is_full and manual_hours[day] > STANDARD - hours:
            continue
        desired[day] = hours
    return desired


async def sync_leave_paid(
    db: AsyncSession, *, timesheet: Timesheet, employment_type: Optional[str]
) -> int:
    """Uzgadnia auto-wpisy ``leave_paid`` z zatwierdzonymi dniami puli.

    Pełny dzień = 8 h, połowa = 4 h. Połowy nie dokładamy, gdy ręczne godziny
    tego dnia przekraczają już 4 h (jak Compass: bez podwójnego liczenia).
    Zwraca liczbę zmian; przy zmianie na zaakceptowanym — nowa suma kontrolna.
    """

    start, end = month_range(timesheet.year, timesheet.month)
    leaves = await leave_map(
        db,
        user_id=timesheet.user_id,
        employment_type=employment_type,
        start=start,
        end=end,
    )
    entries = await entries_of(db, timesheet.id)
    auto: dict[date, list[TimesheetEntry]] = defaultdict(list)
    for entry in entries:
        if entry.source == "leave_paid":
            auto[entry.work_date].append(entry)
    desired = planned_leave_paid(leaves, entries)

    changes = 0
    for day, rows in auto.items():
        keep = desired.get(day)
        for index, row in enumerate(rows):
            if keep is not None and index == 0 and Decimal(row.hours) == keep:
                continue
            await db.delete(row)
            changes += 1
    for day, hours in sorted(desired.items()):
        rows = auto.get(day, [])
        if rows and Decimal(rows[0].hours) == hours:
            continue
        db.add(
            TimesheetEntry(
                timesheet_id=timesheet.id,
                work_date=day,
                hours=hours,
                project=None,
                description=standard_description(employment_type),
                source="leave_paid",
            )
        )
        changes += 1
    if changes:
        # Jak ``delete_entry``: zmiana auto-wpisów to zmiana w NEXUSIE —
        # ponowny import z Compassa nie przywróci godzin odwołanego urlopu
        # (audyt 19.10.2026).
        timesheet.updated_at = func.now()
        await db.flush()
        await recompute_hash_if_set(db, timesheet)
    return changes


async def remove_hours_on_full_leave_days(
    db: AsyncSession, *, timesheet: Timesheet, days: set[date]
) -> list[TimesheetEntry]:
    """Kasuje ręczne godziny z pełnych dni urlopu (zatwierdzenie wniosku)."""

    if not days:
        return []
    rows = list(
        await db.scalars(
            select(TimesheetEntry).where(
                TimesheetEntry.timesheet_id == timesheet.id,
                TimesheetEntry.work_date.in_(sorted(days)),
                TimesheetEntry.source != "leave_paid",
            )
        )
    )
    if rows:
        await db.execute(
            delete(TimesheetEntry).where(
                TimesheetEntry.id.in_([row.id for row in rows])
            )
        )
        timesheet.updated_at = func.now()  # jak ``delete_entry``
    return rows


def plan_half_day_trim(
    entries: Iterable[TimesheetEntry], caps: dict[date, Decimal]
) -> dict[int, Decimal]:
    """Wpis → nowe godziny (0 = usunąć), żeby zwykłe ręczne godziny dnia
    zmieściły się w limicie ``caps`` (pół dnia urlopu → 4 h).

    Skracamy od najpóźniej dodanego wpisu. Auto-wpis ``leave_paid`` liczy się
    w limicie sam, a nadgodzina (wpis ponad 8 h sumy dnia z uzasadnieniem)
    zostaje — limit dnia dotyczy zwykłych godzin.
    """

    by_day: dict[date, list[TimesheetEntry]] = defaultdict(list)
    for entry in entries:
        if (
            entry.work_date in caps
            and entry.source != "leave_paid"
            and not entry.is_overtime
        ):
            by_day[entry.work_date].append(entry)
    plan: dict[int, Decimal] = {}
    for day, rows in by_day.items():
        excess = sum((Decimal(row.hours) for row in rows), Decimal("0")) - caps[day]
        for row in sorted(rows, key=lambda item: item.id, reverse=True):
            if excess <= 0:
                break
            cut = min(excess, Decimal(row.hours))
            plan[row.id] = Decimal(row.hours) - cut
            excess -= cut
    return plan


async def trim_hours_on_half_leave_days(
    db: AsyncSession, *, timesheet: Timesheet, caps: dict[date, Decimal]
) -> list[tuple[TimesheetEntry, Decimal, Decimal]]:
    """Skraca ręczne godziny dni z połową urlopu (zatwierdzenie wniosku).

    Zwraca (wpis, godziny przed, godziny po); wpis skrócony do zera znika.
    """

    if not caps:
        return []
    rows = list(
        await db.scalars(
            select(TimesheetEntry).where(
                TimesheetEntry.timesheet_id == timesheet.id,
                TimesheetEntry.work_date.in_(sorted(caps)),
            )
        )
    )
    plan = plan_half_day_trim(rows, caps)
    changed: list[tuple[TimesheetEntry, Decimal, Decimal]] = []
    for row in rows:
        if row.id not in plan:
            continue
        before, after = Decimal(row.hours), plan[row.id]
        if after > 0:
            row.hours = after
        else:
            await db.delete(row)
        changed.append((row, before, after))
    if changed:
        timesheet.updated_at = func.now()  # jak ``delete_entry``
        await db.flush()
    return changed


def entry_payload(entry: TimesheetEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "work_date": entry.work_date.isoformat(),
        "hours": float(entry.hours),
        "project": entry.project,
        "description": entry.description,
        "source": entry.source,
        "is_overtime": entry.is_overtime,
        "overtime_reason": entry.overtime_reason,
    }
