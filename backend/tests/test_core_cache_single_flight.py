"""`cache_single_flight` — jeden wykonawca na klucz, reszta czeka na wynik.

Czysty test jednostkowy (bez bazy). Do 09.2026 `_lock` w `app/core/cache.py`
chronił tylko słownik: po wygaśnięciu TTL każde równoległe żądanie tego samego
klucza liczyło ciężki snapshot od nowa.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import cache as cache_mod
from app.core.cache import (
    cache_get,
    cache_invalidate,
    cache_set,
    cache_single_flight,
)


async def _get_or_compute(key: str, compute, ttl: int = 60):
    async with cache_single_flight(key):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        value = await compute()
        await cache_set(key, value, ttl_seconds=ttl)
        return value


@pytest.mark.asyncio
async def test_fifty_concurrent_cold_reads_compute_once():
    await cache_invalidate("sf:")
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"n": calls}

    results = await asyncio.gather(
        *(_get_or_compute("sf:cold", compute) for _ in range(50))
    )
    assert calls == 1
    assert all(r == {"n": 1} for r in results)
    # Blokada nie zostaje po zakończeniu — brak wycieku wpisów per klucz.
    assert "sf:cold" not in cache_mod._inflight
    assert "sf:cold" not in cache_mod._inflight_refs


@pytest.mark.asyncio
async def test_failed_compute_releases_lock_and_caches_nothing():
    await cache_invalidate("sf:")
    attempts = 0

    async def compute():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("pierwsze liczenie pada")
        return "ok"

    with pytest.raises(RuntimeError):
        await _get_or_compute("sf:fail", compute)
    assert await cache_get("sf:fail") is None
    assert "sf:fail" not in cache_mod._inflight
    # Następne żądanie liczy samo — nic nie wisi na padniętym wykonawcy.
    assert await _get_or_compute("sf:fail", compute) == "ok"
    assert attempts == 2


@pytest.mark.asyncio
async def test_different_keys_do_not_serialize_each_other():
    await cache_invalidate("sf:")
    started: list[str] = []
    release = asyncio.Event()

    def make(key: str):
        async def compute():
            started.append(key)
            await release.wait()
            return key

        return compute

    task_a = asyncio.create_task(_get_or_compute("sf:a", make("a")))
    task_b = asyncio.create_task(_get_or_compute("sf:b", make("b")))
    await asyncio.sleep(0.02)
    # Oba liczenia ruszyły równolegle — „a" nie blokuje „b".
    assert sorted(started) == ["a", "b"]
    release.set()
    assert await asyncio.gather(task_a, task_b) == ["a", "b"]


@pytest.mark.asyncio
async def test_cache_set_jitter_extends_ttl_within_bounds(monkeypatch):
    await cache_invalidate("sf:")
    monkeypatch.setattr(cache_mod.random, "uniform", lambda a, b: b)
    base = cache_mod.time.monotonic()
    await cache_set("sf:jitter", 1, ttl_seconds=10, jitter_seconds=5)
    _value, expires_at = cache_mod._cache["sf:jitter"]
    assert 14.9 <= expires_at - base <= 15.2


@pytest.mark.asyncio
async def test_cache_set_sweeps_expired_keys_nobody_reads_again(monkeypatch) -> None:
    # Do 18.11.2026 wygasły klucz znikał tylko przy odczycie tego samego klucza.
    now = [1000.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(cache_mod, "_cache", {})
    monkeypatch.setattr(cache_mod, "_next_sweep_at", 0.0)
    await cache_set("old:user:1", "a", ttl_seconds=10)
    await cache_set("live:user:2", "b", ttl_seconds=600)
    now[0] += 61  # stary wygasł, minęła minuta od sprzątania
    await cache_set("new:user:3", "c", ttl_seconds=10)
    assert set(cache_mod._cache) == {"live:user:2", "new:user:3"}
    assert cache_mod.entry_count() == 2


@pytest.mark.asyncio
async def test_cache_sweep_runs_at_most_once_a_minute(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(cache_mod, "_cache", {})
    monkeypatch.setattr(cache_mod, "_next_sweep_at", 0.0)
    await cache_set("first", 1, ttl_seconds=60)  # sprzątanie teraz, następne za 60 s
    await cache_set("short", 1, ttl_seconds=1)
    now[0] += 5
    await cache_set("other", 2, ttl_seconds=60)
    # „short” wygasł, ale do następnego sprzątania zostaje; odczyt i tak go nie odda.
    assert "short" in cache_mod._cache
    assert await cache_get("short") is None
    assert "short" not in cache_mod._cache
