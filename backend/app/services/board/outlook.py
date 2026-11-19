"""Pulpit Rady (R7): gotówka, zdolność kredytowa, wycena i symulacja roku.

Uwagi Rady z 18.11.2026: w miejscu „Do uwagi Rady” (przeniesionego na dół)
pulpit pokazuje stan gotówki, aktualną zdolność kredytową, wartość spółki
dla inwestora finansowego i branżowego oraz symulację sprzedaży i zysku
brutto na koniec roku.

* **EBITDA** — zysk brutto z faktur z 12 ostatnich miesięcy z pełnymi kosztami
  + amortyzacja przyjęta na stałe 1 mln zł rocznie (uwagi Rady z 19.11.2026:
  amortyzacja jest mała, wystarczy stała; wcześniej EBITDA brała się ze
  sprawozdania). Koszty spoza faktur (płace UoP, ZUS) nie wchodzą — to
  przybliżenie, nie sprawozdanie.
* **Dług netto** = dług finansowy z ostatniego sprawozdania (brak = 0)
  − gotówka (wpis Zarządu, gdy nowszy niż koniec roku sprawozdania; inaczej
  gotówka ze sprawozdania).
* **Symulacja roku** — wykonanie miesięcy z fakturami + prognoza z kontraktów
  z Budżetu (R3) w dwóch scenariuszach; zysk brutto = sprzedaż × (1 − udział
  kosztów z faktur w 12 miesiącach kroczących).

Kwoty w mln zł. Brak danych daje ``None`` i powód, nie zero.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.board_document import BoardCashPosition
from app.services.board import analysis, budget, financials, summary


def _m(value: Optional[float]) -> Optional[float]:
    """PLN ze sprawozdania → mln zł."""

    return None if value is None else round(value / 1_000_000, 2)


#: Po tylu miesiącach od najnowszego pełnego miesiąca koszty uznajemy za spłynięte.
SETTLED_MONTHS = 4


def trailing_months(
    rows: list[summary.MonthRow], complete: set[tuple[int, int]], count: int = 12
) -> list[tuple[int, int]]:
    """Ostatnie ``count`` miesięcy z pełnymi kosztami, bez przerw; miesiąc
    z niepełnymi kosztami w środku okna = brak okna (``[]``), bo zawyżyłby
    zysk brutto, a za nim EBITDA, zdolność kredytową i wycenę."""

    ordered = sorted(complete)
    if not ordered:
        return []
    year, month = ordered[-1]
    out: list[tuple[int, int]] = []
    for i in range(count):
        # Miesiąc sprzed ``SETTLED_MONTHS`` miał czas na spływ faktur; niska
        # suma to krótki miesiąc (grudzień ze świętami), nie brak kosztów.
        if (year, month) not in complete and i < SETTLED_MONTHS:
            return []
        out.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return out


def gross_profit(rows: list[summary.MonthRow], months: list[tuple[int, int]]) -> float:
    keys = set(months)
    return sum(r.sales - r.costs for r in rows if (r.year, r.month) in keys)


def base_year(years: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Ostatni pełny rok z EBITDA (rok z księgi w toku się nie liczy)."""

    full = [
        y
        for y in years
        if y.get("partial_months") is None and y["metrics"].get("ebitda") is not None
    ]
    return max(full, key=lambda y: y["year"]) if full else None


#: Uwagi Rady z 19.11.2026: amortyzacja mała i mało znacząca — 1 mln zł rocznie.
AMORTIZATION = 1_000_000.0


