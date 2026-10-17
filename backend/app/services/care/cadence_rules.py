"""Rytm kontaktu z konsultantem (etap 3, O7–O9, 17.10.2026) — reguły bez bazy.

Poziomy (``LEVELS``): co 2 tygodnie, co miesiąc, co kwartał, tylko kamienie
i wstrzymany. Bez żadnej zmiany obowiązuje program z Compassa: pierwsze
90 dni od startu kontraktu co 2 tygodnie (``program``), potem co miesiąc
(``default``).

Zmiana rytmu to okres (``care_cadence_periods``): od dnia zmiany, opcjonalnie
„do kiedy”. W danym dniu obowiązuje okres, który go obejmuje i zaczął się
najpóźniej (remis — zapisany później). Po dacie „do kiedy” wraca więc to, co
obowiązywało przed zmianą, a nie domyślny rytm — „na chwilę częściej” nie
zostaje na zawsze.

Terminy rozmów liczy się od początku każdego odcinka o stałym poziomie
(start kontraktu, dzień 90, dzień zmiany, dzień po „do kiedy”): odcinek
„co 2 tygodnie” od 15.10 daje 29.10, 12.11… Sąsiednie odcinki o tym samym
poziomie są jednym odcinkiem — „co miesiąc” ustawione przy domyślnym „co
miesiąc” nie przesuwa terminów. Kamienie (dzień 7 po starcie i 30 dni przed
końcem) dokłada ``plan.slots_between`` przy każdym poziomie, także przy
wstrzymaniu.

Sygnały tylko podpowiadają częstszy kontakt (O9) — rytm zmienia człowiek.
"""

from __future__ import annotations

import calendar
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Protocol

from app.services.contract_care_schema import CADENCE_LEVELS

LEVELS: tuple[str, ...] = CADENCE_LEVELS
#: Poziomy z rozmowami w stałym odstępie: (dni, miesiące).
REGULAR_STEPS: dict[str, tuple[int, int]] = {
    "biweekly": (14, 0),
    "monthly": (0, 1),
    "quarterly": (0, 3),
}
PROGRAM_DAYS = 90
PROGRAM_LEVEL = "biweekly"
DEFAULT_LEVEL = "monthly"
#: Sygnały, przy których podpowiadamy częstszy kontakt. Zaległa rozmowa to
#: telefon, nie zmiana rytmu, więc jej tu nie ma.
RAISING_SIGNALS: frozenset[str] = frozenset(
    {"weak_feedback", "order_end", "wants_change", "attrition_risk"}
)


