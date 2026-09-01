"""NBP FX rate fetcher + per-date lookup.

NBP daily table A (https://api.nbp.pl/api/exchangerates/tables/a/) lists middle
rates for major currencies. We cache whatever we fetch in the fx_rates table
so subsequent conversions don't hit the network.

All functions are best-effort: if NBP is unreachable or a currency isn't
listed, we return the most recent known rate (falling back to 1.0 for PLN).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import is_business_day, local_now
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

# NBP declares table A between 11:45 and 12:15 on Polish business days. Start
# at the opening of that window and retry for delayed publications/network
# hiccups; once today's effective date is persisted, sleep until the next
# business-day window. This avoids the old 24-hour schedule being anchored to
# an arbitrary container start time (e.g. 08:00 forever serving yesterday).
NBP_TABLE_A_PUBLISH_START = time(11, 45)
NBP_TABLE_A_RETRY_UNTIL = time(16, 30)
NBP_TABLE_A_RETRY_MINUTES = 15.0


@dataclass(frozen=True)
class FxRateSnapshot:
    """Persisted FX value together with the date published by its source.

    Contract UI must show the real NBP ``effectiveDate``. Returning just a
    multiplier would tempt callers to label Friday's rate with Sunday's date,
    which is precisely the fallback case the product needs to make explicit.
    """

    currency: str
    rate_to_pln: Decimal
    effective_date: date
    source: str


class NbpFetchError(RuntimeError):
    """Pobranie tabeli A nie doszło do skutku (transport albo kształt payloadu).

    Istnieje po to, żeby `fx_refresh_loop` miało co złapać. Wcześniej każda
    ścieżka błędu kończyła się `return 0` i `logger.warning`, więc gałąź
    `except` pętli była nieosiągalna, a system nie umiał odróżnić „NBP nie
    opublikował nic nowego" od „NBP jest nieosiągalny od miesiąca".
    """


def amount_to_pln_with_rate(
    amount: Decimal | int | float | None,
    rate_to_pln: Optional[Decimal],
) -> tuple[Optional[Decimal], bool]:
    """Apply an already resolved PLN rate without inventing missing FX.

    ``complete`` is false only when a *non-zero* amount needs an unavailable
    rate. Zero is currency-independent, so ``0 USD`` remains a complete
    ``0 PLN`` even when no USD quote exists. ``None`` means no priced leg and
    is likewise not an FX-quality failure.
    """

    if amount is None:
        return None, True
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if value == 0:
        return Decimal("0"), True
    if rate_to_pln is None:
        return None, False
    return value * rate_to_pln, True


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
    rows_to_insert = []
    for r in rates:
        code = r.get("code")
        mid = r.get("mid")
        if not code or mid is None:
            continue
        rows_to_insert.append(
            {
                "effective_date": effective_date,
                "currency": code,
                "rate_to_pln": Decimal(str(mid)),
                "source": "NBP",
            }
        )
    inserted = 0
    async with AsyncSessionLocal() as db:
        if rows_to_insert:
            # Admin refresh and the background loop can overlap. The database
            # unique index is the arbiter; SELECT-then-INSERT raced and could
            # turn an otherwise successful refresh into an IntegrityError.
            stmt = (
                pg_insert(FxRate)
                .values(rows_to_insert)
                .on_conflict_do_nothing(
                    index_elements=[FxRate.effective_date, FxRate.currency]
                )
                .returning(FxRate.id)
            )
            inserted = len((await db.execute(stmt)).scalars().all())
        await db.commit()
    logger.info("NBP fetch: stored %d new rates for %s", inserted, effective_date)
    return inserted


# Historyczna seria JEDNEJ waluty. Tabela A ma osobny endpoint na zakres dat;
# `NBP_URL` (cała tabela) zwraca wyłącznie NAJNOWSZE notowanie, więc luk
# w przeszłości nie da się nim zasypać — a to właśnie ich dotyczy `degraded.fx`
# w kokpicie zarządu.
NBP_SERIES_URL = (
    "https://api.nbp.pl/api/exchangerates/rates/a/{currency}/{start}/{end}/"
)

# NBP odmawia (400) zakresom dłuższym niż 367 dni, więc dzielimy na kawałki.
NBP_MAX_RANGE_DAYS = 300


async def backfill_nbp_rates(currency: str, start: date, end: date) -> dict:
    """Dociągnij historyczne kursy JEDNEJ waluty i wstaw brakujące wiersze.

    Powstało, bo `fetch_and_store_nbp_today` pobiera WYŁĄCZNIE dzisiejszą
    tabelę, a `rates_to_pln_by_date` szuka „najnowszego kursu nie później niż
    dana data". Miesiąc bez ani jednego notowania w cache'u przed swoją
    granicą nie ma więc czym być wyceniony i wypada z sum — dokładnie to
    widać było na produkcji: siedem kolejnych miesięcy (2025-10 … 2026-04)
    z kwotami EUR POMINIĘTYMI, przy komunikacie podpowiadającym
    `POST /api/fx/refresh`, który tego nie naprawia.

    Idempotentne: `ON CONFLICT DO NOTHING` na `(effective_date, currency)`,
    ten sam arbiter co przy odświeżaniu dziennym. Dni bez notowania (weekendy,
    święta) po prostu nie istnieją w odpowiedzi NBP i nie są błędem.

    Zwraca licznik wstawionych wierszy ORAZ zakresy, które NBP odrzucił —
    cichy `inserted: 0` nie odróżniałby „wszystko już było" od „nie pobrano nic".
    """
    code = (currency or "").upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"Nieprawidłowy kod waluty: {currency!r}")
    if start > end:
        raise ValueError("Data początkowa jest późniejsza niż końcowa")

    inserted = 0
    fetched = 0
    failed_chunks: list[str] = []

    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=NBP_MAX_RANGE_DAYS - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    async with httpx.AsyncClient(timeout=20.0) as client:
        for chunk_start, chunk_end in chunks:
            url = NBP_SERIES_URL.format(
                currency=code.lower(),
                start=chunk_start.isoformat(),
                end=chunk_end.isoformat(),
            )
            try:
                resp = await client.get(url, params={"format": "json"})
            except Exception as exc:  # noqa: BLE001
                failed_chunks.append(f"{chunk_start}..{chunk_end}: {exc!r}")
                continue
            # 404 = NBP nie ma notowań w tym zakresie (np. przyszłość albo
            # okres sprzed publikacji). To informacja, nie awaria.
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                failed_chunks.append(
                    f"{chunk_start}..{chunk_end}: HTTP {resp.status_code}"
                )
                continue
            payload = resp.json()
            rows_to_insert = []
            for r in payload.get("rates", []):
                eff = r.get("effectiveDate")
                mid = r.get("mid")
                if not eff or mid is None:
                    continue
                rows_to_insert.append(
                    {
                        "effective_date": date.fromisoformat(eff),
                        "currency": code,
                        "rate_to_pln": Decimal(str(mid)),
                        "source": "NBP",
                    }
                )
            fetched += len(rows_to_insert)
            if not rows_to_insert:
                continue
            async with AsyncSessionLocal() as db:
                stmt = (
                    pg_insert(FxRate)
                    .values(rows_to_insert)
                    .on_conflict_do_nothing(
                        index_elements=[FxRate.effective_date, FxRate.currency]
                    )
                    .returning(FxRate.id)
                )
                inserted += len((await db.execute(stmt)).scalars().all())
                await db.commit()

    logger.info(
        "NBP backfill %s %s..%s: pobrano %d notowań, wstawiono %d, nieudanych zakresów %d",
        code,
        start,
        end,
        fetched,
        inserted,
        len(failed_chunks),
    )
    return {
        "currency": code,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fetched": fetched,
        "inserted": inserted,
        "failed_ranges": failed_chunks,
    }


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


async def get_rate_snapshot_to_pln(
    db: AsyncSession, currency: str, on: Optional[date] = None
) -> Optional[FxRateSnapshot]:
    """Return the newest persisted rate not newer than ``on``.

    Unlike :func:`get_rate_to_pln`, absence stays ``None``. A contract detail
    may omit a conversion while the cache is temporarily empty, but it must
    never present a fabricated 1:1 EUR/PLN conversion. The shared ``fx_rates``
    table is the durable per-publication cache for every contract, so opening
    multiple EUR contracts never repeats an NBP request.
    """

    cur = (currency or "").upper()
    if not cur or cur == "PLN":
        return None
    target = on or date.today()
    row = (
        await db.execute(
            select(FxRate)
            .where(FxRate.currency == cur, FxRate.effective_date <= target)
            .order_by(FxRate.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return FxRateSnapshot(
        currency=row.currency,
        rate_to_pln=row.rate_to_pln,
        effective_date=row.effective_date,
        source=row.source,
    )


async def convert_to_pln_detail(
    db: AsyncSession, amount: Decimal | int, currency: str, on: Optional[date] = None
) -> tuple[Decimal, bool]:
    """Like :func:`convert_to_pln` but also reports whether a rate was found.

    The second tuple element is ``False`` when the conversion fell back to 1:1
    because no FX rate is cached for ``currency`` — callers summing across
    currencies use it to flag a degraded (``fx_missing``) result.
    """
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if value == 0:
        return Decimal("0"), True
    rate, found = await get_rate_to_pln(db, currency, on)
    return value * rate, found


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


async def rates_to_pln_by_date(
    db: AsyncSession,
    currencies_by_date: Mapping[date, set[str]],
) -> dict[date, dict[str, Optional[Decimal]]]:
    """Resolve many historical date/currency snapshots with one DB query.

    Each result uses the latest cached rate whose effective date is not later
    than that boundary, matching :func:`rates_to_pln`. This avoids an N×M
    query pattern on archive views with many distinct contract end dates.
    """

    if not currencies_by_date:
        return {}
    normalized = {
        boundary: {(raw or "PLN").upper() for raw in currencies}
        for boundary, currencies in currencies_by_date.items()
    }
    foreign = {
        currency
        for currencies in normalized.values()
        for currency in currencies
        if currency != "PLN"
    }
    history: dict[str, list[tuple[date, Decimal]]] = {
        currency: [] for currency in foreign
    }
    if foreign:
        rows = (
            await db.execute(
                select(
                    FxRate.currency,
                    FxRate.effective_date,
                    FxRate.rate_to_pln,
                )
                .where(
                    FxRate.currency.in_(foreign),
                    FxRate.effective_date <= max(normalized),
                )
                .order_by(FxRate.currency, FxRate.effective_date)
            )
        ).all()
        for row in rows:
            history.setdefault(row.currency, []).append(
                (row.effective_date, Decimal(row.rate_to_pln))
            )

    resolved: dict[date, dict[str, Optional[Decimal]]] = {}
    for boundary, currencies in normalized.items():
        snapshot: dict[str, Optional[Decimal]] = {}
        for currency in currencies:
            if currency == "PLN":
                snapshot[currency] = Decimal("1")
                continue
            snapshot[currency] = next(
                (
                    rate
                    for effective_date, rate in reversed(history.get(currency, []))
                    if effective_date <= boundary
                ),
                None,
            )
        resolved[boundary] = snapshot
    return resolved


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


async def _latest_cached_effective_date(currency: str) -> Optional[date]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(FxRate.effective_date)
            .where(FxRate.currency == currency.upper())
            .order_by(FxRate.effective_date.desc())
            .limit(1)
        )


def _seconds_until_next_nbp_window(now: datetime) -> float:
    """Seconds until 11:45 on the next Polish business day."""

    candidate = now.replace(
        hour=NBP_TABLE_A_PUBLISH_START.hour,
        minute=NBP_TABLE_A_PUBLISH_START.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    while not is_business_day(candidate):
        candidate += timedelta(days=1)
    # Subtract instants in UTC. Python intentionally uses wall-clock arithmetic
    # for two datetimes carrying the same ZoneInfo, which would miss the one-hour
    # DST jump on a weekend and wake the refresh loop an hour late.
    return max(
        60.0,
        (
            candidate.astimezone(timezone.utc) - now.astimezone(timezone.utc)
        ).total_seconds(),
    )


def _should_refresh_nbp(now: datetime, latest: Optional[date]) -> bool:
    """Whether this cycle should call NBP rather than use the durable cache."""

    if latest is None:
        return True
    return (
        is_business_day(now)
        and now.time() >= NBP_TABLE_A_PUBLISH_START
        and latest < now.date()
    )


async def fx_refresh_loop(
    retry_minutes: float = NBP_TABLE_A_RETRY_MINUTES,
) -> None:
    """Keep NBP table A current according to its Warsaw publication window.

    Awaria pobrania jest teraz WIDOCZNA: `fetch_and_store_nbp_today` rzuca
    :class:`NbpFetchError`, a ta gałąź loguje na poziomie ERROR, więc Sentry
    (`event_level=logging.ERROR`) dostaje zdarzenie. Wcześniej każda ścieżka
    błędu kończyła się `return 0`, więc pętla nie miała czego złapać i
    kilkumiesięczna cisza NBP wyglądała dokładnie jak dzień bez nowej tabeli.
    """
    import asyncio

    retry_seconds = max(60.0, retry_minutes * 60)
    logger.info("fx_refresh_loop: started retry=%.1f min", retry_minutes)
    # Initial delay to keep startup snappy.
    await asyncio.sleep(60)
    while True:
        delay = retry_seconds
        try:
            now = local_now()
            latest = await _latest_cached_effective_date(HEALTH_CANARY_CURRENCY)
            # Populate a brand-new cache on startup. Once any rate exists, a
            # restart must not create a gratuitous NBP dependency (especially
            # on weekends); normal Warsaw publication-window rules take over.
            if _should_refresh_nbp(now, latest):
                await fetch_and_store_nbp_today(strict=True)
                latest = await _latest_cached_effective_date(HEALTH_CANARY_CURRENCY)

            now = local_now()
            local_time = now.time()
            waiting_for_today = latest is None or latest < now.date()
            if (
                is_business_day(now)
                and waiting_for_today
                and NBP_TABLE_A_PUBLISH_START <= local_time <= NBP_TABLE_A_RETRY_UNTIL
            ):
                delay = retry_seconds
                logger.info(
                    "fx_refresh_loop: latest=%s, retrying in %.1f min",
                    latest,
                    retry_minutes,
                )
            else:
                delay = _seconds_until_next_nbp_window(now)
        except Exception:  # noqa: BLE001
            logger.exception("fx_refresh_loop: cycle error")
            now = local_now()
            if not (
                is_business_day(now)
                and NBP_TABLE_A_PUBLISH_START <= now.time() <= NBP_TABLE_A_RETRY_UNTIL
            ):
                delay = _seconds_until_next_nbp_window(now)
        await asyncio.sleep(delay)
