"""Tempo zużycia zamówienia MD / kosztowego — próg wysokiego priorytetu.

Panel „Moi klienci" podnosi przypomnienie do wysokiego priorytetu (+ mail),
gdy pozostałość wystarcza na ~7 dni roboczych przy DOTYCHCZASOWYM tempie tego
konkretnego zamówienia. Stały próg w MD albo złotych mówiłby co innego przy
zamówieniu jednej osoby i przy zamówieniu pięciu — dlatego liczymy tempo.

Zużycie jest raportowane MIESIĘCZNIE (``period_month``), więc tempo to suma
raportów podzielona przez dni robocze w raportowanych miesiącach, licząc od
późniejszej z dat: startu zamówienia albo pierwszego dnia pierwszego
raportowanego miesiąca, do ostatniego dnia ostatniego raportowanego miesiąca
(nie dalej niż dziś). Miesiąc bez raportu w środku przedziału liczy się jako
zero — tak samo, jak widzi go budżet.

Moduł jest czysty (bez bazy): wejście to liczby i daty, więc da się go
przetestować wartościami, a nie zrzutem ekranu.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from app.core.scheduling import _polish_holidays

#: Szacunek dla zamówienia MD bez żadnego raportu: konsultant pracuje ~1 MD
#: na dzień roboczy. Zamówienie kosztowe nie ma odpowiednika (stawka i skład
#: pozycji są zbyt różne), więc bez historii nie dostaje progu dynamicznego.
MD_PER_WORKDAY_PER_CONSULTANT = Decimal("1")


def workdays_between(start: date, end: date) -> int:
    """Dni robocze (Pon–Pt bez polskich świąt) w przedziale DOMKNIĘTYM."""
    if end < start:
        return 0
    count = 0
    day = start
    one = timedelta(days=1)
    while day <= end:
        if day.weekday() < 5 and day not in _polish_holidays(day.year):
            count += 1
        day += one
    return count


def _month_bounds(period_month: str) -> tuple[date, date]:
    year, month = (int(part) for part in period_month.split("-", 1))
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


@dataclass(frozen=True)
class BurnRate:
    """Tempo na dzień roboczy + skąd się wzięło."""

    per_workday: Decimal
    estimated: bool
    """``True`` = szacunek bez historii (MD: 1 MD/dzień na osobę)."""


def burn_rate_from_reports(
    reports: Iterable[tuple[str, Decimal]],
    *,
    order_start: Optional[date],
    today: date,
) -> Optional[Decimal]:
    """Średnie zużycie na dzień roboczy z miesięcznych raportów.

    ``None``, gdy nie ma czego liczyć (brak raportów, suma zero albo zero dni
    roboczych w przedziale) — wtedy wołający sięga po szacunek albo w ogóle
    nie ustala progu. Zero NIE jest tempem: zamówienie, które jeszcze nic nie
    zużyło, nie „wystarcza na nieskończenie długo".
    """
    rows = [(month, Decimal(value)) for month, value in reports if value is not None]
    if not rows:
        return None
    total = sum((value for _, value in rows), Decimal("0"))
    if total <= 0:
        return None
    months = sorted(month for month, _ in rows)
    first_day, _ = _month_bounds(months[0])
    _, last_day = _month_bounds(months[-1])
    if order_start is not None and order_start > first_day:
        first_day = order_start
    if last_day > today:
        last_day = today
    days = workdays_between(first_day, last_day)
    if days <= 0:
        return None
    return total / Decimal(days)


def md_burn_rate(
    reports: Iterable[tuple[str, Decimal]],
    *,
    order_start: Optional[date],
    today: date,
    consultants: int,
) -> Optional[BurnRate]:
    """Tempo MD: z historii, a bez niej szacunek 1 MD/dzień na osobę."""
    measured = burn_rate_from_reports(reports, order_start=order_start, today=today)
    if measured is not None:
        return BurnRate(per_workday=measured, estimated=False)
    if consultants <= 0:
        return None
    return BurnRate(
        per_workday=MD_PER_WORKDAY_PER_CONSULTANT * consultants, estimated=True
    )


def cost_burn_rate(
    reports: Iterable[tuple[str, Decimal]],
    *,
    order_start: Optional[date],
    today: date,
) -> Optional[BurnRate]:
    """Tempo wydatków kosztowych. Bez historii: brak progu dynamicznego."""
    measured = burn_rate_from_reports(reports, order_start=order_start, today=today)
    if measured is None:
        return None
    return BurnRate(per_workday=measured, estimated=False)


def high_priority_threshold(
    rate: Optional[BurnRate], workdays: int
) -> Optional[Decimal]:
    """Pozostałość, poniżej której (włącznie) sprawa jest pilna."""
    if rate is None or workdays <= 0:
        return None
    return rate.per_workday * Decimal(workdays)
