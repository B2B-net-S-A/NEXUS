"""Terminy wejścia i odejścia — czyste funkcje (bez bazy).

* Termin zadania = data startu (wejście) albo ostatni dzień pracy (odejście)
  przesunięta o N DNI ROBOCZYCH firmy (weekendy, święta ustawowe i dni wolne
  firmy pomijane). „2 dni robocze przed startem w poniedziałek 2.11” to
  czwartek 29.10 — piątek 30.10 jest pierwszym dniem wstecz.
* Przekazanie pracy wykonuje się od 18:00 ostatniego dnia pracy (czas
  Warszawy) — do tej pory osoba pracuje normalnie.
* Konto wyłącza się w dniu następującym po ostatnim dniu pracy (dzień
  kalendarzowy firmy, od północy czasu Warszawy).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.services.hr.calendar import WorkCalendar

#: Godzina przekazania pracy w ostatnim dniu (czas Warszawy).
HANDOVER_HOUR = time(18, 0)

#: Bezpiecznik pętli przesunięcia (najdłuższa przerwa między dniami roboczymi
#: to kilka dni; ``max offset`` w szablonie to 120 dni roboczych).
_MAX_STEPS = 400


def shift_working_days(calendar: WorkCalendar, anchor: date, offset: int) -> date:
    """``anchor`` przesunięty o ``offset`` dni roboczych (ujemny = wstecz).

    ``offset == 0`` zwraca sam dzień kotwicy, nawet gdy wypada w dzień wolny —
    to data wybrana przez Kadry, nie wyliczona.
    """

    if offset == 0:
        return anchor
    step = timedelta(days=1 if offset > 0 else -1)
    remaining = abs(offset)
    current = anchor
    for _ in range(_MAX_STEPS):
        current += step
        if calendar.is_working_day(current):
            remaining -= 1
            if remaining == 0:
                return current
    return current


def calendar_window(anchor: date) -> tuple[date, date]:
    """Zakres dni wolnych firmy potrzebny do przesunięć od ``anchor``."""

    return anchor - timedelta(days=120), anchor + timedelta(days=200)


def deactivate_on_for(last_working_day: date) -> date:
    """Dzień wyłączenia konta: następny dzień kalendarzowy po ostatnim dniu."""

    return last_working_day + timedelta(days=1)


def handover_moment(last_working_day: date, tz: str = DEFAULT_TZ) -> datetime:
    """Chwila przekazania pracy: 18:00 ostatniego dnia, czas Warszawy."""

    return datetime.combine(last_working_day, HANDOVER_HOUR, tzinfo=ZoneInfo(tz))


def handover_due(last_working_day: date, now: datetime) -> bool:
    """Czy wolno już przekazać pracę (``now`` musi znać strefę)."""

    return now >= handover_moment(last_working_day)


def deactivation_due(deactivate_on: date, today: date) -> bool:
    """Czy to już dzień wyłączenia konta (``today`` = kalendarz firmy)."""

    return today >= deactivate_on
