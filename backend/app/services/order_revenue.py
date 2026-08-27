"""Currency-safe aggregation of ClientOrder revenue for finance surfaces."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrderStatus
from app.services.fx_service import rates_to_pln


def fold_order_revenue_rows_pln(
    rows: Sequence[Any],
    fx_rates: dict[str, Optional[Decimal]],
) -> tuple[dict[int, dict[str, Decimal]], set[int]]:
    """Fold grouped ``client/status/currency/sum_val`` rows into PLN.

    A client with any unavailable required rate is marked incomplete. Callers
    must expose its totals as unavailable rather than publishing a partial sum.
    """

    totals: dict[int, dict[str, Decimal]] = {}
    incomplete: set[int] = set()
    for row in rows:
        status = getattr(row.status, "value", row.status)
        if status == ClientOrderStatus.cancelled.value:
            continue
        client_id = int(row.client_id)
        raw_value = Decimal(row.sum_val or 0)
        if raw_value == 0:
            totals.setdefault(
                client_id,
                {
                    "total": Decimal("0"),
                    "active": Decimal("0"),
                    "completed": Decimal("0"),
                },
            )
            continue
        currency = (row.currency or "PLN").strip().upper()
        fx = fx_rates.get(currency)
        if fx is None:
            incomplete.add(client_id)
            continue
        value = raw_value * fx
        slot = totals.setdefault(
            client_id,
            {
                "total": Decimal("0"),
                "active": Decimal("0"),
                "completed": Decimal("0"),
            },
        )
        slot["total"] += value
        if status == ClientOrderStatus.active.value:
            slot["active"] += value
        elif status == ClientOrderStatus.completed.value:
            slot["completed"] += value
    return totals, incomplete


async def order_revenue_rows_to_pln(
    db: AsyncSession,
    rows: Sequence[Any],
    on: date,
) -> tuple[dict[int, dict[str, Decimal]], set[int]]:
    currencies = {
        (row.currency or "PLN").strip().upper()
        for row in rows
        if Decimal(row.sum_val or 0) != 0
    }
    fx_rates = await rates_to_pln(db, currencies, on)
    return fold_order_revenue_rows_pln(rows, fx_rates)
