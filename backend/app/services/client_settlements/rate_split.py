"""Koszt z dwóch stawek kontraktora w jednym miesiącu (próba IX–X 2026). Bez bazy.

Harmonogram kontraktu podniósł stawkę Partnera w połowie miesiąca, a linia
zamówienia ma jedną stawkę MD. Kontraktor zafakturował dni przed zmianą starą
stawką, a od zmiany nową. NEXUS liczył całość starą i dawał uwagę „Zmiana stawki”.

* **Stawka w dniu jak ``Contract.effective_candidate_rate``:** ostatni krok nie
  późniejszy niż ten dzień, a przed pierwszym krokiem stawka pierwszego kroku.
  Pierwszy krok w środku miesiąca (krok z dnia startu kontraktu, Orlen 29.10)
  i krok z tą samą stawką („125 → 125”) nie zmieniają stawki, więc nie dają uwagi.
* **Prawdziwa zmiana:** MD dzielimy według godzin z RCP dzień po dniu (przed
  zmianą i od zmiany). Koszt części = MD części × stawka części w zł/MD.
* **Uwaga zostaje, gdy podziału nie da się policzyć:** dowód bez godzin dzień po
  dniu, godziny nie dają MD rozliczenia, praca dodatkowa, stawka kontraktu nie
  w zł, linia zamówienia ze stawką spoza harmonogramu.
* **Przychód się nie dzieli:** stawkę klienta liczymy stawką z pierwszego dnia
  miesiąca (``order_revenue_steps``, decyzja Artura z 16.11.2026).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence, Union

MD_Q = Decimal("0.001")
MONEY_Q = Decimal("0.01")
ZERO = Decimal("0")

#: Krok harmonogramu: (od dnia, stawka w jednostce kontraktu), w kolejności
#: ``effective_from, id`` (przy remisie wygrywa późniejszy wpis).
Step = tuple[date, Decimal]


@dataclass(frozen=True)
class Change:
    day: date
    old: Decimal
    new: Decimal


@dataclass(frozen=True)
class CostPart:
    """Część miesiąca po jednej stawce kosztu."""

    start: date
    end: date
    md: Decimal
    #: Stawka kosztu w zł/MD.
    rate: Decimal

    @property
    def net(self) -> Decimal:
        return (self.md * self.rate).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def rate_on(steps: Sequence[Step], day: date) -> Optional[Decimal]:
    """Stawka w dniu ``day``; przed pierwszym krokiem stawka pierwszego kroku."""

    if not steps:
        return None
    past = [rate for start, rate in steps if start <= day]
    if past:
        return past[-1]
    earliest = steps[0][0]
    return [rate for start, rate in steps if start == earliest][-1]


def changes(steps: Sequence[Step], first: date, last: date) -> list[Change]:
    """Dni miesiąca (bez pierwszego), od których stawka jest inna niż dzień wcześniej."""

    found: list[Change] = []
    for day in sorted({start for start, _ in steps if first < start <= last}):
        old = rate_on(steps, day - timedelta(days=1))
        new = rate_on(steps, day)
        if old is not None and new is not None and old != new:
            found.append(Change(day, old, new))
    return found


def parts(
    segments: Sequence[tuple[date, Decimal]],
    day_hours: Sequence[Decimal],
    *,
    last: date,
    md: Decimal,
    per_md: Decimal,
) -> Union[list[CostPart], str]:
    """Części kosztu według godzin dzień po dniu; tekst = powód, czemu się nie da.

    ``segments``: (od dnia, stawka zł/MD), pierwszy od 1. dnia miesiąca.
    ``day_hours``: godziny od 1. dnia miesiąca (RCP BNP ma 31 kolumn: w krótszym
    miesiącu ostatnie to dni następnego, więc liczą się tylko dni do ``last``).
    Reszta z zaokrąglenia MD idzie na ostatnią część, więc suma = ``md``."""

    if len(day_hours) < last.day:
        return "Dowód nie ma godzin dzień po dniu, więc nie wiadomo, ile pracy było przed zmianą."
    hours = [Decimal(h) for h in day_hours[: last.day]]
    total = sum(hours, ZERO)
    if per_md <= 0 or abs(total / per_md - md) >= MD_Q:
        return (
            f"Godziny z dni ({_fmt(total)} h) nie dają {_fmt(md)} MD rozliczenia, "
            "więc podziału na dni przed i po zmianie nie da się policzyć."
        )
    found: list[CostPart] = []
    for index, (start, rate) in enumerate(segments):
        end = (
            segments[index + 1][0] - timedelta(days=1)
            if index + 1 < len(segments)
            else last
        )
        part_hours = sum(hours[start.day - 1 : end.day], ZERO)
        part_md = (part_hours / per_md).quantize(MD_Q, rounding=ROUND_HALF_UP)
        found.append(CostPart(start, end, part_md, rate))
    rest = md - sum((p.md for p in found[:-1]), ZERO)
    found[-1] = CostPart(found[-1].start, found[-1].end, rest, found[-1].rate)
    return [p for p in found if p.md > 0] or found[-1:]


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")
