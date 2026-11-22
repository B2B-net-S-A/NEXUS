"""Budżet Rady (R3): plan, wykonanie z faktur i prognoza z kontraktów.

* **Plan** — wpisuje admin (Zarząd) miesiąc po miesiącu; przyjęcie budżetu to
  uchwała Rady w dokumentach (``resolution_document_id``).
* **Wykonanie** — ta sama miara co pulpit: sprzedaż i faktury kosztowe
  z archiwum eBI24, netto w PLN (``summary``).
* **Prognoza** miesięcy po ostatnim pełnym miesiącu sprzedaży: potencjał
  aktywnych kontraktów (stawka klienta po kursie NBP × dni robocze z polskimi
  świętami × 8 h dla stawki godzinowej) przemnożony przez **realizację** —
  średni stosunek faktur do potencjału w ostatnich 3 pełnych miesiącach.
  Koszty = sprzedaż × udział kosztów w sprzedaży z 12 miesięcy kroczących do
  ostatniego miesiąca z pełnymi kosztami (krótsze okno łapie przesunięcia dat
  wystawienia: faktury za kwiecień wystawione w czerwcu). Dwa scenariusze: **bez przedłużeń** (kontrakt kończy się
  w dniu końca umowy albo zamówienia) i **wszystkie przedłużone**.

Prognoza to dodatek: brak danych daje ``null`` i komunikat, nie zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardBudget, BoardBudgetLine
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.board import summary
from app.services.fx_service import rates_to_pln
from app.services.person_workdays import business_days

HOURS_PER_DAY = 8
REALIZATION_MONTHS = 3
COST_SHARE_MONTHS = 12
_FAR = date(9999, 12, 31)


@dataclass(frozen=True)
class ContractRate:
    """Stawka klienta w PLN na dzień roboczy i ostatni dzień pracy."""

    per_day: float
    last_day: date
    monthly: bool


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def potential(
    rates: list[ContractRate], year: int, month: int, *, renewed: bool
) -> float:
    """Potencjał sprzedaży miesiąca: każdy kontrakt × jego dni robocze w miesiącu."""

    start, end = month_bounds(year, month)
    all_days = business_days(start, end)
    if not all_days:
        return 0.0
    total = 0.0
    for rate in rates:
        last = end if renewed else min(end, rate.last_day)
        if last < start:
            continue
        days = len([d for d in all_days if d <= last])
        total += rate.per_day * days
    return total


async def contract_rates(db: AsyncSession, today: date) -> list[ContractRate]:
    rows = (
        await db.execute(
            select(
                Contract.rate_client,
                Contract.rate_unit,
                func.coalesce(Contract.rate_client_currency, Contract.currency),
                func.least(
                    func.coalesce(Contract.end_date, _FAR),
                    func.coalesce(Contract.client_order_end_date, _FAR),
                ),
            ).where(
                Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
                or_(Contract.end_date.is_(None), Contract.end_date >= today),
            )
        )
    ).all()
    fx = await rates_to_pln(db, {row[2] or "PLN" for row in rows}, today)
    out: list[ContractRate] = []
    for rate, unit, currency, last_day in rows:
        to_pln = fx.get((currency or "PLN").upper())
        if rate is None or to_pln is None:
            continue
        value = float(rate) * float(to_pln)
        if unit == RateUnit.hourly:
            out.append(ContractRate(value * HOURS_PER_DAY, last_day, False))
        elif unit == RateUnit.daily:
            out.append(ContractRate(value, last_day, False))
        elif unit == RateUnit.monthly:
            # Miesięczna stawka rozkłada się na dni robocze miesiąca (ok. 21).
            out.append(ContractRate(value / 21, last_day, True))
    return out


def cost_share(
    sales: dict[tuple[int, int], float],
    costs: dict[tuple[int, int], float],
    cost_complete: list[tuple[int, int]],
) -> Optional[float]:
    """Koszty / sprzedaż w 12 miesiącach kroczących do ostatniego z pełnymi kosztami."""

    if not cost_complete:
        return None
    end_year, end_month = cost_complete[-1]
    window = []
    year, month = end_year, end_month
    for _ in range(COST_SHARE_MONTHS):
        window.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    total_sales = sum(sales.get(m, 0.0) for m in window)
    if total_sales <= 0 or sum(1 for m in window if m in sales) < REALIZATION_MONTHS:
        return None
    return round(sum(costs.get(m, 0.0) for m in window) / total_sales, 3)


def realization(
    actual: dict[tuple[int, int], float],
    rates: list[ContractRate],
    months: list[tuple[int, int]],
) -> Optional[float]:
    """Średnia faktur / potencjał (z przedłużeniami) w podanych pełnych miesiącach."""

    ratios = []
    for year, month in months:
        cap = potential(rates, year, month, renewed=True)
        if cap > 0 and actual.get((year, month)):
            ratios.append(actual[(year, month)] / cap)
    return round(sum(ratios) / len(ratios), 3) if ratios else None


async def budget_view(db: AsyncSession, year: int, today: date) -> dict[str, Any]:
    rows = await summary.month_rows(db, year - 2)
    sales = {(r.year, r.month): r.sales for r in rows}
    costs = {(r.year, r.month): r.costs for r in rows}
    sales_complete = sorted(summary.complete_sales_months(rows))
    cost_complete = sorted(summary.complete_cost_months(rows))
    last_sales = sales_complete[-1] if sales_complete else None
    rates = await contract_rates(db, today)

    base_months = [m for m in sales_complete if m <= (today.year, today.month)][
        -REALIZATION_MONTHS:
    ]
    real = realization(sales, rates, base_months)
    share = cost_share(sales, costs, cost_complete)

    budget = (
        await db.execute(select(BoardBudget).where(BoardBudget.year == year))
    ).scalar_one_or_none()
    plan: dict[tuple[int, str], float] = {}
    if budget is not None:
        for line in (
            await db.execute(
                select(BoardBudgetLine).where(BoardBudgetLine.budget_id == budget.id)
            )
        ).scalars():
            plan[(line.month, line.line)] = float(line.amount)

    months = []
    for month in range(1, 13):
        key = (year, month)
        is_actual = last_sales is not None and key <= last_sales
        entry: dict[str, Any] = {
            "month": month,
            "plan_sales": summary.mln(plan.get((month, "sales"))),
            "plan_costs": summary.mln(plan.get((month, "costs"))),
            "kind": "actual" if is_actual else "forecast",
            "sales": summary.mln(sales.get(key)) if is_actual else None,
            "costs": summary.mln(costs.get(key)) if is_actual else None,
            "costs_complete": key in set(cost_complete),
            "potential": None,
            "potential_renewed": None,
            "business_days": len(business_days(*month_bounds(year, month))),
        }
        if not is_actual:
            entry["potential"] = summary.mln(
                potential(rates, year, month, renewed=False)
            )
            entry["potential_renewed"] = summary.mln(
                potential(rates, year, month, renewed=True)
            )
        months.append(entry)

    return {
        "year": year,
        "budget": None
        if budget is None
        else {
            "status": budget.status,
            "resolution_document_id": budget.resolution_document_id,
            "note": budget.note,
            "updated_at": budget.updated_at.isoformat() if budget.updated_at else None,
        },
        "months": months,
        "realization": real,
        "realization_months": [f"{m:02d}.{y}" for y, m in base_months],
        "cost_share": share,
        "contracts": len(rates),
    }
