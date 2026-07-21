"""NBP FX rate fetcher + per-date lookup.

NBP daily table A (http://api.nbp.pl/api/exchangerates/tables/a/) lists middle
rates for major currencies. We cache whatever we fetch in the fx_rates table
so subsequent conversions don't hit the network.

All functions are best-effort: if NBP is unreachable or a currency isn't
listed, we return the most recent known rate (falling back to 1.0 for PLN).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.fx_rate import FxRate

logger = logging.getLogger(__name__)

NBP_URL = "http://api.nbp.pl/api/exchangerates/tables/a/"


async def fetch_and_store_nbp_today() -> int:
    """Fetch today's NBP table A and insert any missing rows. Returns row count."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NBP_URL, params={"format": "json"})
            if resp.status_code != 200:
                logger.warning("NBP fetch failed: HTTP %s", resp.status_code)
                return 0
            payload = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("NBP fetch error: %s", e)
        return 0
    if not isinstance(payload, list) or not payload:
        return 0
    table = payload[0]
    effective_date_str = table.get("effectiveDate")
    rates = table.get("rates", [])
    if not effective_date_str:
        return 0
    effective_date = date.fromisoformat(effective_date_str)
    inserted = 0
    async with AsyncSessionLocal() as db:
        for r in rates:
            code = r.get("code")
            mid = r.get("mid")
            if not code or mid is None:
                continue
            existing = await db.scalar(
                select(FxRate).where(
                    FxRate.effective_date == effective_date,
                    FxRate.currency == code,
                )
            )
            if existing is not None:
                continue
            db.add(
                FxRate(
                    effective_date=effective_date,
                    currency=code,
                    rate_to_pln=Decimal(str(mid)),
                    source="NBP",
                )
            )
            inserted += 1
        await db.commit()
    logger.info("NBP fetch: stored %d new rates for %s", inserted, effective_date)
    return inserted


async def get_rate_to_pln(
    db: AsyncSession, currency: str, on: Optional[date] = None
) -> tuple[Decimal, bool]:
    """Resolve the multiplier for ``currency → PLN`` on a date (default today).

    Returns ``(rate, rate_found)``. ``rate`` is ``1`` for PLN and for any
    currency with no cached rate (a 1:1 degradation, kept non-fatal so a
    missing rate never 500s a dashboard). ``rate_found`` is ``False`` on that
    fallback so callers can surface a ``fx_missing`` / degraded signal instead
    of silently reporting a wrong number (M7-P0.11).
    """
    cur = (currency or "PLN").upper()
    if cur == "PLN":
        return Decimal("1"), True
    target = on or date.today()
    # Find closest rate not newer than `target`; fall back to most recent overall.
    res = await db.execute(
        select(FxRate)
        .where(FxRate.currency == cur, FxRate.effective_date <= target)
        .order_by(FxRate.effective_date.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        res = await db.execute(
            select(FxRate)
            .where(FxRate.currency == cur)
            .order_by(FxRate.effective_date.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
    if row is None:
        # No rate at all — degrade gracefully to 1:1 rather than crash, but make
        # it observable so a missing rate isn't silently mispriced.
        logger.warning(
            "fx: no cached rate for %s (asof %s) — using 1:1 fallback (degraded)",
            cur,
            target,
        )
        return Decimal("1"), False
    return row.rate_to_pln, True


async def convert_to_pln_detail(
    db: AsyncSession, amount: Decimal | int, currency: str, on: Optional[date] = None
) -> tuple[Decimal, bool]:
    """Like :func:`convert_to_pln` but also reports whether a rate was found.

    The second tuple element is ``False`` when the conversion fell back to 1:1
    because no FX rate is cached for ``currency`` — callers summing across
    currencies use it to flag a degraded (``fx_missing``) result.
    """
    if amount is None:
        return Decimal("0"), True
    rate, found = await get_rate_to_pln(db, currency, on)
    return Decimal(amount) * rate, found


async def convert_to_pln(
    db: AsyncSession, amount: Decimal | int, currency: str, on: Optional[date] = None
) -> Decimal:
    """Return `amount × rate(currency→PLN)` for the given date (default today)."""
    converted, _ = await convert_to_pln_detail(db, amount, currency, on)
    return converted


async def fx_age_days(db: AsyncSession, currency: str) -> Optional[int]:
    """Return age of the most recent cached rate for a currency, or None if absent."""
    cur = currency.upper()
    if cur == "PLN":
        return 0
    res = await db.execute(
        select(FxRate)
        .where(FxRate.currency == cur)
        .order_by(FxRate.effective_date.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None
    return (date.today() - row.effective_date).days


_ = timedelta  # silence unused-import warning if tests add variations later


async def fx_refresh_loop(interval_hours: float = 24.0) -> None:
    """Long-running task — fetch NBP table A once a day.

    Best-effort: if NBP is down, the cycle silently logs and retries next day.
    """
    import asyncio

    logger.info("fx_refresh_loop: started interval=%.1f h", interval_hours)
    # Initial delay to keep startup snappy.
    await asyncio.sleep(60)
    while True:
        try:
            await fetch_and_store_nbp_today()
        except Exception as e:  # noqa: BLE001
            logger.warning("fx_refresh_loop: cycle error %s", e)
        await asyncio.sleep(interval_hours * 3600)
