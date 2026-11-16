"""Pensja miesięczna UoP, wynagrodzenie chorobowe, urlopowe i ekwiwalent (K7b).

Czyste funkcje, bez bazy i bez zegara. ``month_pay`` liczy brutto jednej osoby
na umowie o pracę ze stałą pensją miesięczną w jednym miesiącu pracy:

* **Pensja za przepracowaną część miesiąca** (rozporządzenie MPiPS z 29.05.1996,
  Dz.U. 2017 poz. 927): najpierw nieobecność bez prawa do wynagrodzenia
  (urlop bezpłatny, wychowawczy, opiekuńczy z art. 173¹ KP, okres wyczekiwania
  na chorobowe, dni poza umową) — pensja / godziny wymiaru × godziny
  nieobecności (§ 12), potem choroba i zasiłki — pensja / 30 × dni
  kalendarzowe (§ 11, także dni zasiłku z ZUS i macierzyńskiego). Każde
  potrącenie do grosza. Cały miesiąc na L4 albo zasiłku = 0 zł pensji.
* **Wymiar czasu pracy** (art. 130 KP): 8 h × etat × dni od poniedziałku do
  piątku, minus 8 h × etat za każde święto przypadające w innym dniu niż
  niedziela (także w sobotę). Dzień wolny firmy nie obniża wymiaru.
* **Wynagrodzenie chorobowe** (art. 92 KP, ustawa zasiłkowa z 25.06.1999):
  80% podstawy (100% przy oznaczeniu Płac: ciąża, wypadek w drodze, dawstwo),
  za dni kalendarzowe niezdolności, do 33 dni w roku kalendarzowym (14 dni od
  roku po roku 50. urodzin), po okresie wyczekiwania (30 dni nieprzerwanego
  ubezpieczenia, art. 4; zwolnienie osoby albo L4 z oznaczeniem Płac).
  Kolejne dni to zasiłek z ZUS — firma do 20 ubezpieczonych nie jest płatnikiem
  zasiłków (art. 61), na liście 0 zł i problem „Z-3”. Stawka dzienna =
  podstawa × procent / 30, do grosza.
* **Podstawa chorobowego** (art. 36–38, 43, 45): przeciętne miesięczne
  wynagrodzenie z 12 pełnych miesięcy kalendarzowych przed miesiącem początku
  niezdolności, po odjęciu składek pracownika (13,71% przy obecnych stawkach).
  Miesiąc, w którym przepracowano mniej niż połowę wymiaru, wypada (chyba że
  wszystkie są takie); niepełny miesiąc uzupełnia się — stałe do kwoty za
  pełny miesiąc, zmienne proporcjonalnie do godzin. Bez pełnego miesiąca —
  pensja (art. 37 ust. 1). Nie mniej niż płaca minimalna × etat po odjęciu
  składek (art. 45). Przerwa krótsza niż 3 miesiące od poprzedniej
  niezdolności = ta sama podstawa (art. 43). Premie z placementów i Ligi są
  poza podstawą (decyzja Artura 16.11.2026: art. 41 — osoba zachowuje do nich
  prawo w czasie choroby).
* **Urlopowe za składniki zmienne** (rozporządzenie MPiPS z 08.01.1997, § 8–9):
  zmienne z 3 miesięcy przed miesiącem początku urlopu / godziny faktycznie
  przepracowane w nich × godziny urlopu (8 h × etat na dzień). Stała pensja
  w urlopie się nie zmniejsza. Premie za osiągnięcie poza średnią (§ 6 pkt 1).
  Siła wyższa (art. 148¹ KP) — połowa wynagrodzenia.
* **Ekwiwalent** (art. 171 KP, § 14–19): (pensja + średnia zmiennych z 3
  miesięcy) / (współczynnik urlopowy × etat) = za dzień; / 8 = za godzinę;
  × 8 h × niewykorzystane dni. Urlop w roku odejścia proporcjonalnie do
  miesięcy pracy u tego pracodawcy, miesiąc i dzień w górę (art. 155¹, 155²ᵃ).

Ręcznie (kwota Płac) zostają: nadgodziny UoP, zasiłki wypłacane przez płatnika
(gdy firma przekroczy 20 ubezpieczonych), zmiana etatu w okresie podstawy
(art. 40), składniki za okresy dłuższe niż miesiąc (art. 42).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from app.core.scheduling import _polish_holidays
from app.services.hr.payroll_lists.params import Params

ZERO = Decimal("0")
CENT = Decimal("0.01")
HOURS_PER_DAY = Decimal("8")
THIRTY = Decimal("30")
HUNDRED = Decimal("100")

SICK_RATES: tuple[str, ...] = ("80", "100", "zus")
#: Urlopy płatne „jak urlop wypoczynkowy” — stała pensja bez zmian, zmienne ze średniej.
LEAVE_PAY_TYPES: frozenset[str] = frozenset(
    {"vacation", "on_demand", "occasional", "childcare", "blood_donation", "training"}
)
#: Nieobecność płatna bez urlopowego za zmienne (dzień za święto w sobotę).
PAID_PLAIN_TYPES: frozenset[str] = frozenset({"holiday_in_lieu"})
#: Bez prawa do wynagrodzenia — pensja metodą godzinową (§ 12).
UNPAID_TYPES: frozenset[str] = frozenset({"unpaid_leave", "care_leave", "childrearing"})
#: Zasiłek z ZUS za cały okres — pensja metodą 1/30 (§ 11 ust. 2).
BENEFIT_TYPES: frozenset[str] = frozenset({"maternity", "paternity", "parental_leave"})
HALF_PAY_TYPES: frozenset[str] = frozenset({"force_majeure"})
SICK_TYPE = "sick_leave"

#: Oznaczenia wyniku → zdanie na ekranie (bez kwot i danych o zdrowiu w treści).
NOTE_LABELS: dict[str, str] = {
    "salary": "Pensja miesięczna z kartoteki płac.",
    "salary_reduced": "Pensja za przepracowaną część miesiąca (§ 11–12 rozporządzenia).",
    "sick_pay": "Wynagrodzenie chorobowe (art. 92 KP) — bez składek ZUS, ze zdrowotną i PIT.",
    "sick_waiting": "Okres wyczekiwania — za te dni L4 bez wynagrodzenia chorobowego.",
    "sick_zus": "Dni zasiłku z ZUS (limit dni pracodawcy w roku wyczerpany albo zasiłek od 1. dnia).",
    "sick_base_salary": "Podstawa chorobowego z pensji — brak pełnego miesiąca w historii (art. 37).",
    "sick_base_all_months": "Każdy miesiąc z historii poniżej połowy wymiaru — podstawa ze wszystkich (art. 38).",
    "sick_base_minimum": "Podstawa chorobowego podniesiona do płacy minimalnej po składkach (art. 45).",
    "sick_base_reused": "Przerwa krótsza niż 3 miesiące od poprzedniego L4 — ta sama podstawa (art. 43).",
    "leave_variable": "Urlopowe za składniki zmienne ze średniej z 3 miesięcy (§ 8–9).",
    "leave_variable_no_hours": "Brak przepracowanych godzin w 3 miesiącach — urlopowe za zmienne 0 zł.",
    "half_pay": "Zwolnienie z powodu siły wyższej — połowa wynagrodzenia (art. 148¹ KP).",
    "equivalent": "Ekwiwalent za niewykorzystany urlop (art. 171 KP).",
    "equivalent_overused": "Wykorzystano więcej urlopu niż przysługuje w roku odejścia — ekwiwalentu nie ma.",
    "absence_other": "Nieobecność rodzaju „inna” — pensja bez zmian; sprawdź, czy płatna.",
}


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def iter_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, nxt - timedelta(days=1)


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def is_holiday(day: date) -> bool:
    return day in _polish_holidays(day.year)


def wymiar_days(start: date, end: date) -> int:
    """Dni wymiaru: pon.–pt. minus święta w dni od poniedziałku do soboty."""

    if end < start:
        return 0
    weekdays = 0
    reductions = 0
    for day in iter_days(start, end):
        if day.weekday() < 5:
            weekdays += 1
        if day.weekday() < 6 and is_holiday(day):
            reductions += 1
    return max(0, weekdays - reductions)


def nominal_hours(start: date, end: date, fte: Decimal) -> Decimal:
    return HOURS_PER_DAY * fte * wymiar_days(start, end)


def is_wymiar_day(day: date) -> bool:
    return day.weekday() < 5 and not is_holiday(day)


def leave_coefficient(year: int) -> Decimal:
    """Współczynnik urlopowy roku (§ 19): dni pracy w pięciodniowym tygodniu / 12."""

    first, last = date(year, 1, 1), date(year, 12, 31)
    return money(Decimal(wymiar_days(first, last)) / 12)


# ── Wejście ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Absence:
    """Zatwierdzona nieobecność z modułu urlopów (rodzaj tylko do liczenia)."""

    key: str
    leave_type: str
    start: date
    end: date
    #: Dni robocze wniosku z ułamkiem (``leave_request_days``, aktywne).
    days: tuple[tuple[date, Decimal], ...] = ()
    #: L4: „80”, „100” albo „zus” (zasiłek z ZUS od 1. dnia — np. opieka).
    sick_rate: str = "80"
    waiting_exempt: bool = False


@dataclass(frozen=True)
class BasisMonth:
    """Miesiąc historii podstaw (import z Enovy albo zatwierdzona lista NEXUSA)."""

    year: int
    month: int
    fixed_paid: Decimal
    fixed_full: Decimal
    variable: Decimal
    nominal_hours: Decimal
    worked_hours: Decimal
    paid_hours: Decimal
    leave_variable: Decimal = ZERO
    full_month: bool = True
    source: str = "enova"

    @property
    def sick_amount(self) -> Decimal:
        return self.fixed_paid + self.variable + self.leave_variable


@dataclass(frozen=True)
class PreviousSick:
    """Ostatnia niezdolność z podstawą (art. 43)."""

    last_day: date
    base: Decimal


@dataclass(frozen=True)
class MonthInput:
    year: int
    month: int
    monthly_salary: Decimal
    fte: Decimal
    employed_from: date
    employed_to: date
    #: Początek zatrudnienia u płatnika (pełne miesiące do podstawy).
    hired_on: date
    #: Nieprzerwane ubezpieczenie chorobowe od (okres wyczekiwania).
    insured_since: date
    waiting_exempt: bool = False
    birth_date: Optional[date] = None
    absences: tuple[Absence, ...] = ()
    #: Składniki zmienne miesiąca wpisane przez Płace (w podstawach).
    variable: Decimal = ZERO
    #: Inne składniki poza podstawami (nagroda) i premie z „Mojego miesiąca”.
    other: Decimal = ZERO
    bonuses: Decimal = ZERO
    history: tuple[BasisMonth, ...] = ()
    previous_sick: Optional[PreviousSick] = None
    #: Dni wynagrodzenia chorobowego wykorzystane przed tym miesiącem: rok → dni.
    sick_days_used: tuple[tuple[int, int], ...] = ()
    #: Niewykorzystane dni urlopu do ekwiwalentu (umowa kończy się w miesiącu).
    equivalent_days: Decimal = ZERO
    #: Podstawa chorobowego wpisana przez Płace (zastępuje wyliczoną).
    sick_base_override: Optional[Decimal] = None


@dataclass(frozen=True)
class SickPart:
    absence_key: str
    rate: Decimal
    base: Decimal
    daily: Decimal
    paid_days: int
    zus_days: int
    waiting_days: int
    amount: Decimal
    first_day: Optional[date]
    last_day: Optional[date]

    def to_json(self) -> dict[str, object]:
        return {
            "absence": self.absence_key,
            "rate": str(self.rate),
            "base": str(self.base),
            "daily": str(self.daily),
            "paid_days": self.paid_days,
            "zus_days": self.zus_days,
            "waiting_days": self.waiting_days,
            "amount": str(self.amount),
            "first_day": self.first_day.isoformat() if self.first_day else None,
            "last_day": self.last_day.isoformat() if self.last_day else None,
        }


@dataclass(frozen=True)
class MonthPay:
    gross: Decimal
    salary_part: Decimal
    sick_pay: Decimal
    leave_variable: Decimal
    equivalent: Decimal
    variable: Decimal
    other: Decimal
    bonuses: Decimal
    #: Podstawa FP w przeliczeniu na pełny miesiąc.
    fund_basis: Decimal
    nominal_hours: Decimal
    worked_hours: Decimal
    paid_hours: Decimal
    sick: tuple[SickPart, ...]
    sick_days_by_year: tuple[tuple[int, int], ...]
    zus_days: int
    notes: tuple[str, ...]
    problems: tuple[str, ...]
    #: Ten miesiąc jako wiersz historii podstaw (do kolejnych miesięcy).
    basis: BasisMonth
    reductions: dict[str, str] = field(default_factory=dict)

    @property
    def social_exempt(self) -> Decimal:
        return self.sick_pay

    def to_json(self) -> dict[str, object]:
        return {
            "gross": str(self.gross),
            "salary_part": str(self.salary_part),
            "sick_pay": str(self.sick_pay),
            "leave_variable": str(self.leave_variable),
            "equivalent": str(self.equivalent),
            "variable": str(self.variable),
            "other": str(self.other),
            "bonuses": str(self.bonuses),
            "fund_basis": str(self.fund_basis),
            "nominal_hours": str(self.nominal_hours),
            "worked_hours": str(self.worked_hours),
            "paid_hours": str(self.paid_hours),
            "sick": [part.to_json() for part in self.sick],
            "sick_days_by_year": {str(y): d for y, d in self.sick_days_by_year},
            "zus_days": self.zus_days,
            "notes": list(self.notes),
            "problems": list(self.problems),
            "reductions": self.reductions,
            "basis": basis_to_json(self.basis),
        }


def basis_to_json(row: BasisMonth) -> dict[str, object]:
    return {
        "year": row.year,
        "month": row.month,
        "fixed_paid": str(row.fixed_paid),
        "fixed_full": str(row.fixed_full),
        "variable": str(row.variable),
        "leave_variable": str(row.leave_variable),
        "nominal_hours": str(row.nominal_hours),
        "worked_hours": str(row.worked_hours),
        "paid_hours": str(row.paid_hours),
        "full_month": row.full_month,
        "source": row.source,
    }


def basis_from_json(raw: dict[str, object]) -> BasisMonth:
    def num(name: str) -> Decimal:
        return Decimal(str(raw.get(name) or "0"))

    return BasisMonth(
        year=int(str(raw["year"])),
        month=int(str(raw["month"])),
        fixed_paid=num("fixed_paid"),
        fixed_full=num("fixed_full"),
        variable=num("variable"),
        leave_variable=num("leave_variable"),
        nominal_hours=num("nominal_hours"),
        worked_hours=num("worked_hours"),
        paid_hours=num("paid_hours"),
        full_month=bool(raw.get("full_month", True)),
        source=str(raw.get("source") or "nexus"),
    )


# ── Podstawy ────────────────────────────────────────────────────────────────


def employee_social_rate(params: Params) -> Decimal:
    return (
        params.pension_employee_rate
        + params.disability_employee_rate
        + params.sickness_employee_rate
    )


def _after_contributions(amount: Decimal, params: Params) -> Decimal:
    return amount - money(amount * employee_social_rate(params) / HUNDRED)


def _window(
    history: Iterable[BasisMonth], year: int, month: int, months: int
) -> list[BasisMonth]:
    wanted = {shift_month(year, month, -n) for n in range(1, months + 1)}
    rows = {(row.year, row.month): row for row in history}
    return [rows[key] for key in sorted(wanted) if key in rows]


def _supplemented(row: BasisMonth) -> Decimal:
    """Miesiąc niepełny uzupełniony do pełnego (art. 38 ust. 2)."""

    if row.nominal_hours <= 0 or row.paid_hours >= row.nominal_hours:
        return row.sick_amount
    if row.paid_hours <= 0:
        return row.fixed_full
    variable = row.variable + row.leave_variable
    return row.fixed_full + money(variable * row.nominal_hours / row.paid_hours)


def sick_base(
    history: Iterable[BasisMonth],
    *,
    year: int,
    month: int,
    hired_on: date,
    monthly_salary: Decimal,
    fte: Decimal,
    params: Params,
) -> tuple[Decimal, list[str]]:
    """Podstawa chorobowego za pełny miesiąc (po składkach pracownika)."""

    notes: list[str] = []
    if hired_on.day == 1:
        first_full = hired_on
    else:
        first_full = date(*shift_month(hired_on.year, hired_on.month, 1), 1)
    rows = [
        row
        for row in _window(history, year, month, 12)
        if row.full_month and date(row.year, row.month, 1) >= first_full
    ]
    if not rows:
        base = _after_contributions(monthly_salary, params)
        notes.append("sick_base_salary")
    else:
        qualifying = [row for row in rows if row.paid_hours * 2 >= row.nominal_hours]
        if not qualifying:
            qualifying = rows
            notes.append("sick_base_all_months")
        total = sum(
            (_after_contributions(_supplemented(row), params) for row in qualifying),
            ZERO,
        )
        base = money(total / len(qualifying))
    minimum = _after_contributions(money(params.minimum_wage * fte), params)
    if base < minimum:
        base = minimum
        notes.append("sick_base_minimum")
    return base, notes


def sick_limit(birth_date: Optional[date], year: int, params: Params) -> int:
    """33 dni; 14 dni od roku kalendarzowego po roku 50. urodzin."""

    if birth_date is not None and birth_date.year + params.sick_pay_senior_age < year:
        return params.sick_pay_days_limit_senior
    return params.sick_pay_days_limit


def _variable_hourly(
    history: Iterable[BasisMonth], year: int, month: int
) -> Optional[Decimal]:
    rows = _window(history, year, month, 3)
    hours = sum((row.worked_hours for row in rows), ZERO)
    if hours <= 0:
        return None
    return money(sum((row.variable for row in rows), ZERO) / hours)


def _variable_average(history: Iterable[BasisMonth], year: int, month: int) -> Decimal:
    rows = _window(history, year, month, 3)
    if not rows:
        return ZERO
    return money(sum((row.variable for row in rows), ZERO) / len(rows))


def equivalent_amount(
    *,
    monthly_salary: Decimal,
    variable_average: Decimal,
    fte: Decimal,
    days: Decimal,
    params: Params,
) -> Decimal:
    """Ekwiwalent: za dzień = podstawa / współczynnik × etat, za godzinę / 8 (§ 18–19)."""

    if days <= 0:
        return ZERO
    coefficient = money(params.leave_coefficient * fte)
    if coefficient <= 0:
        return ZERO
    daily = money((monthly_salary + variable_average) / coefficient)
    hourly = money(daily / HOURS_PER_DAY)
    return money(hourly * HOURS_PER_DAY * days)


def unused_leave_days(
    *,
    entitlement: Decimal,
    carried_over: Decimal,
    used_before: Decimal,
    used_paid: Decimal,
    year: int,
    employed_from: date,
    employed_to: date,
) -> tuple[Decimal, bool]:
    """Niewykorzystane dni w roku odejścia (art. 155¹: proporcjonalnie, w górę).

    Zwraca (dni, przekroczony) — ``True`` gdy wykorzystano więcej, niż przysługuje.
    """

    start = max(employed_from, date(year, 1, 1))
    end = min(employed_to, date(year, 12, 31))
    if end < start:
        months = 0
    else:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
    proportional = (
        Decimal(math.ceil(entitlement * months / 12)) if entitlement > 0 else ZERO
    )
    proportional = min(proportional, entitlement)
    left = proportional + carried_over - used_before - used_paid
    if left < 0:
        return ZERO, True
    return left, False


# ── Miesiąc ─────────────────────────────────────────────────────────────────


def _clip(absence: Absence, start: date, end: date) -> list[date]:
    lo = max(absence.start, start)
    hi = min(absence.end, end)
    return iter_days(lo, hi) if hi >= lo else []


def month_pay(data: MonthInput, params: Params) -> MonthPay:
    if data.monthly_salary < 0 or not ZERO < data.fte <= 1:
        raise ValueError("pensja ujemna albo etat spoza (0, 1]")
    first, last = month_bounds(data.year, data.month)
    emp_from = max(first, data.employed_from)
    emp_to = min(last, data.employed_to)
    if emp_to < emp_from:
        raise ValueError("osoba nie była zatrudniona w miesiącu")
    notes: list[str] = []
    problems: list[str] = []
    fte = data.fte
    day_hours = HOURS_PER_DAY * fte
    salary = money(data.monthly_salary)
    nominal = nominal_hours(first, last, fte)
    outside_hours = nominal_hours(
        first, emp_from - timedelta(days=1), fte
    ) + nominal_hours(emp_to + timedelta(days=1), last, fte)

    unpaid_hours = ZERO
    half_hours = ZERO
    thirtieth: set[date] = set()
    sick_hours = ZERO
    paid_leave_hours = ZERO
    leave_hours_by_absence: list[tuple[Absence, Decimal, Decimal]] = []
    sick_parts: list[SickPart] = []
    used = dict(data.sick_days_used)
    zus_total = 0
    previous = data.previous_sick
    waiting_end = data.insured_since + timedelta(days=params.waiting_period_days)

    for absence in sorted(data.absences, key=lambda item: (item.start, item.key)):
        kind = absence.leave_type
        if kind == SICK_TYPE:
            days = _clip(absence, emp_from, emp_to)
            if not days:
                continue
            if absence.sick_rate not in SICK_RATES:
                raise ValueError(f"nieznana stawka L4: {absence.sick_rate!r}")
            paid_days: list[date] = []
            zus_days: list[date] = []
            waiting_days: list[date] = []
            exempt = data.waiting_exempt or absence.waiting_exempt
            for day in days:
                if absence.sick_rate == "zus":
                    zus_days.append(day)
                elif day < waiting_end and not exempt:
                    waiting_days.append(day)
                elif used.get(day.year, 0) < sick_limit(
                    data.birth_date, day.year, params
                ):
                    paid_days.append(day)
                    used[day.year] = used.get(day.year, 0) + 1
                else:
                    zus_days.append(day)
            thirtieth.update(paid_days)
            thirtieth.update(zus_days)
            unpaid_hours += day_hours * sum(
                1 for day in waiting_days if is_wymiar_day(day)
            )
            sick_hours += day_hours * sum(
                1 for day in days if is_wymiar_day(day) and day not in waiting_days
            )
            zus_total += len(zus_days)
            if waiting_days:
                notes.append("sick_waiting")
            if zus_days:
                notes.append("sick_zus")
            base = ZERO
            daily = ZERO
            amount = ZERO
            rate = (
                Decimal("100") if absence.sick_rate == "100" else params.sick_pay_rate
            )
            if paid_days:
                if data.sick_base_override is not None:
                    base = money(data.sick_base_override)
                elif previous is not None and absence.start <= _plus_months(
                    previous.last_day, 3
                ):
                    base = previous.base
                    notes.append("sick_base_reused")
                else:
                    base, base_notes = sick_base(
                        data.history,
                        year=absence.start.year,
                        month=absence.start.month,
                        hired_on=data.hired_on,
                        monthly_salary=salary,
                        fte=fte,
                        params=params,
                    )
                    notes.extend(base_notes)
                daily = money(base * rate / HUNDRED / THIRTY)
                amount = money(daily * len(paid_days))
                notes.append("sick_pay")
                previous = PreviousSick(last_day=paid_days[-1], base=base)
            elif previous is not None and days:
                # Dni bez wynagrodzenia też przedłużają ciągłość niezdolności (art. 43).
                previous = PreviousSick(last_day=days[-1], base=previous.base)
            sick_parts.append(
                SickPart(
                    absence_key=absence.key,
                    rate=rate,
                    base=base,
                    daily=daily,
                    paid_days=len(paid_days),
                    zus_days=len(zus_days),
                    waiting_days=len(waiting_days),
                    amount=amount,
                    first_day=days[0],
                    last_day=days[-1],
                )
            )
            continue
        if kind in BENEFIT_TYPES:
            days = _clip(absence, emp_from, emp_to)
            thirtieth.update(days)
            sick_hours += day_hours * sum(1 for day in days if is_wymiar_day(day))
            zus_total += len(days)
            if days:
                notes.append("sick_zus")
            continue
        in_month = [
            (day, fraction)
            for day, fraction in absence.days
            if emp_from <= day <= emp_to and is_wymiar_day(day)
        ]
        hours = sum((day_hours * fraction for _day, fraction in in_month), ZERO)
        if kind in UNPAID_TYPES:
            unpaid_hours += hours
        elif kind in HALF_PAY_TYPES:
            half_hours += hours
            paid_leave_hours += hours
            if hours:
                notes.append("half_pay")
            leave_hours_by_absence.append((absence, hours, Decimal("0.5")))
        elif kind in LEAVE_PAY_TYPES:
            paid_leave_hours += hours
            leave_hours_by_absence.append((absence, hours, Decimal("1")))
        elif kind in PAID_PLAIN_TYPES:
            paid_leave_hours += hours
        else:
            paid_leave_hours += hours
            if hours:
                notes.append("absence_other")

    # ── Pensja za przepracowaną część (§ 12, potem § 11) ─────────────────────
    reductions: dict[str, str] = {}
    hourly_cut = ZERO
    if nominal > 0:
        hourly_cut = money(salary / nominal * (outside_hours + unpaid_hours))
        hourly_cut += money(salary / nominal * half_hours / 2)
    thirtieth_cut = money(salary / THIRTY * len(thirtieth))
    employed_days = (emp_to - emp_from).days + 1
    if thirtieth and len(thirtieth) >= employed_days:
        salary_part = ZERO
    else:
        salary_part = max(ZERO, salary - hourly_cut - thirtieth_cut)
    if hourly_cut:
        reductions["hours"] = str(hourly_cut)
    if thirtieth_cut:
        reductions["thirtieth"] = str(thirtieth_cut)
    notes.append("salary_reduced" if salary_part != salary else "salary")

    # ── Urlopowe za zmienne (§ 8–9) ──────────────────────────────────────────
    leave_variable = ZERO
    for absence, hours, share in leave_hours_by_absence:
        if hours <= 0:
            continue
        hourly = _variable_hourly(data.history, absence.start.year, absence.start.month)
        if hourly is None:
            if any(
                row.variable
                for row in _window(
                    data.history, absence.start.year, absence.start.month, 3
                )
            ):
                notes.append("leave_variable_no_hours")
            continue
        part = money(hourly * hours * share)
        if part:
            leave_variable += part
            notes.append("leave_variable")

    # ── Ekwiwalent (art. 171) ────────────────────────────────────────────────
    equivalent = ZERO
    if data.equivalent_days > 0:
        equivalent = equivalent_amount(
            monthly_salary=salary,
            variable_average=_variable_average(data.history, data.year, data.month),
            fte=fte,
            days=data.equivalent_days,
            params=params,
        )
        if equivalent:
            notes.append("equivalent")

    sick_pay = sum((part.amount for part in sick_parts), ZERO)
    variable = money(data.variable)
    other = money(data.other)
    bonuses = money(data.bonuses)
    if zus_total and params.benefit_payer:
        problems.append("benefit_payer_manual")
    elif zus_total:
        problems.append("z3_needed")
    gross = (
        salary_part
        + sick_pay
        + leave_variable
        + equivalent
        + variable
        + other
        + bonuses
    )
    worked = max(
        ZERO,
        nominal - outside_hours - unpaid_hours - sick_hours - paid_leave_hours,
    )
    paid = max(ZERO, nominal - outside_hours - unpaid_hours - sick_hours)
    basis = BasisMonth(
        year=data.year,
        month=data.month,
        fixed_paid=salary_part,
        fixed_full=salary,
        variable=variable,
        leave_variable=leave_variable,
        nominal_hours=nominal,
        worked_hours=worked,
        paid_hours=paid,
        full_month=emp_from == first and emp_to == last and data.hired_on <= first,
        source="nexus",
    )
    return MonthPay(
        gross=gross,
        salary_part=salary_part,
        sick_pay=sick_pay,
        leave_variable=leave_variable,
        equivalent=equivalent,
        variable=variable,
        other=other,
        bonuses=bonuses,
        fund_basis=salary + variable,
        nominal_hours=nominal,
        worked_hours=worked,
        paid_hours=paid,
        sick=tuple(sick_parts),
        sick_days_by_year=tuple(sorted(used.items())),
        zus_days=zus_total,
        notes=tuple(dict.fromkeys(notes)),
        problems=tuple(dict.fromkeys(problems)),
        basis=basis,
        reductions=reductions,
    )


def _plus_months(day: date, months: int) -> date:
    year, month = shift_month(day.year, day.month, months)
    last = month_bounds(year, month)[1]
    return date(year, month, min(day.day, last.day))


__all__ = [
    "Absence",
    "BasisMonth",
    "LEAVE_PAY_TYPES",
    "MonthInput",
    "MonthPay",
    "NOTE_LABELS",
    "PreviousSick",
    "SICK_RATES",
    "SickPart",
    "basis_from_json",
    "basis_to_json",
    "equivalent_amount",
    "leave_coefficient",
    "month_pay",
    "nominal_hours",
    "sick_base",
    "sick_limit",
    "unused_leave_days",
    "wymiar_days",
]
