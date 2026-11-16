"""Pulpit Rady (R2): sprzedaż, koszty i wynik z faktur, koncentracja klientów,
zamówienia kończące się do końca roku.

Źródło kwot: archiwum faktur z eBI24 (``finance_archive_documents``, netto
w PLN, data wystawienia). To nie jest księga: „wynik z faktur” = sprzedaż
minus faktury kosztowe, bez płac UoP, ZUS i amortyzacji — po K8 zastąpi go
RZiS. Faktury kosztowe przychodzą z opóźnieniem, więc porównanie rok do roku
liczy wynik tylko za miesiące z pełnymi kosztami (``complete_cost_months``).

Kwoty są sumami całej firmy — trasa wpuszcza tylko Radę i admina.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any, Optional

from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.finance_archive import FinanceArchiveDocument as Doc
from app.services.fx_service import rates_to_pln

HISTORY_YEARS = 3
TOP_CLIENTS = 5
# Miesiąc z kosztami poniżej tej części mediany 6 poprzednich jest niepełny.
COST_COMPLETE_SHARE = 0.8
# Ostatni miesiąc sprzedaży do porównań: co najmniej połowa mediany 6 poprzednich
# (bieżący, ledwo zaczęty miesiąc nie wydłuża okresu porównania).
SALES_COMPLETE_SHARE = 0.5
HOURS_PER_MONTH = 160
DAYS_PER_MONTH = 20


def _net_pln():
    """Netto w PLN: netto × (brutto PLN / brutto); faktura w PLN bez brutto = netto."""

    return case(
        (Doc.gross_amount != 0, Doc.net_amount * Doc.gross_pln / Doc.gross_amount),
        (or_(Doc.currency.is_(None), Doc.currency == "PLN"), Doc.net_amount),
        else_=None,
    )


def mln(value: Optional[Decimal | float]) -> Optional[float]:
    return None if value is None else round(float(value) / 1_000_000, 2)


@dataclass(frozen=True)
class MonthRow:
    year: int
    month: int
    sales: float
    costs: float


def _complete(rows: list[MonthRow], attr: str, share: float) -> set[tuple[int, int]]:
    ordered = sorted(rows, key=lambda r: (r.year, r.month))
    complete: set[tuple[int, int]] = set()
    for i, row in enumerate(ordered):
        window = [getattr(r, attr) for r in ordered[max(0, i - 6) : i] if getattr(r, attr) > 0]
        if not window or getattr(row, attr) >= share * median(window):
            complete.add((row.year, row.month))
    return complete


def complete_sales_months(rows: list[MonthRow]) -> set[tuple[int, int]]:
    """Miesiące ze sprzedażą co najmniej połowy mediany 6 poprzednich."""

    return _complete(rows, "sales", SALES_COMPLETE_SHARE)


def complete_cost_months(rows: list[MonthRow]) -> set[tuple[int, int]]:
    """Miesiące, których koszty nie są wyraźnie niższe od mediany 6 poprzednich."""

    return _complete(rows, "costs", COST_COMPLETE_SHARE)


def year_over_year(rows: list[MonthRow], year: int) -> dict[str, Any]:
    """Ten sam zakres miesięcy w roku bieżącym i poprzednim.

    Sprzedaż: do ostatniego miesiąca z fakturami. Wynik: tylko do ostatniego
    miesiąca z pełnymi kosztami (od stycznia bez przerw).
    """

    current = {r.month: r for r in rows if r.year == year}
    previous = {r.month: r for r in rows if r.year == year - 1}
    sales_complete = [m for (y, m) in complete_sales_months(rows) if y == year]
    if not current or not sales_complete:
        return {"sales_months": 0, "result_months": 0}
    sales_months = max(sales_complete)
    complete = complete_cost_months(rows)
    result_months = 0
    for month in range(1, sales_months + 1):
        if (year, month) not in complete:
            break
        result_months = month

    def total(src: dict[int, MonthRow], months: int, attr: str) -> float:
        return sum(getattr(src[m], attr) for m in range(1, months + 1) if m in src)

    out: dict[str, Any] = {
        "sales_months": sales_months,
        "sales": mln(total(current, sales_months, "sales")),
        "sales_previous": mln(total(previous, sales_months, "sales")),
        "result_months": result_months,
    }
    if result_months:
        cur_s, cur_c = total(current, result_months, "sales"), total(current, result_months, "costs")
        prev_s, prev_c = total(previous, result_months, "sales"), total(previous, result_months, "costs")
        out.update(
            result=mln(cur_s - cur_c),
            result_pct=round(100 * (cur_s - cur_c) / cur_s, 1) if cur_s else None,
            result_previous=mln(prev_s - prev_c),
            result_previous_pct=round(100 * (prev_s - prev_c) / prev_s, 1) if prev_s else None,
        )
    return out


async def month_rows(db: AsyncSession, first_year: int) -> list[MonthRow]:
    net = _net_pln()
    year = extract("year", Doc.issue_date)
    month = extract("month", Doc.issue_date)
    rows = await db.execute(
        select(
            year.label("y"),
            month.label("m"),
            func.coalesce(func.sum(case((Doc.kind == "sale", net))), 0),
            func.coalesce(func.sum(case((Doc.kind == "cost", net))), 0),
        )
        .where(Doc.kind.in_(("sale", "cost")), Doc.issue_date >= date(first_year, 1, 1))
        .group_by(year, month)
        .order_by(year, month)
    )
    return [MonthRow(int(y), int(m), float(s or 0), float(c or 0)) for y, m, s, c in rows.all()]


async def _top_clients(db: AsyncSession, start: date, end: date) -> list[dict[str, Any]]:
    net = _net_pln()
    window = and_(Doc.kind == "sale", Doc.issue_date >= start, Doc.issue_date <= end)
    total = (await db.execute(select(func.sum(net)).where(window))).scalar_one_or_none()
    if not total:
        return []
    rows = await db.execute(
        select(Doc.partner_name, func.sum(net).label("v"))
        .where(window)
        .group_by(Doc.partner_name)
        .order_by(func.sum(net).desc().nulls_last())
        .limit(TOP_CLIENTS)
    )
    return [
        {
            "name": name or "bez nazwy",
            "sales": mln(value),
            "share": round(100 * float(value or 0) / float(total), 1),
        }
        for name, value in rows.all()
    ]


async def orders_ending(db: AsyncSession, today: date) -> dict[str, Any]:
    """Aktywne kontrakty i te, których zamówienie albo umowa kończy się do 31.12.

    Potencjał miesięczny = stawka klienta × 160 h (20 dni, 1 miesiąc) po kursie
    NBP — górna granica, bo nie każda godzina jest przepracowana i fakturowana.
    """

    year_end = date(today.year, 12, 31)
    contracts = (
        await db.execute(
            select(
                Contract.rate_client,
                Contract.rate_unit,
                func.coalesce(Contract.rate_client_currency, Contract.currency),
                func.least(
                    func.coalesce(Contract.end_date, date(9999, 12, 31)),
                    func.coalesce(Contract.client_order_end_date, date(9999, 12, 31)),
                ),
            ).where(
                Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
                or_(Contract.end_date.is_(None), Contract.end_date >= today),
            )
        )
    ).all()
    rates = await rates_to_pln(db, {row[2] or "PLN" for row in contracts}, today)
    per_unit = {RateUnit.hourly: HOURS_PER_MONTH, RateUnit.daily: DAYS_PER_MONTH, RateUnit.monthly: 1}
    active = ending = 0
    potential = ending_potential = 0.0
    no_rate = 0
    for rate, unit, currency, last_day in contracts:
        active += 1
        is_ending = last_day <= year_end
        ending += int(is_ending)
        fx = rates.get((currency or "PLN").upper())
        if rate is None or fx is None or unit not in per_unit:
            no_rate += 1
            continue
        monthly = float(rate) * float(fx) * per_unit[unit]
        potential += monthly
        if is_ending:
            ending_potential += monthly
    return {
        "active": active,
        "ending": ending,
        "potential_month": mln(potential),
        "ending_potential_month": mln(ending_potential),
        "without_rate": no_rate,
        "year_end": year_end.isoformat(),
    }


async def company_summary(db: AsyncSession, today: date) -> dict[str, Any]:
    first_year = today.year - HISTORY_YEARS
    rows = await month_rows(db, first_year)
    coverage = (
        await db.execute(
            select(func.min(Doc.issue_date), func.max(Doc.issue_date)).where(
                Doc.kind.in_(("sale", "cost"))
            )
        )
    ).one()
    ytd = year_over_year(rows, today.year)
    years = []
    for year in range(first_year, today.year + 1):
        sales = sum(r.sales for r in rows if r.year == year)
        costs = sum(r.costs for r in rows if r.year == year)
        if not sales and not costs:
            continue
        entry: dict[str, Any] = {
            "year": year,
            "sales": mln(sales),
            "costs": mln(costs),
            "result": mln(sales - costs),
            "result_pct": round(100 * (sales - costs) / sales, 1) if sales else None,
            "complete": year < today.year,
        }
        if year == today.year:
            # Koszty bieżącego roku spływają z opóźnieniem — wynik tylko
            # z miesięcy z pełnymi kosztami, jak w porównaniu rok do roku.
            entry.update(
                result=ytd.get("result"),
                result_pct=ytd.get("result_pct"),
                result_months=ytd.get("result_months", 0),
            )
        years.append(entry)
    complete = complete_cost_months(rows)
    months = [
        {
            "year": r.year,
            "month": r.month,
            "sales": mln(r.sales),
            "costs": mln(r.costs),
            "costs_complete": (r.year, r.month) in complete,
        }
        for r in rows
        if r.year >= today.year - 1
    ]
    last_full_year = today.year - 1
    return {
        "source": {
            "kind": "invoices",
            "first_date": coverage[0].isoformat() if coverage[0] else None,
            "last_date": coverage[1].isoformat() if coverage[1] else None,
        },
        "years": years,
        "months": months,
        "ytd": ytd,
        "top_clients": {
            "year": last_full_year,
            "items": await _top_clients(db, date(last_full_year, 1, 1), date(last_full_year, 12, 31)),
        },
        "orders": await orders_ending(db, today),
    }

