"""NBP FX rate fetcher + per-date lookup.

NBP daily table A (https://api.nbp.pl/api/exchangerates/tables/a/) lists middle
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

NBP_URL = "https://api.nbp.pl/api/exchangerates/tables/a/"

# Powyżej tego wieku cache kursów uznajemy za zamrożony: `/api/health.checks.fx`
# schodzi w `degraded`, a odczyt zostawia ślad w logu. NBP publikuje tabelę A
# w dni robocze, a najdłuższa normalna przerwa (Boże Narodzenie / Wielkanoc) to
# cztery dni — siedem daje zapas, którego zwykły weekend ani święto nie
# przekroczy, a dwutygodniowa cisza owszem. Świadomie NIE wpływa na wynik
# przeliczenia; dlaczego — patrz docstring `get_rate_to_pln`.
MAX_RATE_AGE_DAYS = 7

# Waluta-kanarek dla sondy zdrowia. Pobranie zapisuje CAŁĄ tabelę A w jednej
# transakcji, więc wiek dowolnej pozycji opisuje wiek całego cache'u; EUR jest
# w tabeli A od zawsze, więc nie zniknie z niej przy zmianie koszyka.
HEALTH_CANARY_CURRENCY = "EUR"


class NbpFetchError(RuntimeError):
    """Pobranie tabeli A nie doszło do skutku (transport albo kształt payloadu).

    Istnieje po to, żeby `fx_refresh_loop` miało co złapać. Wcześniej każda
    ścieżka błędu kończyła się `return 0` i `logger.warning`, więc gałąź
    `except` pętli była nieosiągalna, a system nie umiał odróżnić „NBP nie
    opublikował nic nowego" od „NBP jest nieosiągalny od miesiąca".
    """


async def fetch_and_store_nbp_today(*, strict: bool = False) -> int:
    """Fetch today's NBP table A and insert any missing rows. Returns row count.

    ``strict=True`` (używa go `fx_refresh_loop`) przepuszcza
    :class:`NbpFetchError` do wywołującego, żeby dało się odróżnić „NBP nie
    opublikował nic nowego" od „NBP jest nieosiągalny od miesiąca". Domyślne
    ``strict=False`` zachowuje kontrakt ręcznego triggera admina
    (``POST /api/fx/refresh`` ma zwracać 200 z ``inserted: 0``, a nie 500) —
    ale awaria leci teraz przez `logger.exception`, czyli na poziomie ERROR,
    więc Sentry (`event_level=logging.ERROR`) w ogóle ją widzi. Wcześniej
    KAŻDA ścieżka błędu kończyła się cichym ``return 0``, a dwie z nich nie
    logowały nawet linijki.
    """
    try:
        return await _fetch_and_store_nbp_today()
    except NbpFetchError:
        if strict:
            raise
        logger.exception("NBP fetch failed — cache kursów nie został odświeżony")
        return 0


async def _fetch_and_store_nbp_today() -> int:
    """Właściwe pobranie. Rzuca :class:`NbpFetchError` na każdej awarii."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NBP_URL, params={"format": "json"})
            if resp.status_code != 200:
                raise NbpFetchError(f"NBP fetch failed: HTTP {resp.status_code}")
            payload = resp.json()
    except NbpFetchError:
        raise
    except Exception as e:  # noqa: BLE001
        raise NbpFetchError(f"NBP fetch error: {e!r}") from e
    if not isinstance(payload, list) or not payload:
        raise NbpFetchError(
            f"NBP payload of unexpected shape: {type(payload).__name__}"
        )
    table = payload[0]
    effective_date_str = table.get("effectiveDate")
    rates = table.get("rates", [])
    if not effective_date_str:
        raise NbpFetchError("NBP payload without effectiveDate")
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

    Przeterminowanie NIE zmienia ``rate_found`` — i to jest świadoma decyzja,
    a nie przeoczenie. Flaga jest PRZECIĄŻONA: `margin_by_contractor` /
    `margin_by_client` tylko zapalają na niej `fx_missing`, ale
    `revenue_forecast._to_display` traktuje ją jako polecenie WYKLUCZENIA kwoty
    z prognozy (`return None`). Zamrożony kurs EUR sprzed dwóch miesięcy myli
    się o kilka procent; wycięcie kontraktu z przychodu myli się o 100%.
    Sygnałem o przeterminowanym cache'u jest ``/api/health.checks.fx``
    (:func:`fx_age_days` + :data:`MAX_RATE_AGE_DAYS`) — adresowany do operatora,
    który ma to naprawić, a nie do raportu, który miałby po cichu zgubić
    pieniądze.
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
    if (target - row.effective_date).days > MAX_RATE_AGE_DAYS:
        # Loguj, ale NIE degraduj `rate_found` — patrz docstring. To jest jedyne
        # miejsce per-waluta, w którym zamrożony cache w ogóle zostawia ślad;
        # decyzję operacyjną niesie `/api/health.checks.fx`.
        logger.warning(
            "fx: stale rate for %s — newest is %s, older than %d days (asof %s)",
            cur,
            row.effective_date,
            MAX_RATE_AGE_DAYS,
            target,
        )
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


