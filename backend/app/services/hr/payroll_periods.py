"""Miesiące płac: daty, stan okresu i blokada zmian w zamkniętym miesiącu.

Zamknięty miesiąc nie przyjmuje zmian stawek obowiązujących w tym miesiącu
ani premii z tym okresem (409) — linie są zamrożone, a timesheety mają
``payroll_locked``. Otwiera go ponownie tylko administrator, ze śladem.

Zamknięcie trzyma wiersz okresu pod ``FOR UPDATE`` od początku do commita;
zmiany wchodzące do płac (premia, akceptacja timesheetu) sprawdzają okres pod
``FOR SHARE`` (``assert_open`` / ``lock_period_shared``). Zmiana albo kończy
się przed zamknięciem (i trafia do zamrożonych linii), albo czeka na jego
koniec i widzi „zamknięty” — nie ma okna, w którym mija się z raportem.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll import PayrollPeriod
from app.services.hr.payroll_errors import PayrollConflict, PayrollError

MONTHS_PL: tuple[str, ...] = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)

YearMonth = tuple[int, int]


def validate_period(year: int, month: int) -> None:
    if not 2020 <= year <= 2100 or not 1 <= month <= 12:
        raise PayrollError("Niepoprawny miesiąc.")


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def month_end(year: int, month: int) -> date:
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return nxt - timedelta(days=1)


def add_months(year: int, month: int, delta: int) -> YearMonth:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def previous_month(today: date) -> YearMonth:
    """Miesiąc przed ``today`` — w styczniu grudzień POPRZEDNIEGO roku.

    Compass (``/api/internal/payroll-export``) w styczniu zwracał grudzień
    bieżącego roku.
    """

    return add_months(today.year, today.month, -1)


def months_between(first: YearMonth, last: YearMonth) -> list[YearMonth]:
    out: list[YearMonth] = []
    current = first
    while current <= last:
        out.append(current)
        current = add_months(current[0], current[1], 1)
    return out


def label(year: int, month: int) -> str:
    return f"{MONTHS_PL[month - 1]} {year}"


async def get_period(
    db: AsyncSession, year: int, month: int
) -> Optional[PayrollPeriod]:
    return await db.scalar(
        select(PayrollPeriod).where(
            PayrollPeriod.year == year, PayrollPeriod.month == month
        )
    )


async def lock_period(db: AsyncSession, year: int, month: int) -> PayrollPeriod:
    """Wiersz okresu pod ``FOR UPDATE`` (zakłada go, gdy go nie ma)."""

    await db.execute(
        insert(PayrollPeriod)
        .values(year=year, month=month, status="open")
        .on_conflict_do_nothing(index_elements=["year", "month"])
    )
    period = await db.scalar(
        select(PayrollPeriod)
        .where(PayrollPeriod.year == year, PayrollPeriod.month == month)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert period is not None
    return period


async def lock_period_shared(db: AsyncSession, year: int, month: int) -> PayrollPeriod:
    """Wiersz okresu pod ``FOR SHARE`` (zakłada go, gdy go nie ma).

    Wiersz musi istnieć, zanim go zablokujemy: zamknięcie, które dopiero go
    wstawiło, jest jeszcze niewidoczne, a ``ON CONFLICT DO NOTHING`` czeka na
    jego koniec — bez wstawienia akceptacja przeszłaby obok zamknięcia.
    """

    await db.execute(
        insert(PayrollPeriod)
        .values(year=year, month=month, status="open")
        .on_conflict_do_nothing(index_elements=["year", "month"])
    )
    period = await db.scalar(
        select(PayrollPeriod)
        .where(PayrollPeriod.year == year, PayrollPeriod.month == month)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    assert period is not None
    return period


async def closed_months(
    db: AsyncSession, months: Optional[list[YearMonth]] = None
) -> set[YearMonth]:
    query = select(PayrollPeriod.year, PayrollPeriod.month).where(
        PayrollPeriod.status == "closed"
    )
    if months is not None:
        if not months:
            return set()
        query = query.where(tuple_(PayrollPeriod.year, PayrollPeriod.month).in_(months))
    return {(int(y), int(m)) for y, m in (await db.execute(query)).all()}


async def is_closed(db: AsyncSession, year: int, month: int) -> bool:
    return (year, month) in await closed_months(db, [(year, month)])


def closed_detail(year: int, month: int) -> str:
    return (
        f"Miesiąc płac {label(year, month)} jest zamknięty — zmiany tego miesiąca "
        "wymagają ponownego otwarcia przez administratora."
    )


async def assert_open(db: AsyncSession, year: int, month: int) -> None:
    """Miesiąc otwarty — sprawdzone pod blokadą współdzieloną do końca transakcji."""

    period = await lock_period_shared(db, year, month)
    if period.status == "closed":
        raise PayrollConflict(
            closed_detail(year, month),
            code="payroll_month_closed",
            data={"year": year, "month": month},
        )


async def assert_range_open(db: AsyncSession, start: date, end: Optional[date]) -> None:
    """Żaden miesiąc od ``start`` do ``end`` (bez końca = wszystkie dalsze) nie jest zamknięty."""

    rows = await db.execute(
        select(PayrollPeriod.year, PayrollPeriod.month)
        .where(PayrollPeriod.status == "closed")
        .order_by(PayrollPeriod.year, PayrollPeriod.month)
    )
    first = (start.year, start.month)
    last = (end.year, end.month) if end is not None else None
    for year, month in rows.all():
        key = (int(year), int(month))
        if key >= first and (last is None or key <= last):
            raise PayrollConflict(
                closed_detail(*key),
                code="payroll_month_closed",
                data={"year": key[0], "month": key[1]},
            )


async def first_open_month_from(db: AsyncSession, year: int, month: int) -> YearMonth:
    """Pierwszy niezamknięty miesiąc od podanego (premia z automatu nie trafia do zamkniętego)."""

    closed = await closed_months(db)
    current = (year, month)
    while current in closed:
        current = add_months(current[0], current[1], 1)
    return current


__all__ = [
    "MONTHS_PL",
    "add_months",
    "assert_open",
    "assert_range_open",
    "closed_detail",
    "closed_months",
    "first_open_month_from",
    "get_period",
    "is_closed",
    "label",
    "lock_period",
    "lock_period_shared",
    "month_end",
    "month_start",
    "months_between",
    "previous_month",
    "validate_period",
]
