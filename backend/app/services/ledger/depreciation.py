"""Plan amortyzacji środków trwałych i WNiP (K6) — czyste funkcje, bez bazy.

Plan „Księgowość w NEXUSIE” (13.11.2026): NEXUS zastępuje Symfonię Środki
Trwałe, więc odpis każdego miesiąca liczy sam. Kwoty w groszach (``int``),
stawki w procentach rocznie (``Decimal``). Ten sam silnik liczy plan bilansowy
(dokument AM w księdze) i podatkowy (CIT) — różnią się metodą, stawką
i umorzeniem ze stanu z Symfonii.

Zasady (ustawa o CIT art. 16h–16k, ustawa o rachunkowości art. 32):

* **Początek**: odpisy od miesiąca następującego po miesiącu przyjęcia (OT).
  Środek ze stanem z Symfonii (umorzenie na koniec miesiąca) — od miesiąca po
  tym stanie, od umorzenia ze stanu.
* **Liniowa**: odpis = wartość początkowa × stawka / 12, zaokrąglony do grosza
  (połówki w górę); ostatni odpis = reszta do wartości początkowej.
* **Degresywna** (art. 16k): stawka × współczynnik (1,0–2,0) od wartości netto
  z początku roku — w pierwszym roku od wartości początkowej. Od roku, w którym
  tak liczony odpis roczny byłby niższy od liniowego (stawka × wartość
  początkowa), odpis liniowy do końca.
* **Jednorazowa**: cała wartość w pierwszym miesiącu odpisów.
* **Bez amortyzacji** (grunty) albo stawka 0: planu nie ma.
* **Ulepszenie** zwiększa wartość początkową od miesiąca po miesiącu ulepszenia
  (art. 16g ust. 13, art. 16h ust. 1 pkt 1); w degresywnej powiększa też
  podstawę bieżącego roku. Ulepszenie w pełni umorzonego środka wznawia odpisy.
* **Likwidacja i sprzedaż**: odpis także za miesiąc likwidacji albo sprzedaży
  („do końca miesiąca”, art. 16h ust. 1 pkt 1), potem żadnego.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

METHODS: tuple[str, ...] = ("linear", "degressive", "one_off", "none")
METHOD_LABELS: dict[str, str] = {
    "linear": "liniowa",
    "degressive": "degresywna",
    "one_off": "jednorazowa",
    "none": "bez amortyzacji",
}
#: Bezpiecznik pętli: 100 lat (budynek przy 1,5% to ok. 67 lat).
MONTHS_MAX = 1200
COEFFICIENT_DEFAULT = Decimal("2.0")
_TWELVE_HUNDRED = Decimal(1200)


@dataclass(frozen=True)
class Opening:
    """Stan z Symfonii: umorzenie na koniec ``month`` (pierwszy dzień miesiąca).

    ``year_start`` — umorzenie na początek roku ``month``; potrzebne tylko
    metodzie degresywnej, gdy stan nie jest na koniec grudnia (podstawa roku).
    """

    month: date
    accumulated: int
    year_start: Optional[int] = None


@dataclass(frozen=True)
class PlanInput:
    method: str
    rate: Decimal
    initial: int
    accepted: date
    coefficient: Decimal = COEFFICIENT_DEFAULT
    #: (dzień ulepszenia, kwota) — wartość rośnie od następnego miesiąca.
    improvements: tuple[tuple[date, int], ...] = ()
    opening: Optional[Opening] = None
    #: Dzień likwidacji albo sprzedaży — odpis jeszcze za jego miesiąc.
    disposed: Optional[date] = None


@dataclass(frozen=True)
class PlanRow:
    month: date
    amount: int
    accumulated: int
    #: Wartość początkowa w tym miesiącu (z ulepszeniami).
    value: int
    #: Odpis degresywny (po przejściu na liniową — ``False``).
    degressive: bool = False

    @property
    def net(self) -> int:
        return self.value - self.accumulated


def first_of(day: date) -> date:
    return date(day.year, day.month, 1)


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def monthly(base: int, rate: Decimal, factor: Decimal = Decimal(1)) -> int:
    """Odpis miesięczny: podstawa × stawka (%) × współczynnik / 12, do grosza."""

    value = Decimal(base) * rate * factor / _TWELVE_HUNDRED
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def first_month(plan: PlanInput) -> date:
    """Pierwszy miesiąc odpisów: po przyjęciu, a przy stanie — po jego miesiącu."""

    start = add_months(first_of(plan.accepted), 1)
    if plan.opening is not None:
        start = max(start, add_months(first_of(plan.opening.month), 1))
    return start


def depreciates(plan: PlanInput) -> bool:
    if plan.method == "none":
        return False
    return plan.method == "one_off" or plan.rate > 0


def schedule(plan: PlanInput, *, until: Optional[date] = None) -> list[PlanRow]:
    """Odpisy miesiąc po miesiącu (tylko miesiące z odpisem), najwyżej do ``until``."""

    if not depreciates(plan):
        return []
    value = plan.initial
    accumulated = plan.opening.accumulated if plan.opening is not None else 0
    pending = sorted(
        (add_months(first_of(day), 1), amount) for day, amount in plan.improvements
    )
    last = first_of(plan.disposed) if plan.disposed is not None else None
    if until is not None:
        until = first_of(until)
        last = until if last is None else min(last, until)
    month = first_month(plan)
    year_base = 0
    switched = False
    rows: list[PlanRow] = []
    taken = 0
    for step in range(MONTHS_MAX):
        if last is not None and month > last:
            break
        added = 0
        while taken < len(pending) and pending[taken][0] <= month:
            value += pending[taken][1]
            added += pending[taken][1]
            taken += 1
        if plan.method == "degressive":
            if step == 0 or month.month == 1:
                year_base = _year_base(plan, value, accumulated, month, first=step == 0)
                # Roczny degresywny (podstawa × stawka × współczynnik) niższy od
                # liniowego (wartość × stawka) = liniowa od tego roku do końca.
                switched = switched or year_base * plan.coefficient < value
            else:
                year_base += added
        remaining = value - accumulated
        if remaining <= 0:
            if taken >= len(pending):
                break
            month = add_months(month, 1)
            continue
        if plan.method == "one_off":
            amount = remaining
        elif plan.method == "linear" or switched:
            amount = monthly(value, plan.rate)
        else:
            amount = monthly(year_base, plan.rate, plan.coefficient)
        # Grosz minimum: bardzo mała wartość nie może utknąć na odpisie 0.
        amount = min(max(amount, 1), remaining)
        accumulated += amount
        rows.append(
            PlanRow(
                month=month,
                amount=amount,
                accumulated=accumulated,
                value=value,
                degressive=plan.method == "degressive" and not switched,
            )
        )
        month = add_months(month, 1)
    return rows


def _year_base(
    plan: PlanInput, value: int, accumulated: int, month: date, *, first: bool
) -> int:
    """Podstawa degresywnej: wartość netto z początku roku.

    Pierwszy liczony miesiąc w roku stanu z Symfonii (stan nie na koniec
    grudnia) bierze umorzenie z początku tego roku — inaczej podstawą byłaby
    wartość netto z października, a odpisy do grudnia wyszłyby za małe.
    """

    opening = plan.opening
    if (
        first
        and opening is not None
        and opening.year_start is not None
        and month.year == opening.month.year
    ):
        return value - opening.year_start
    return value - accumulated


def row_for(rows: list[PlanRow], month: date) -> Optional[PlanRow]:
    target = first_of(month)
    for row in rows:
        if row.month == target:
            return row
        if row.month > target:
            return None
    return None


def value_at(plan: PlanInput, month: date) -> int:
    """Wartość początkowa na koniec miesiąca (ulepszenia z wcześniejszych miesięcy).

    Ulepszenie z tego samego miesiąca też się liczy — wartość w ewidencji rośnie
    od dnia ulepszenia, odpis dopiero od następnego miesiąca.
    """

    target = first_of(month)
    return plan.initial + sum(
        amount for day, amount in plan.improvements if first_of(day) <= target
    )


def accumulated_at(plan: PlanInput, rows: list[PlanRow], month: date) -> int:
    """Umorzenie na koniec miesiąca (stan z Symfonii + odpisy do tego miesiąca)."""

    target = first_of(month)
    total = plan.opening.accumulated if plan.opening is not None else 0
    for row in rows:
        if row.month > target:
            break
        total = row.accumulated
    return total


def last_month(rows: list[PlanRow]) -> Optional[date]:
    return rows[-1].month if rows else None
