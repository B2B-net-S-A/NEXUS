"""Pulpit Rady (R2): sprzedaż, koszty i wynik z faktur, koncentracja klientów,
zamówienia kończące się do końca roku.

Źródło kwot: archiwum faktur z eBI24 (``finance_archive_documents``, netto
w PLN). Miesiąc faktury to **data sprzedaży** z eBI24 (``transactionDate``),
nie data wystawienia: od kwietnia 2026 faktury za miesiąc pracy wystawia się
na początku następnego, więc po dacie wystawienia kwiecień miał 0,6 mln,
a czerwiec 18 mln (zgłoszenie Rady 18.11.2026). Data sprzedaży odległa od
wystawienia o więcej niż ``SALE_DATE_WINDOW`` (korekty starych faktur, błędy)
— zostaje data wystawienia.

Koszty dzielą się po folderze eBI24: ``Kontraktorzy`` = koszty kontraktorów,
reszta (``BIURO``, ``Zakupy pozostałe``) = koszty biurowe. „Zysk brutto”
= sprzedaż minus faktury kosztowe, bez płac UoP, ZUS i amortyzacji — po K8
zastąpi go RZiS. Faktury kosztowe przychodzą z opóźnieniem, więc wynik roku
bieżącego i porównanie rok do roku liczą się tylko za miesiące z pełnymi
kosztami (``complete_cost_months``).

Kwoty są sumami całej firmy — trasa wpuszcza tylko Radę i admina.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Optional

from sqlalchemy import Date, and_, case, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardBudget, BoardBudgetLine
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
# Data sprzedaży liczy się, gdy leży od kwartału przed do 45 dni po wystawieniu.
SALE_DATE_WINDOW = (timedelta(days=92), timedelta(days=45))
CONTRACTOR_FOLDER = "Kontraktorzy"
HOURS_PER_MONTH = 160
DAYS_PER_MONTH = 20


def _net_pln():
    """Netto w PLN: netto × (brutto PLN / brutto); faktura w PLN bez brutto = netto."""

    return case(
        (Doc.gross_amount != 0, Doc.net_amount * Doc.gross_pln / Doc.gross_amount),
        (or_(Doc.currency.is_(None), Doc.currency == "PLN"), Doc.net_amount),
        else_=None,
    )


def period_date():
    """Dzień, do którego miesiąca należy faktura: data sprzedaży z eBI24
    w oknie wokół wystawienia, w przeciwnym razie data wystawienia.

    CASE, nie AND: tylko CASE gwarantuje kolejność, więc rzutowanie na datę
    nie dotknie wartości, która datą nie jest."""

    raw = Doc.meta["transactionDate"].astext
    sold = cast(func.substr(raw, 1, 10), Date)
    before, after = SALE_DATE_WINDOW
    return case(
        (Doc.issue_date.is_(None), None),
        (or_(raw.is_(None), ~raw.op("~")(r"^\d{4}-\d{2}-\d{2}")), Doc.issue_date),
        (sold.between(Doc.issue_date - before, Doc.issue_date + after), sold),
        else_=Doc.issue_date,
    )


def is_contractor_cost():
    return and_(Doc.kind == "cost", Doc.folder.ilike(f"{CONTRACTOR_FOLDER}%"))


def mln(value: Optional[Decimal | float]) -> Optional[float]:
    return None if value is None else round(float(value) / 1_000_000, 2)


@dataclass(frozen=True)
class MonthRow:
    year: int
    month: int
    sales: float
    costs: float
    contractors: float = 0.0

    @property
    def office(self) -> float:
        return self.costs - self.contractors


def _complete(rows: list[MonthRow], attr: str, share: float) -> set[tuple[int, int]]:
    ordered = sorted(rows, key=lambda r: (r.year, r.month))
    complete: set[tuple[int, int]] = set()
    for i, row in enumerate(ordered):
        window = [
            getattr(r, attr) for r in ordered[max(0, i - 6) : i] if getattr(r, attr) > 0
        ]
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
        cur_s, cur_c = (
            total(current, result_months, "sales"),
            total(current, result_months, "costs"),
        )
        prev_s, prev_c = (
            total(previous, result_months, "sales"),
            total(previous, result_months, "costs"),
        )
        out.update(
            result=mln(cur_s - cur_c),
            result_pct=round(100 * (cur_s - cur_c) / cur_s, 1) if cur_s else None,
            result_previous=mln(prev_s - prev_c),
            result_previous_pct=round(100 * (prev_s - prev_c) / prev_s, 1)
            if prev_s
            else None,
        )
    return out


async def month_rows(db: AsyncSession, first_year: int) -> list[MonthRow]:
    net = _net_pln()
    day = period_date()
    year = extract("year", day)
    month = extract("month", day)
    rows = await db.execute(
        select(
            year.label("y"),
            month.label("m"),
            func.coalesce(func.sum(case((Doc.kind == "sale", net))), 0),
            func.coalesce(func.sum(case((Doc.kind == "cost", net))), 0),
            func.coalesce(func.sum(case((is_contractor_cost(), net))), 0),
        )
        .where(
            Doc.kind.in_(("sale", "cost")),
            # Faktura z początku stycznia może mieć sprzedaż z grudnia.
            Doc.issue_date >= date(first_year, 1, 1) - SALE_DATE_WINDOW[1],
            day >= date(first_year, 1, 1),
        )
        .group_by(year, month)
        .order_by(year, month)
    )
    return [
        MonthRow(int(y), int(m), float(s or 0), float(c or 0), float(k or 0))
        for y, m, s, c, k in rows.all()
    ]


def year_figures(rows: list[MonthRow], year: int, months: int = 12) -> dict[str, Any]:
    """Sprzedaż, koszty kontraktorów, marża, koszty biurowe i zysk brutto
    za miesiące 1..``months`` roku (mln zł)."""

    picked = [r for r in rows if r.year == year and r.month <= months]
    sales = sum(r.sales for r in picked)
    contractors = sum(r.contractors for r in picked)
    office = sum(r.office for r in picked)
    margin = sales - contractors
    result = margin - office

    def share(value: float) -> Optional[float]:
        return round(100 * value / sales, 1) if sales else None

    return {
        "sales": mln(sales),
        "costs": mln(contractors + office),
        "contractors": mln(contractors),
        "contractor_margin": mln(margin),
        "contractor_margin_pct": share(margin),
        "office": mln(office),
        "result": mln(result),
        "result_pct": share(result),
    }


async def budget_sales(
    db: AsyncSession, years: list[int]
) -> dict[str, list[Optional[float]]]:
    """Plan sprzedaży miesięcy z budżetów Rady (R3), mln zł; brak = ``None``."""

    lines = (
        await db.execute(
            select(BoardBudget.year, BoardBudgetLine.month, BoardBudgetLine.amount)
            .join(BoardBudgetLine, BoardBudgetLine.budget_id == BoardBudget.id)
            .where(BoardBudget.year.in_(years), BoardBudgetLine.line == "sales")
        )
    ).all()
    out: dict[str, list[Optional[float]]] = {}
    for year, month, amount in lines:
        out.setdefault(str(year), [None] * 12)[month - 1] = mln(amount)
    return out


async def top_clients(db: AsyncSession, start: date, end: date) -> list[dict[str, Any]]:
    net = _net_pln()
    day = period_date()
    window = and_(Doc.kind == "sale", day >= start, day <= end)
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
    per_unit = {
        RateUnit.hourly: HOURS_PER_MONTH,
        RateUnit.daily: DAYS_PER_MONTH,
        RateUnit.monthly: 1,
    }
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
        if not any(r.year == year and (r.sales or r.costs) for r in rows):
            continue
        current = year == today.year
        # Koszty bieżącego roku spływają z opóźnieniem — cały słupek roku
        # (także sprzedaż) liczymy za miesiące z pełnymi kosztami.
        months = ytd.get("result_months", 0) if current else 12
        if not months:
            continue
        entry: dict[str, Any] = {
            "year": year,
            **year_figures(rows, year, months),
            "complete": not current,
        }
        if current:
            entry["result_months"] = months
        years.append(entry)
    complete = complete_cost_months(rows)
    sales_complete = complete_sales_months(rows)
    months = [
        {
            "year": r.year,
            "month": r.month,
            "sales": mln(r.sales),
            "costs": mln(r.costs),
            "contractors": mln(r.contractors),
            "costs_complete": (r.year, r.month) in complete,
            # Bieżący miesiąc jest zawsze niepełny: faktury za niego wystawia
            # się na początku następnego.
            "sales_complete": (r.year, r.month) in sales_complete
            and (r.year, r.month) < (today.year, today.month),
        }
        for r in rows
        if r.year >= today.year - 2
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
        "budgets": await budget_sales(db, [today.year - 1, today.year, today.year + 1]),
        "ytd": ytd,
        "top_clients": {
            "year": last_full_year,
            "items": await top_clients(
                db, date(last_full_year, 1, 1), date(last_full_year, 12, 31)
            ),
        },
        "orders": await orders_ending(db, today),
    }
