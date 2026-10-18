"""Paczka miesiąca dla Symfonii ERP Kadry i Płace (R5, decyzja 17.10.2026).

Symfonia nie ma API do zapisu w Kadrach i Płacach — Płace importują pliki
w programie. Paczka (ZIP) powstaje z ZAMKNIĘTEGO miesiąca płac (zamrożone
linie, ``payroll_lines``):

* ``zdarzenia_RRRR-MM.xml`` — nieobecności z zatwierdzonych wniosków
  i nadgodziny z zatwierdzonych timesheetów, tylko umowa o pracę. Rodzaj
  nieobecności widzi wyłącznie krąg D6 (osoba, przełożony, Kadry, admin),
  więc plik zdarzeń dostaje tylko osoba z uprawnieniem „Kadry” (albo admin);
  Płace bez „Kadr” dostają paczkę bez niego i zdanie w zestawieniu. L4 tylko
  po włączeniu „Płace nie pobierają e-ZLA” (inaczej Symfonia ma je z PUE ZUS),
* ``premie_RRRR-MM.xlsx`` — premie przyznane w miesiącu (UoP, PLN), kolumna
  na rodzaj premii ze słownika w Ustawieniach,
* ``zlecenia_rozliczenia_RRRR-MM.xlsx`` — rozliczenia umów zlecenia: kwota
  brutto z zamrożonej linii (godziny × stawka + premie), data rozliczenia =
  dzień wypłaty,
* ``zestawienie_RRRR-MM.pdf`` — sumy kontrolne, skróty plików, lista rzeczy
  do zrobienia ręcznie (nowe osoby i umowy, odejścia, koniec zwolnienia
  studenta, osoby bez identyfikatora, kwoty w innej walucie).

Kwoty (premie, zlecenia) trafiają do paczki tylko osobie z uprawnieniem
„Płace”. B2B nie idzie do Symfonii (faktury rozlicza księgowość).

Osoba w Symfonii: identyfikator z danych do rozliczeń (GUID albo numer
ewidencyjny — PESEL nie trafia do NEXUSA) + nazwisko i imię. Osoba bez
identyfikatora nie trafia do plików, tylko na listę „do zrobienia”. W XML-u
zdarzeń Symfonia rozpoznaje osobę po GUID-zie albo po nazwisku i imieniu —
imiennicy bez GUID-u wypadają z XML-a (lista „do zrobienia”).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_payroll import HrBonus, PayrollLine
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import EmployeeBillingDetails
from app.models.user import User
from app.services.hr import audit, leave_policy, symfonia_files
from app.services.hr.bank.elixir import amount_text
from app.services.hr.bank.settings import PaymentSettings, load_settings
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.hr.payroll_access import is_payroll
from app.services.hr.payroll_errors import PayrollConflict
from app.services.hr.payroll_periods import (
    get_period,
    label,
    month_end,
    month_start,
    validate_period,
)
from app.services.hr.payroll_report import money
from app.services.hr.settlements_rules import payout_date
from app.services.hr.symfonia_files import (
    BonusRow,
    MandateRow,
    Summary,
    SummaryFile,
    SymfoniaEvent,
    SymfoniaPerson,
    split_name,
    time_text,
)
from app.services.hr_leave_schema import LEAVE_TYPES
from app.services.hr_time_schema import STANDARD_DAY_HOURS

UOP = "uop"
MANDATE = "zlecenie"
B2B = "b2b"
HALF_DAY_MINUTES = STANDARD_DAY_HOURS * 60 // 2
SICK_LEAVE = "sick_leave"


@dataclass(frozen=True)
class Rights:
    amounts: bool
    events: bool


def rights_of(user: User) -> Rights:
    return Rights(
        amounts=is_payroll(user),
        events=leave_policy.actor_of(user).sees_everyone,
    )


@dataclass(frozen=True)
class PersonFacts:
    user_id: int
    name: str
    employment_type: Optional[str]
    symfonia_id: Optional[str]
    start: Optional[date]
    last_working_day: Optional[date]
    student_exempt: bool
    exempt_until: Optional[date]


@dataclass
class Package:
    year: int
    month: int
    rights: Rights
    events: list[SymfoniaEvent] = field(default_factory=list)
    bonuses: list[BonusRow] = field(default_factory=list)
    bonus_columns: list[str] = field(default_factory=list)
    mandates: list[MandateRow] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    totals: dict[str, Decimal] = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return f"{self.year}-{self.month:02d}"


# ── Dane ──────────────────────────────────────────────────────────────────────


async def _people(db: AsyncSession, period_id: int) -> dict[int, PersonFacts]:
    rows = await db.execute(
        select(
            PayrollLine.user_id,
            PayrollLine.person_name,
            PayrollLine.employment_type,
            EmployeeBillingDetails.symfonia_id,
            EmployeeProfile.work_start_date,
            EmployeeProfile.hired_on,
            EmployeeProfile.last_working_day,
            EmployeeProfile.student_contribution_exempt,
            EmployeeProfile.contribution_exempt_until,
        )
        .outerjoin(
            EmployeeBillingDetails,
            EmployeeBillingDetails.user_id == PayrollLine.user_id,
        )
        .outerjoin(EmployeeProfile, EmployeeProfile.user_id == PayrollLine.user_id)
        .where(PayrollLine.period_id == period_id)
        .distinct(PayrollLine.user_id)
        .order_by(PayrollLine.user_id)
    )
    return {
        int(uid): PersonFacts(
            user_id=int(uid),
            name=str(name),
            employment_type=form,
            symfonia_id=(symfonia_id or "").strip() or None,
            start=work_start or hired_on,
            last_working_day=last_day,
            student_exempt=bool(student),
            exempt_until=until,
        )
        for uid, name, form, symfonia_id, work_start, hired_on, last_day, student, until in rows.all()
    }


def _ranges(days: list[date], calendar: WorkCalendar) -> list[tuple[date, date]]:
    """Dni jednego wniosku → zakresy; przerwa z samych dni wolnych nie dzieli."""

    ranges: list[tuple[date, date]] = []
    for day in sorted(days):
        if ranges:
            start, end = ranges[-1]
            gap = [end + timedelta(days=n) for n in range(1, (day - end).days)]
            if all(not calendar.is_working_day(between) for between in gap):
                ranges[-1] = (start, day)
                continue
        ranges.append((day, day))
    return ranges


def _minutes(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


async def _leave_events(
    db: AsyncSession,
    people: dict[int, SymfoniaPerson],
    settings: PaymentSettings,
    first: date,
    last: date,
    package: Package,
) -> None:
    if not people:
        return
    rows = await db.execute(
        select(
            LeaveRequest.id,
            LeaveRequest.user_id,
            LeaveRequest.leave_type,
            LeaveRequest.half_day,
            LeaveRequestDay.day,
            LeaveRequestDay.fraction,
        )
        .join(LeaveRequestDay, LeaveRequestDay.leave_request_id == LeaveRequest.id)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day >= first,
            LeaveRequestDay.day <= last,
            LeaveRequest.user_id.in_(list(people)),
        )
        .order_by(LeaveRequest.user_id, LeaveRequest.id, LeaveRequestDay.day)
    )
    calendar = await load_calendar(db, first, last)
    names = settings.symfonia.leave_events
    work_start = _minutes(settings.symfonia.work_start)
    whole: dict[tuple[Any, int, str], list[date]] = defaultdict(list)
    missing: dict[str, set[int]] = defaultdict(set)
    sick_skipped = 0
    for request_id, user_id, leave_type, half_day, day, fraction in rows.all():
        if leave_type == SICK_LEAVE and not settings.symfonia.export_sick_leave:
            sick_skipped += 1
            continue
        name = names.get(leave_type)
        if not name:
            missing[leave_type].add(int(user_id))
            continue
        person = people[int(user_id)]
        if Decimal(fraction) < 1:
            offset = HALF_DAY_MINUTES if half_day == "afternoon" else 0
            package.events.append(
                SymfoniaEvent(
                    person=person,
                    name=name,
                    begin=day,
                    end=day,
                    start=time_text(work_start + offset),
                    stop=time_text(work_start + offset + HALF_DAY_MINUTES),
                )
            )
            package.counts["leave_half_days"] = (
                package.counts.get("leave_half_days", 0) + 1
            )
            continue
        whole[(request_id, int(user_id), name)].append(day)
    for (_request, user_id, name), days in whole.items():
        for begin, end in _ranges(days, calendar):
            package.events.append(
                SymfoniaEvent(person=people[user_id], name=name, begin=begin, end=end)
            )
            package.counts["leave_events"] = package.counts.get("leave_events", 0) + 1
    for leave_type in sorted(missing, key=LEAVE_TYPES.index):
        package.todo.append(
            f"Nieobecność „{leave_policy.LEAVE_TYPE_LABELS.get(leave_type, leave_type)}” "
            f"({len(missing[leave_type])} os.) nie ma nazwy zdarzenia w Ustawieniach → "
            "Płace — wpisz ją w Symfonii ręcznie albo uzupełnij słownik."
        )
    if sick_skipped:
        package.notes.append(
            "Zwolnienia lekarskie (L4) nie są w pliku — Symfonia pobiera e-ZLA z PUE "
            "ZUS (ustawienie w Ustawieniach → Płace)."
        )


async def overtime_days(
    db: AsyncSession, year: int, month: int, user_ids: list[int]
) -> dict[int, list[tuple[date, Decimal]]]:
    """Nadgodziny per dzień z zatwierdzonych timesheetów (reguła jak w raporcie płac).

    Ta sama reguła co ``payroll_time_bridge.approved_hours`` (suma dnia + dzień
    nieobecności ponad 8 h); dla umowy o pracę nie ma wyjątku płatnej puli
    kontraktora. Test porównuje sumę z raportem płac.
    """

    if not user_ids:
        return {}
    rows = await db.execute(
        text(
            "SELECT t.user_id, e.work_date, SUM(e.hours) AS day_hours, "
            "       COALESCE(MAX(o.occupied), 0) AS occupied "
            "FROM timesheets t "
            "JOIN timesheet_entries e ON e.timesheet_id = t.id "
            "LEFT JOIN ("
            "  SELECT d.user_id, d.day, "
            "         MAX(CAST(:standard AS numeric) * LEAST(d.fraction, 1)) AS occupied "
            "  FROM leave_request_days d "
            "  JOIN leave_requests r ON r.id = d.leave_request_id "
            "  WHERE d.active AND r.status IN ('pending', 'approved') "
            "    AND d.day BETWEEN :first AND :last "
            "  GROUP BY d.user_id, d.day"
            ") o ON o.user_id = t.user_id AND o.day = e.work_date "
            "WHERE t.year = :year AND t.month = :month AND t.status = 'approved' "
            "  AND t.user_id = ANY(:user_ids) "
            "GROUP BY t.user_id, e.work_date "
            "ORDER BY t.user_id, e.work_date"
        ),
        {
            "year": year,
            "month": month,
            "standard": STANDARD_DAY_HOURS,
            "first": month_start(year, month),
            "last": month_end(year, month),
            "user_ids": user_ids,
        },
    )
    found: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in rows:
        extra = Decimal(row.day_hours) + Decimal(row.occupied) - STANDARD_DAY_HOURS
        if extra > 0:
            found[int(row.user_id)].append((row.work_date, extra))
    return dict(found)


async def _overtime_events(
    db: AsyncSession,
    people: dict[int, SymfoniaPerson],
    settings: PaymentSettings,
    year: int,
    month: int,
    package: Package,
) -> None:
    name = settings.symfonia.overtime_event
    days = await overtime_days(db, year, month, list(people))
    if not days:
        return
    if not name:
        package.todo.append(
            f"Nadgodziny ({len(days)} os.) — brak nazwy zdarzenia w Ustawieniach → "
            "Płace; wpisz je w Symfonii ręcznie."
        )
        return
    start = _minutes(settings.symfonia.work_start) + STANDARD_DAY_HOURS * 60
    for user_id, entries in days.items():
        for day, extra in entries:
            minutes = int((extra * 60).to_integral_value())
            if start + minutes > 23 * 60 + 59:
                package.todo.append(
                    f"{people[user_id].given_name} {people[user_id].surname}: "
                    f"nadgodziny {day.isoformat()} sięgają po północy — wpisz je ręcznie."
                )
                continue
            package.events.append(
                SymfoniaEvent(
                    person=people[user_id],
                    name=name,
                    begin=day,
                    end=day,
                    start=time_text(start),
                    stop=time_text(start + minutes),
                )
            )
            package.counts["overtime_days"] = package.counts.get("overtime_days", 0) + 1


async def _bonuses(
    db: AsyncSession,
    people: dict[int, SymfoniaPerson],
    settings: PaymentSettings,
    year: int,
    month: int,
    package: Package,
) -> None:
    if not people:
        return
    rows = await db.execute(
        select(
            HrBonus.recipient_user_id,
            HrBonus.category,
            HrBonus.currency,
            HrBonus.amount,
        )
        .where(
            HrBonus.period_year == year,
            HrBonus.period_month == month,
            HrBonus.status == "assigned",
            HrBonus.recipient_user_id.in_(list(people)),
        )
        .order_by(HrBonus.recipient_user_id, HrBonus.id)
    )
    components = settings.symfonia.bonus_components
    sums: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    foreign: set[int] = set()
    unnamed: set[str] = set()
    for user_id, category, currency, amount in rows.all():
        if currency != "PLN":
            foreign.add(int(user_id))
            continue
        column = components.get(category)
        if not column:
            unnamed.add(category)
            continue
        sums[int(user_id)][column] += Decimal(amount)
    columns = sorted({column for amounts in sums.values() for column in amounts})
    package.bonus_columns = columns
    for user_id, amounts in sums.items():
        package.bonuses.append(
            BonusRow(
                person=people[user_id],
                amounts={column: money(value) for column, value in amounts.items()},
            )
        )
        for column, value in amounts.items():
            package.totals[f"Premie · {column}"] = money(
                package.totals.get(f"Premie · {column}", Decimal("0")) + value
            )
    for user_id in sorted(foreign):
        person = people[user_id]
        package.todo.append(
            f"{person.given_name} {person.surname}: premia w walucie innej niż PLN — "
            "wpisz ją w Symfonii ręcznie."
        )
    if unnamed:
        package.todo.append(
            "Rodzaje premii bez kolumny w Ustawieniach → Płace: "
            + ", ".join(sorted(unnamed))
            + " — wpisz je ręcznie albo uzupełnij słownik."
        )


async def _mandates(
    db: AsyncSession,
    period_id: int,
    people: dict[int, SymfoniaPerson],
    facts: dict[int, PersonFacts],
    settings: PaymentSettings,
    year: int,
    month: int,
    package: Package,
) -> None:
    if not people:
        return
    lines = list(
        await db.scalars(
            select(PayrollLine)
            .where(
                PayrollLine.period_id == period_id,
                PayrollLine.user_id.in_(list(people)),
            )
            .order_by(PayrollLine.user_id, PayrollLine.currency)
        )
    )
    settled_on = payout_date(year, month, settings.payout_day)
    by_user: dict[int, list[PayrollLine]] = defaultdict(list)
    for line in lines:
        by_user[line.user_id].append(line)
    for user_id, own in by_user.items():
        person = people[user_id]
        for line in own:
            if line.currency != "PLN":
                if Decimal(line.total) > 0:
                    package.todo.append(
                        f"{person.given_name} {person.surname}: rozliczenie zlecenia "
                        f"w {line.currency} — wpisz je w Symfonii ręcznie."
                    )
                continue
            if Decimal(line.total) <= 0:
                continue
            contract_date = facts[user_id].start
            if contract_date is None:
                package.todo.append(
                    f"{person.given_name} {person.surname}: brak daty umowy zlecenia "
                    "w kartotece — uzupełnij „Data umowy” w pliku przed importem."
                )
            package.mandates.append(
                MandateRow(
                    person=person,
                    contract_date=contract_date,
                    settlement_date=settled_on,
                    gross=money(Decimal(line.total)),
                    hours=Decimal(line.hours),
                    rate=Decimal(line.hourly_rate)
                    if line.hourly_rate is not None
                    else None,
                    bonuses=money(Decimal(line.bonus_total)),
                )
            )
            package.totals["Zlecenia · brutto"] = money(
                package.totals.get("Zlecenia · brutto", Decimal("0"))
                + Decimal(line.total)
            )


def _lifecycle_todo(facts: dict[int, PersonFacts], year: int, month: int) -> list[str]:
    first, last = month_start(year, month), month_end(year, month)
    next_last = month_end(*((year + 1, 1) if month == 12 else (year, month + 1)))
    todo: list[str] = []
    for person in sorted(facts.values(), key=lambda p: p.name.casefold()):
        if person.employment_type not in (UOP, MANDATE):
            continue
        if person.start and first <= person.start <= last:
            todo.append(
                f"{person.name}: nowa osoba od {person.start.strftime('%d.%m.%Y')} — "
                "załóż kartotekę i umowę w Symfonii (zgłoszenie ZUS) przed importem."
            )
        if person.last_working_day and first <= person.last_working_day <= last:
            todo.append(
                f"{person.name}: koniec współpracy "
                f"{person.last_working_day.strftime('%d.%m.%Y')} — rozwiązanie umowy "
                "i wyrejestrowanie w Symfonii."
            )
        if (
            person.student_exempt
            and person.exempt_until
            and first <= person.exempt_until <= next_last
        ):
            todo.append(
                f"{person.name}: zwolnienie ze składek (student do 26 lat) kończy się "
                f"{person.exempt_until.strftime('%d.%m.%Y')} — zmień kod tytułu "
                "ubezpieczenia w Symfonii."
            )
    return todo


def _identified(
    facts: dict[int, PersonFacts], forms: tuple[str, ...]
) -> dict[int, SymfoniaPerson]:
    people: dict[int, SymfoniaPerson] = {}
    for person in facts.values():
        if person.employment_type not in forms:
            continue
        if not person.symfonia_id:
            continue
        surname, given = split_name(person.name)
        people[person.user_id] = SymfoniaPerson(
            user_id=person.user_id,
            surname=surname,
            given_name=given,
            symfonia_id=person.symfonia_id,
        )
    return people


def _without_namesakes(
    people: dict[int, SymfoniaPerson], package: Package
) -> dict[int, SymfoniaPerson]:
    """XML zdarzeń: bez GUID-u Symfonia szuka po nazwisku i imieniu."""

    keys: dict[tuple[str, str], list[int]] = defaultdict(list)
    for person in people.values():
        if person.guid is None:
            keys[(person.surname.casefold(), person.given_name.casefold())].append(
                person.user_id
            )
    clashing = {uid for ids in keys.values() if len(ids) > 1 for uid in ids}
    for user_id in sorted(clashing):
        person = people[user_id]
        package.todo.append(
            f"{person.given_name} {person.surname}: imiennik bez GUID-u z Symfonii — "
            "nieobecności i nadgodziny tej osoby nie są w pliku zdarzeń; wpisz GUID "
            "w danych do rozliczeń albo wprowadź je ręcznie."
        )
    return {uid: person for uid, person in people.items() if uid not in clashing}


async def collect(
    db: AsyncSession, *, year: int, month: int, rights: Rights
) -> Package:
    validate_period(year, month)
    period = await get_period(db, year, month)
    if period is None or period.status != "closed":
        raise PayrollConflict(
            "Paczka dla Symfonii powstaje z zamkniętego miesiąca płac — "
            "najpierw zamknij miesiąc.",
            code="period_open",
        )
    settings = await load_settings(db)
    package = Package(year=year, month=month, rights=rights)
    facts = await _people(db, period.id)
    forms = (UOP, MANDATE)
    for person in sorted(facts.values(), key=lambda p: p.name.casefold()):
        if person.employment_type in forms and not person.symfonia_id:
            package.todo.append(
                f"{person.name}: brak identyfikatora z Symfonii w danych do rozliczeń "
                "— osoba nie trafiła do plików."
            )
    first, last = month_start(year, month), month_end(year, month)

    if rights.events:
        employees = _without_namesakes(_identified(facts, (UOP,)), package)
        await _leave_events(db, employees, settings, first, last, package)
        await _overtime_events(db, employees, settings, year, month, package)
        package.events.sort(
            key=lambda e: (e.person.surname, e.person.given_name, e.begin)
        )
    else:
        package.notes.append(
            "Plik zdarzeń (nieobecności i nadgodziny) pobiera osoba z uprawnieniem "
            "„Kadry” — rodzaj nieobecności widzą tylko Kadry."
        )
    if rights.amounts:
        await _bonuses(db, _identified(facts, (UOP,)), settings, year, month, package)
        await _mandates(
            db,
            period.id,
            _identified(facts, (MANDATE,)),
            facts,
            settings,
            year,
            month,
            package,
        )
    else:
        package.notes.append(
            "Premie i rozliczenia zleceń (kwoty) pobiera osoba z uprawnieniem „Płace”."
        )
    b2b = sum(1 for p in facts.values() if p.employment_type == B2B)
    if b2b:
        package.notes.append(
            f"B2B ({b2b} os.) nie idzie do Symfonii — faktury rozlicza księgowość."
        )
    package.todo.extend(_lifecycle_todo(facts, year, month))
    package.counts["people"] = sum(
        1 for p in facts.values() if p.employment_type in forms
    )
    return package


# ── Paczka ────────────────────────────────────────────────────────────────────


def _summary(package: Package, author: str, files: list[SummaryFile]) -> Summary:
    period = label(package.year, package.month)
    settings_steps = []
    if any(f.name.startswith("zdarzenia_") for f in files):
        settings_steps.append(
            "Firma › Import zdarzeń → wskaż plik zdarzenia_… .xml (nieobecności i nadgodziny)."
        )
    if any(f.name.startswith("premie_") for f in files):
        settings_steps.append(
            "Firma › Import › danych z Excela → szablon danych kadrowych → premie_… .xlsx "
            "(„Importuj daty z pliku”)."
        )
    if any(f.name.startswith("zlecenia_") for f in files):
        settings_steps.append(
            "Firma › Import › danych z Excela → szablon rozliczeń UCP → "
            "zlecenia_rozliczenia_… .xlsx (z opcją „Realizuj zdarzenia wstawione podczas importu”)."
        )
    totals = [
        (name, f"{amount_text(value)} zł")
        for name, value in sorted(package.totals.items())
    ]
    for key, text_ in (
        ("leave_events", "Nieobecności (zakresy dni)"),
        ("leave_half_days", "Nieobecności w pół dnia"),
        ("overtime_days", "Dni z nadgodzinami"),
    ):
        if package.counts.get(key):
            totals.append((text_, str(package.counts[key])))
    return Summary(
        title=f"Paczka dla Symfonii · {period}",
        generated_by=author,
        generated_at=local_now(),
        files=files,
        totals=totals,
        todo=list(dict.fromkeys(package.todo)),
        notes=package.notes,
        steps=settings_steps,
    )


async def build_zip(
    db: AsyncSession, package: Package, *, author: str
) -> tuple[str, bytes]:
    settings = await load_settings(db)
    stem = package.stem
    files: list[tuple[str, bytes]] = []
    described: list[SummaryFile] = []

    def add(name: str, content: bytes, description: str, rows: int) -> None:
        files.append((name, content))
        described.append(
            SummaryFile(
                name=name,
                description=description,
                rows=rows,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )

    if package.events:
        add(
            f"zdarzenia_{stem}.xml",
            symfonia_files.events_xml(package.events, export_date=business_today()),
            "Nieobecności i nadgodziny (umowa o pracę)",
            len(package.events),
        )
    if package.bonuses:
        content = await asyncio.to_thread(
            symfonia_files.bonuses_xlsx,
            package.bonuses,
            package.bonus_columns,
            first=month_start(package.year, package.month),
            last=month_end(package.year, package.month),
        )
        add(
            f"premie_{stem}.xlsx",
            content,
            "Premie przyznane w miesiącu (UoP)",
            len(package.bonuses),
        )
    if package.mandates:
        content = await asyncio.to_thread(
            symfonia_files.mandates_xlsx,
            package.mandates,
            contract_kind=settings.symfonia.contract_kind,
            payment_form=settings.symfonia.payment_form,
            period=f"{package.month:02d}/{package.year}",
        )
        add(
            f"zlecenia_rozliczenia_{stem}.xlsx",
            content,
            "Rozliczenia umów zlecenia (brutto)",
            len(package.mandates),
        )
    summary = _summary(package, author, described)
    pdf = await asyncio.to_thread(symfonia_files.summary_pdf, summary)
    files.append((f"zestawienie_{stem}.pdf", pdf))
    archive = await asyncio.to_thread(symfonia_files.zip_bytes, files)
    return f"symfonia-{stem}.zip", archive


def preview_payload(package: Package) -> dict[str, Any]:
    files = []
    if package.events:
        files.append(
            {"name": f"zdarzenia_{package.stem}.xml", "rows": len(package.events)}
        )
    if package.bonuses:
        files.append(
            {"name": f"premie_{package.stem}.xlsx", "rows": len(package.bonuses)}
        )
    if package.mandates:
        files.append(
            {
                "name": f"zlecenia_rozliczenia_{package.stem}.xlsx",
                "rows": len(package.mandates),
            }
        )
    files.append({"name": f"zestawienie_{package.stem}.pdf", "rows": None})
    payload: dict[str, Any] = {
        "year": package.year,
        "month": package.month,
        "label": label(package.year, package.month),
        "includes_events": package.rights.events,
        "includes_amounts": package.rights.amounts,
        "files": files,
        "people": package.counts.get("people", 0),
        "todo": list(dict.fromkeys(package.todo)),
        "notes": package.notes,
    }
    if package.rights.amounts:
        payload["totals"] = {
            name: str(value) for name, value in sorted(package.totals.items())
        }
    return payload


def record_export(db: AsyncSession, package: Package, *, actor_id: int) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="payroll_period",
        entity_id=package.stem,
        action="symfonia_exported",
        sensitivity="payroll",
        details={
            "year": package.year,
            "month": package.month,
            "events": len(package.events),
            "bonus_rows": len(package.bonuses),
            "mandate_rows": len(package.mandates),
            "todo": len(package.todo),
            "includes_events": package.rights.events,
            "includes_amounts": package.rights.amounts,
        },
    )


__all__ = [
    "Package",
    "Rights",
    "build_zip",
    "collect",
    "overtime_days",
    "preview_payload",
    "record_export",
    "rights_of",
]