async def rates_to_pln(
    db: AsyncSession, currencies: set[str], on: Optional[date] = None
) -> dict[str, Optional[Decimal]]:
    """Report FX rate per currency → PLN: latest cached rate with
    ``effective_date <= on`` (default today), keyed by upper-case code.

    Unlike :func:`convert_to_pln`, a currency with **no** cached rate maps to
    ``None`` — never a silent 1:1. Callers summing money across currencies must
    therefore exclude those amounts and flag the total as incomplete rather than
    under-report a foreign amount as if it were the same number of PLN. Mirrors
    ``app.analytics.metrics._fx_rates_to_pln`` (the canonical finance summation).

    ``None`` znaczy BRAK kursu, nigdy „kurs przeterminowany" — tak samo jak w
    :func:`get_rate_to_pln`. Wywołujący traktują ``None`` jako polecenie
    WYKLUCZENIA kwoty z sumy, a wykluczenie faktury w EUR myli się o 100%,
    podczas gdy przeliczenie jej po kursie sprzed dwóch miesięcy — o kilka
    procent. Sygnał o zamrożonym cache'u należy do operatora i jedzie przez
    ``/api/health.checks.fx``, a nie przez ciche wycinanie pieniędzy z raportu.
    """
    on = on or date.today()
    out: dict[str, Optional[Decimal]] = {}
    for raw in currencies:
        code = (raw or "PLN").upper()
        if code in out:
            continue
        if code == "PLN":
            out[code] = Decimal("1")
            continue
        row = (
            await db.execute(
                select(FxRate.rate_to_pln)
                .where(FxRate.currency == code, FxRate.effective_date <= on)
                .order_by(FxRate.effective_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out[code] = Decimal(row) if row is not None else None
    return out


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

    Awaria pobrania jest teraz WIDOCZNA: `fetch_and_store_nbp_today` rzuca
    :class:`NbpFetchError`, a ta gałąź loguje na poziomie ERROR, więc Sentry
    (`event_level=logging.ERROR`) dostaje zdarzenie. Wcześniej każda ścieżka
    błędu kończyła się `return 0`, więc pętla nie miała czego złapać i
    kilkumiesięczna cisza NBP wyglądała dokładnie jak dzień bez nowej tabeli.
    """
    import asyncio

    logger.info("fx_refresh_loop: started interval=%.1f h", interval_hours)
    # Initial delay to keep startup snappy.
    await asyncio.sleep(60)
    while True:
        try:
            await fetch_and_store_nbp_today(strict=True)
        except Exception:  # noqa: BLE001
            logger.exception("fx_refresh_loop: cycle error")
        await asyncio.sleep(interval_hours * 3600)
