"""
Simple in-memory TTL cache for heavy API endpoints.
No external dependencies required — uses plain dict + timestamps.
"""

import time
import asyncio
import random
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple
import logging

from app.core import process_bus

logger = logging.getLogger(__name__)

# Global cache store: key → (value, expires_at)
_cache: Dict[str, Tuple[Any, float]] = {}
_lock = asyncio.Lock()


def _make_key(prefix: str, *args, **kwargs) -> str:
    """Build a deterministic cache key."""
    parts = [prefix]
    parts.extend(str(a) for a in args)
    parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return ":".join(parts)


async def cache_get(key: str) -> Optional[Any]:
    """Return cached value if not expired, else None."""
    async with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _cache[key]
            return None
        return value


async def cache_set(
    key: str, value: Any, ttl_seconds: int, *, jitter_seconds: float = 0.0
):
    """Store value in cache with TTL.

    ``jitter_seconds`` rozmywa moment wygaśnięcia (TTL + U(0, jitter)), żeby
    klucze napełnione w tej samej sekundzie (start dnia, 50 osób na dashboardzie)
    nie wygasały w tej samej sekundzie i nie wracały jako jedna fala przeliczeń.
    """
    ttl = ttl_seconds + (random.uniform(0.0, jitter_seconds) if jitter_seconds else 0.0)
    async with _lock:
        now = time.monotonic()
        _cache[key] = (value, now + ttl)
        _sweep_expired(now)


# Wygasły wpis znikał tylko przy odczycie tego samego klucza, więc klucze
# z id osoby albo rekrutacji, o które nikt już nie pyta, żyły do restartu
# i każda pełna zbiórka GC przechodziła je od nowa. Raz na minutę przy zapisie.
SWEEP_INTERVAL_SECONDS = 60.0
_next_sweep_at = 0.0


def _sweep_expired(now: float) -> None:
    """Usuń wygasłe wpisy, najwyżej raz na ``SWEEP_INTERVAL_SECONDS``; wołać pod ``_lock``."""
    global _next_sweep_at
    if now < _next_sweep_at:
        return
    _next_sweep_at = now + SWEEP_INTERVAL_SECONDS
    expired = [key for key, (_, expires_at) in _cache.items() if now > expires_at]
    for key in expired:
        del _cache[key]


def entry_count() -> int:
    """Liczba wpisów w cache (do `runtime_metrics`), bez blokady — tylko odczyt."""
    return len(_cache)


# ── Single-flight ────────────────────────────────────────────────────────────
#
# `_lock` chroni SŁOWNIK, nie obliczenie między `cache_get` a `cache_set`.
# Po wygaśnięciu TTL każde równoległe żądanie tego samego klucza widziało
# pustkę i liczyło ten sam ciężki snapshot od nowa (N razy `VERIFIER_ANCHORED_CTE`
# przy 50 osobach wchodzących na dashboard w tej samej sekundzie). Blokada per
# klucz sprawia, że liczy JEDNO żądanie, a reszta czeka i czyta gotowy wynik.
#
# Wzorzec użycia (podwójne sprawdzenie w środku jest częścią kontraktu):
#
#     async with cache_single_flight(cache_key):
#         cached = await cache_get(cache_key)
#         if cached is not None:
#             return cached
#         result = await expensive()
#         await cache_set(cache_key, result, ttl_seconds=120)
#         return result
#
# Wyjątek w środku zwalnia blokadę i NIE zapisuje nic — następne żądanie liczy
# samo. Blokady są lokalne procesu, jak sam cache.
_inflight: Dict[str, asyncio.Lock] = {}
_inflight_refs: Dict[str, int] = {}


@asynccontextmanager
async def cache_single_flight(key: str, *, db: Any = None) -> AsyncIterator[None]:
    """Serialize computation of one cache key across concurrent requests.

    ``db`` (sesja requestu) jest opcjonalne: gdy klucz liczy już ktoś inny,
    oczekujący oddaje swoje połączenie do puli przed czekaniem
    (`release_idle_connection`). Bez kontencji nic się nie dzieje — zwykłe
    trafienie w cache nie płaci za dodatkowy commit.
    """
    lock = _inflight.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _inflight[key] = lock
    _inflight_refs[key] = _inflight_refs.get(key, 0) + 1
    # `try` obejmuje WSZYSTKO po zwiększeniu licznika, także oddawanie sesji.
    # Anulowanie żądania (`CancelledError` nie jest `Exception`) w trakcie
    # `release_idle_connection` omijało wcześniej sprzątanie i zostawiało wpis
    # blokady na zawsze (reaudyt v2 14.09.2026, N01).
    try:
        if db is not None and lock.locked():
            from app.core.database import release_idle_connection

            try:
                await release_idle_connection(db)
            except Exception:  # pragma: no cover — zwolnienie jest optymalizacją
                # Sam prefiks: klucz niesie argumenty (np. tekst wyszukiwania)
                # — runda 7, R7-V5-2.
                logger.debug(
                    "release_idle_connection failed for %s",
                    key.split(":", 1)[0],
                    exc_info=True,
                )
        async with lock:
            yield
    finally:
        remaining = _inflight_refs.get(key, 1) - 1
        if remaining <= 0:
            _inflight.pop(key, None)
            _inflight_refs.pop(key, None)
        else:
            _inflight_refs[key] = remaining


_BUS_TOPIC = "cache_invalidate"


async def cache_invalidate(prefix: str):
    """Invalidate all keys starting with prefix — też w drugim procesie web i workerze."""
    await cache_evict_local(prefix)
    process_bus.publish_soon(_BUS_TOPIC, {"prefix": prefix})


async def _on_remote_invalidate(data: dict) -> None:
    await cache_evict_local(str(data["prefix"]))


process_bus.subscribe(_BUS_TOPIC, _on_remote_invalidate, others_only=True)


async def cache_evict_local(prefix: str) -> None:
    """Usuń wpisy tylko w TYM procesie — sprzątanie, nie zmiana danych.

    Do wyrzucania starszych migawek tuż przed zapisem nowej: rozgłoszone
    kasowałoby drugiemu procesowi jego świeży wpis i oba liczyłyby w kółko.
    """
    async with _lock:
        keys_to_delete = [k for k in _cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del _cache[k]
    logger.debug(f"Cache invalidated: {prefix} ({len(keys_to_delete)} keys)")


def cached(ttl_seconds: int, key_prefix: str):
    """
    Decorator for async endpoint functions.
    Caches the return value for ttl_seconds.
    The cache key includes all function arguments.

    Usage:
        @cached(ttl_seconds=120, key_prefix="dashboard_kpis")
        async def get_kpis(current_user, db):
            ...
    """

    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # Build cache key from kwargs that are simple scalars
            cache_kwargs = {
                k: v
                for k, v in kwargs.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }
            key = _make_key(key_prefix, **cache_kwargs)

            cached_value = await cache_get(key)
            if cached_value is not None:
                logger.debug("Cache HIT: %s", key_prefix)
                return cached_value

            logger.debug("Cache MISS: %s", key_prefix)
            result = await func(*args, **kwargs)
            await cache_set(key, result, ttl_seconds)
            return result

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