class PeriodLike(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def level(self) -> str: ...

    @property
    def starts_on(self) -> date: ...

    @property
    def until_on(self) -> Optional[date]: ...


@dataclass(frozen=True)
class CadencePeriod:
    """Okres rytmu bez bazy (podgląd zmiany, testy); wiersz ORM ma te same pola."""

    id: int
    level: str
    starts_on: date
    until_on: Optional[date] = None


@dataclass(frozen=True)
class Effective:
    level: str
    source: str  # program | default | period
    period: Optional[PeriodLike] = None
    #: Ostatni dzień: okresu z datą „do kiedy” albo programu pierwszych 90 dni.
    until_on: Optional[date] = None


def add_months(day: date, months: int) -> date:
    """Ten sam dzień miesiąca ``months`` później (31.01 + 1 = 28/29.02)."""

    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def program_end(start: date) -> date:
    """Pierwszy dzień po programie „co 2 tygodnie” (dzień 90 od startu)."""

    return start + timedelta(days=PROGRAM_DAYS)


def _covering(periods: Iterable[PeriodLike], day: date) -> Optional[PeriodLike]:
    covering = [
        period
        for period in periods
        if period.starts_on <= day
        and (period.until_on is None or day <= period.until_on)
    ]
    return max(covering, key=lambda p: (p.starts_on, p.id), default=None)


def level_on(start: date, periods: Iterable[PeriodLike], day: date) -> Effective:
    """Rytm obowiązujący w dniu ``day``."""

    period = _covering(periods, day)
    if period is not None:
        return Effective(period.level, "period", period, period.until_on)
    if day < program_end(start):
        return Effective(
            PROGRAM_LEVEL, "program", None, program_end(start) - timedelta(days=1)
        )
    return Effective(DEFAULT_LEVEL, "default", None, None)


def _change_points(
    start: date, periods: Sequence[PeriodLike], last: date
) -> list[date]:
    points = {start, program_end(start)}
    for period in periods:
        points.add(period.starts_on)
        if period.until_on is not None:
            points.add(period.until_on + timedelta(days=1))
    return sorted(point for point in points if start <= point <= last)


@dataclass(frozen=True)
class Segment:
    level: str
    starts_on: date
    #: Pierwszy dzień następnego odcinka (``None`` = do końca horyzontu).
    ends_before: Optional[date]


def segments(start: date, periods: Sequence[PeriodLike], last: date) -> list[Segment]:
    """Odcinki o stałym poziomie od startu do ``last`` (sąsiednie równe złączone)."""

    out: list[Segment] = []
    for point in _change_points(start, periods, last):
        level = level_on(start, periods, point).level
        if out and out[-1].level == level:
            continue
        if out:
            out[-1] = Segment(out[-1].level, out[-1].starts_on, point)
        out.append(Segment(level, point, None))
    return out


def _step(anchor: date, level: str, count: int) -> date:
    days, months = REGULAR_STEPS[level]
    if months:
        return add_months(anchor, months * count)
    return anchor + timedelta(days=days * count)


def regular_dates(start: date, periods: Sequence[PeriodLike], last: date) -> list[date]:
    """Terminy rozmów według rytmu od startu do ``last`` włącznie (bez kamieni)."""

    out: list[date] = []
    for segment in segments(start, periods, last):
        if segment.level not in REGULAR_STEPS:
            continue
        count = 1
        while True:
            due = _step(segment.starts_on, segment.level, count)
            if due > last or (
                segment.ends_before is not None and due >= segment.ends_before
            ):
                break
            out.append(due)
            count += 1
    return out


@dataclass(frozen=True)
class Transition:
    on: date
    kind: str  # start | program_end | change | return
    level: str
    period: Optional[PeriodLike] = None


def transitions(start: date, periods: Sequence[PeriodLike]) -> list[Transition]:
    """Historia rytmu: start, koniec programu, zmiany i powroty po „do kiedy”."""

    ordered = sorted(periods, key=lambda p: (p.starts_on, p.id))
    out = [Transition(start, "start", level_on(start, ordered, start).level)]
    end = program_end(start)
    before, after = (
        level_on(start, ordered, end - timedelta(days=1)),
        level_on(start, ordered, end),
    )
    if before.source == "program" and after.source == "default":
        out.append(Transition(end, "program_end", after.level))
    for period in ordered:
        out.append(Transition(period.starts_on, "change", period.level, period))
        if period.until_on is None:
            continue
        # Powrót tylko wtedy, gdy ten okres obowiązywał do swojej daty
        # (późniejsza zmiana mogła go zastąpić wcześniej).
        if level_on(start, ordered, period.until_on).period is not period:
            continue
        back = period.until_on + timedelta(days=1)
        returned = level_on(start, ordered, back)
        if returned.level != period.level:
            out.append(Transition(back, "return", returned.level, returned.period))
    order = {"start": 0, "program_end": 1, "return": 2, "change": 3}
    return sorted(out, key=lambda t: (t.on, order[t.kind]))


def suggested_level(level: str, signals: Collection[str]) -> Optional[str]:
    """Podpowiedź „podnieść rytm?” — tylko gdy są sygnały i rozmów jest rzadziej."""

    if level in ("biweekly", "paused") or not RAISING_SIGNALS.intersection(signals):
        return None
    return "biweekly"