def current_figures(
    base: Optional[dict[str, Any]],
    *,
    profit: Optional[float],
    sales: Optional[float],
    cash: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """EBITDA 12 mies. (zysk z faktur + amortyzacja), dług netto, zdolność
    kredytowa i wycena (PLN). ``base`` daje tylko dług, gotówkę i należności."""

    ebitda = None if profit is None else profit + AMORTIZATION
    debt = base["metrics"].get("financial_debt") if base else None
    statement_cash = base["amounts"].get("cash") if base else None
    if cash is not None and (
        base is None or cash["as_of"] > date(base["year"], 12, 31)
    ):
        cash_value, cash_source = cash["amount"], "entry"
    elif statement_cash is not None:
        cash_value, cash_source = statement_cash, "statement"
    else:
        cash_value, cash_source = 0.0, None
    net_debt = (debt or 0.0) - cash_value
    metrics = {"ebitda": ebitda, "net_debt": net_debt}
    receivables = base["amounts"].get("trade_receivables") if base else None
    return {
        "base_year": base["year"] if base else None,
        "base_source": base.get("source_label") if base else None,
        "profit": profit,
        "sales": sales,
        "amortization": AMORTIZATION,
        "ebitda": ebitda,
        "financial_debt": debt,
        "cash_used": cash_value,
        "cash_source": cash_source,
        "net_debt": net_debt,
        "credit": analysis.credit({"trade_receivables": receivables}, metrics),
        "valuation": analysis.valuation({"revenue": sales}, metrics),
    }


def year_end(view: dict[str, Any]) -> dict[str, Any]:
    """Sprzedaż i zysk brutto roku: wykonanie + prognoza z Budżetu (mln zł)."""

    actual = sum(m["sales"] or 0.0 for m in view["months"] if m["kind"] == "actual")
    actual_months = sum(1 for m in view["months"] if m["kind"] == "actual")
    real = view.get("realization")
    share = view.get("cost_share")
    forecast = [m for m in view["months"] if m["kind"] == "forecast"]
    if forecast and real is None:
        return {
            "actual_sales": round(actual, 2),
            "actual_months": actual_months,
            "sales_low": None,
            "sales_high": None,
            "reason": "Brak realizacji z ostatnich miesięcy — prognoza niepewna.",
        }
    low = actual + sum((m["potential"] or 0.0) * (real or 0) for m in forecast)
    high = actual + sum((m["potential_renewed"] or 0.0) * (real or 0) for m in forecast)
    plan = [m["plan_sales"] for m in view["months"]]
    plan_total = (
        round(sum(p for p in plan if p is not None), 2)
        if any(p is not None for p in plan)
        else None
    )

    def profit(sales: float) -> Optional[float]:
        return None if share is None else round(sales * (1 - share), 2)

    return {
        "actual_sales": round(actual, 2),
        "actual_months": actual_months,
        "sales_low": round(low, 2),
        "sales_high": round(high, 2),
        "profit_low": profit(low),
        "profit_high": profit(high),
        "profit_pct": None if share is None else round(100 * (1 - share), 1),
        "plan_sales": plan_total,
        "realization": real,
        "reason": None,
    }


async def latest_cash(db: AsyncSession) -> Optional[dict[str, Any]]:
    row = (
        await db.execute(
            select(BoardCashPosition).order_by(BoardCashPosition.as_of.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {"as_of": row.as_of, "amount": float(row.amount), "note": row.note}


async def outlook(db: AsyncSession, today: date) -> dict[str, Any]:
    analysis_data = await financials.analysis_view(db, today)
    base = base_year(analysis_data["years"])
    rows = await summary.month_rows(db, today.year - 3)
    complete = summary.complete_cost_months(rows)
    trailing = trailing_months(rows, complete)
    full = len(trailing) == 12
    keys = set(trailing)
    cash = await latest_cash(db)
    figures = current_figures(
        base,
        profit=gross_profit(rows, trailing) if full else None,
        sales=sum(r.sales for r in rows if (r.year, r.month) in keys) if full else None,
        cash=cash,
    )
    year_view = await budget.budget_view(db, today.year, today)

    def mln_tree(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (v if k in _NOT_MONEY else mln_tree(v)) for k, v in value.items()
            }
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _m(float(value))
        return value

    trailing_sorted = sorted(trailing)
    return {
        "cash": None
        if cash is None
        else {
            "as_of": cash["as_of"].isoformat(),
            "amount": _m(cash["amount"]),
            "note": cash["note"],
        },
        "statement_cash": None
        if base is None
        else {"year": base["year"], "amount": _m(base["amounts"].get("cash"))},
        "current": mln_tree(figures),
        "profit_window": {
            "from": f"{trailing_sorted[0][1]:02d}.{trailing_sorted[0][0]}",
            "to": f"{trailing_sorted[-1][1]:02d}.{trailing_sorted[-1][0]}",
        }
        if full
        else None,
        "year_end": {"year": today.year, **year_end(year_view)},
    }


#: Klucze, które nie są kwotami w PLN (mnożniki, lata, udziały, teksty).
_NOT_MONEY = {
    "base_year",
    "base_source",
    "cash_source",
    "debt_to_ebitda",
    "factoring_share",
    "multiple",
    "range",
    "ev_to_revenue",
}
