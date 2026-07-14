"""Decimal-safe conversion helpers for analytics finance responses.

The public finance API is PLN-only.  A missing historical NBP rate invalidates
the monetary aggregate instead of silently treating unlike currencies as if
they were PLN.  Query callers batch-load rates and pass currency-level rows to
these pure helpers, which keeps the behaviour straightforward to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import AnalyticsQualityStatus


MONEY_QUANTUM = Decimal("0.01")


def money_string(value: Decimal | None) -> str | None:
    """Serialize money without a binary-float round trip."""

    if value is None:
        return None
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), "f")


@dataclass(frozen=True)
class ConvertedFinance:
    revenue: Decimal | None
    costs: Decimal | None
    margin: Decimal | None
    active_contracts: int
    incomplete_contracts: int
    missing_currencies: tuple[str, ...] = ()

    @property
    def quality_status(self) -> AnalyticsQualityStatus:
        if self.missing_currencies:
            return AnalyticsQualityStatus.unavailable
        if self.incomplete_contracts:
            return AnalyticsQualityStatus.partial
        return AnalyticsQualityStatus.complete

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.missing_currencies:
            currencies = ", ".join(self.missing_currencies)
            warnings.append(
                "Missing NBP rate for "
                f"{currencies}; monetary totals are unavailable to prevent "
                "nominal currency mixing."
            )
        if self.incomplete_contracts:
            warnings.append(
                f"{self.incomplete_contracts} active contract(s) have incomplete "
                "rate data and are excluded from monetary totals."
            )
        return warnings


FxHistory = Mapping[str, tuple[tuple[date, Decimal], ...]]


async def load_fx_history(
    db: AsyncSession,
    *,
    currencies: Iterable[str],
    through: date,
) -> dict[str, tuple[tuple[date, Decimal], ...]]:
    """Load all required FX rows in one indexed query (no per-currency N+1)."""

    requested = sorted(
        {str(currency or "PLN").upper() for currency in currencies} - {"PLN"}
    )
    if not requested:
        return {}

    result = await db.execute(
        text(
            """
            SELECT currency, effective_date, rate_to_pln
            FROM fx_rates
            WHERE currency = ANY(CAST(:currencies AS varchar[]))
              AND effective_date <= :through
              AND source = 'NBP'
            ORDER BY currency, effective_date
            """
        ),
        {"currencies": requested, "through": through},
    )
    history: dict[str, list[tuple[date, Decimal]]] = {}
    for row in result.mappings().all():
        history.setdefault(str(row["currency"]).upper(), []).append(
            (row["effective_date"], Decimal(row["rate_to_pln"]))
        )
    return {currency: tuple(rows) for currency, rows in history.items()}


def rate_on_or_before(
    currency: str,
    *,
    report_date: date,
    history: FxHistory,
) -> Decimal | None:
    normalized = str(currency or "PLN").upper()
    if normalized == "PLN":
        return Decimal("1")
    matching = history.get(normalized, ())
    for effective_date, rate in reversed(matching):
        if effective_date <= report_date:
            return Decimal(rate)
    return None


def convert_currency_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    report_date: date,
    history: FxHistory,
) -> ConvertedFinance:
    """Convert currency-level monthly amounts to PLN or fail the whole sum."""

    revenue = Decimal("0")
    costs = Decimal("0")
    active_contracts = 0
    incomplete_contracts = 0
    missing: set[str] = set()

    for row in rows:
        currency = str(row.get("currency") or "PLN").upper()
        active_contracts += int(row.get("active_contracts") or 0)
        incomplete_contracts += int(row.get("incomplete_contracts") or 0)
        rate = rate_on_or_before(
            currency,
            report_date=report_date,
            history=history,
        )
        if rate is None:
            # Only flag currencies that actually carry a convertible amount.
            if row.get("revenue") is not None or row.get("costs") is not None:
                missing.add(currency)
            continue
        revenue += Decimal(row.get("revenue") or 0) * rate
        costs += Decimal(row.get("costs") or 0) * rate

    if missing:
        return ConvertedFinance(
            revenue=None,
            costs=None,
            margin=None,
            active_contracts=active_contracts,
            incomplete_contracts=incomplete_contracts,
            missing_currencies=tuple(sorted(missing)),
        )

    return ConvertedFinance(
        revenue=revenue,
        costs=costs,
        margin=revenue - costs,
        active_contracts=active_contracts,
        incomplete_contracts=incomplete_contracts,
    )


def margin_percentage(finance: ConvertedFinance) -> float | None:
    """Return monthly margin / monthly revenue, guarding a zero denominator."""

    if finance.margin is None or finance.revenue in (None, Decimal("0")):
        return None
    return round(float(finance.margin / finance.revenue * Decimal("100")), 2)
