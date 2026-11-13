"""Status osoby w miesiącu z raportu T4T i faktury kontraktora (plan Nordei N1.3).

Czysta funkcja jak ``engine.compute``: bez bazy, bez dat systemowych. Liczy się
tylko status 2 (Approved); status 1 (Submitted) to godziny złożone, czekające
na line managera; 0 i 3 nie trafiają ani do jednych, ani do drugich.

Statusy (reguły z prezentacji rozliczeń, liczby września w planie):

* ``ok`` „Zgodne” — godziny zatwierdzone = godziny z faktury. Status 1
  zostawiony obok (konsultant przeniósł godziny, stary wpis wisi) daje uwagę.
* ``no_approval`` „Brak akceptacji” — zatwierdzone + złożone = faktura,
  ale status 1 jest też we wcześniejszym przedziale niż ostatni.
* ``waiting`` „Czekamy” — status 1 tylko w ostatnim przedziale miesiąca albo
  brakuje godzin, które zmieszczą się w ostatnim przedziale (dni robocze
  od jego początku do końca miesiąca × 8 h, bez świąt), a wcześniej
  nic nie czeka na akceptację.
* ``other_amount`` „Inna kwota” — faktura nie dzieli się na pełne godziny przy
  stawce z kontraktu: możliwy dodatek doliczony do godzin (polecenie,
  delegacja; odpowiedź rozliczeń R1 z 13.11), a nie twarda rozbieżność godzin.
* ``differs`` „Rozbieżność” — każda inna różnica godzin.
* ``no_invoice`` „Brak faktury” — osoba jest w raporcie, faktury kontraktora
  za miesiąc nie ma (albo nie da się policzyć jej godzin).
* ``not_in_report`` „Brak w raporcie” — faktura jest, osoby nie ma w raporcie.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional, Sequence

OK = "ok"
NO_APPROVAL = "no_approval"
WAITING = "waiting"
DIFFERS = "differs"
OTHER_AMOUNT = "other_amount"
NO_INVOICE = "no_invoice"
NOT_IN_REPORT = "not_in_report"
STATUSES = (OK, NO_APPROVAL, WAITING, DIFFERS, OTHER_AMOUNT, NO_INVOICE, NOT_IN_REPORT)

APPROVED = 2
SUBMITTED = 1
TOLERANCE = Decimal("0.01")
HOURS_PER_DAY = Decimal("8")
ZERO = Decimal("0")


@dataclass(frozen=True)
class Entry:
    project_no: Optional[str]
    period_start: date
    period_end: date
    hours: Decimal
    status: int


@dataclass(frozen=True)
class Period:
    start: date
    end: date


@dataclass(frozen=True)
class Week:
    start: date
    end: date
    approved: Decimal
    submitted: Decimal


@dataclass(frozen=True)
class ProjectWeeks:
    project_no: Optional[str]
    weeks: tuple[Week, ...]


@dataclass(frozen=True)
class Outcome:
    status: str
    approved: Decimal
    submitted: Decimal
    invoice: Optional[Decimal]
    #: Faktura minus zatwierdzone; ``None`` bez faktury.
    difference: Optional[Decimal]
    weeks: tuple[Week, ...]
    projects: tuple[ProjectWeeks, ...]
    notes: tuple[str, ...]


def _fmt(value: Decimal) -> str:
    text = f"{value.normalize():f}" if value == value.to_integral() else f"{value:.2f}"
    return text.replace(".", ",")


def _span(period: Period) -> str:
    return f"{period.start:%d}–{period.end:%d.%m}"


def weekdays(first: date, last: date) -> int:
    count, day = 0, first
    while day <= last:
        count += day.weekday() < 5
        day += timedelta(days=1)
    return count


def month_periods(
    entries: Iterable[Entry], first: date, last: date
) -> tuple[Period, ...]:
    """Przedziały T4T miesiąca z wierszy raportu (wszystkich wersji)."""

    found = {
        (e.period_start, e.period_end)
        for e in entries
        if first <= e.period_start <= last
    }
    return tuple(Period(s, e) for s, e in sorted(found))


def _weeks(entries: Sequence[Entry], periods: Sequence[Period]) -> tuple[Week, ...]:
    sums: dict[date, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for entry in entries:
        if entry.status == APPROVED:
            sums[entry.period_start][0] += entry.hours
        elif entry.status == SUBMITTED:
            sums[entry.period_start][1] += entry.hours
    known = {p.start for p in periods}
    extra = [
        Period(e.period_start, e.period_end)
        for e in entries
        if e.period_start not in known
    ]
    ordered = sorted({*periods, *extra}, key=lambda p: p.start)
    return tuple(
        Week(p.start, p.end, sums[p.start][0], sums[p.start][1]) for p in ordered
    )


def classify(
    entries: Sequence[Entry],
    invoice_hours: Optional[Decimal],
    periods: Sequence[Period],
    month_end: date,
    *,
    invoice_note: Optional[str] = None,
) -> Optional[Outcome]:
    """Status osoby; ``None``, gdy nie ma ani wierszy raportu, ani faktury."""

    if not entries and invoice_hours is None:
        return None
    weeks = _weeks(entries, periods)
    by_project: dict[Optional[str], list[Entry]] = defaultdict(list)
    for entry in entries:
        by_project[entry.project_no].append(entry)
    projects = tuple(
        ProjectWeeks(project, _weeks(items, periods))
        for project, items in sorted(by_project.items(), key=lambda kv: kv[0] or "")
    )
    approved = sum((w.approved for w in weeks), ZERO)
    submitted = sum((w.submitted for w in weeks), ZERO)
    last = periods[-1] if periods else None
    early_submitted = [
        w for w in weeks if w.submitted > 0 and (last is None or w.start != last.start)
    ]
    notes: list[str] = []
    if invoice_note:
        notes.append(invoice_note)

    def outcome(status: str) -> Outcome:
        difference = None if invoice_hours is None else invoice_hours - approved
        return Outcome(
            status,
            approved,
            submitted,
            invoice_hours,
            difference,
            weeks,
            projects,
            tuple(notes),
        )

    if not entries:
        return outcome(NOT_IN_REPORT)
    if invoice_hours is None:
        return outcome(NO_INVOICE)
    if abs(approved - invoice_hours) <= TOLERANCE:
        if submitted > 0:
            spans = ", ".join(
                _span(Period(w.start, w.end)) for w in weeks if w.submitted > 0
            )
            notes.append(f"Wisi status 1: {_fmt(submitted)} h ({spans}).")
        return outcome(OK)
    if abs(approved + submitted - invoice_hours) <= TOLERANCE:
        if early_submitted:
            spans = ", ".join(_span(Period(w.start, w.end)) for w in early_submitted)
            notes.append(f"Status 1 we wcześniejszym przedziale: {spans}.")
            return outcome(NO_APPROVAL)
        notes.append("Status 1 tylko w ostatnim przedziale.")
        return outcome(WAITING)
    missing = invoice_hours - approved - submitted
    if last is not None and missing > 0 and not early_submitted:
        in_last = next((w for w in weeks if w.start == last.start), None)
        reported_last = (in_last.approved + in_last.submitted) if in_last else ZERO
        room = weekdays(last.start, month_end) * HOURS_PER_DAY - reported_last
        if missing <= room:
            notes.append(
                f"Brakuje {_fmt(missing)} h, mieszczą się w ostatnim przedziale "
                f"({_span(last)})."
            )
            return outcome(WAITING)
    if abs(invoice_hours - invoice_hours.to_integral_value()) > TOLERANCE:
        notes.append(
            f"Faktura daje {_fmt(invoice_hours)} h przy stawce z kontraktu: "
            "możliwy dodatek (polecenie, delegacja)."
        )
        return outcome(OTHER_AMOUNT)
    if missing < 0:
        notes.append(f"Raport ma o {_fmt(-missing)} h więcej niż faktura.")
    else:
        notes.append(f"Faktura ma o {_fmt(missing)} h więcej niż raport.")
    return outcome(DIFFERS)
