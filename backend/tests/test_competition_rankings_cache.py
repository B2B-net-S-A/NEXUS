"""Rankingi konkursów liczą się raz na minutę dla wszystkich oglądających.

Test obciążeniowy 24.09.2026: `/api/competitions/monthly-races` ~6 s
i `/api/competitions/current` ~3 s przy każdym wejściu na Insights. Wynik nie
zależy od osoby, więc jedno przeliczenie wystarcza wszystkim, a zamrożenie
okresu i rozstrzygnięcie remisu muszą zdjąć stary wynik od razu.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.api import competitions as competitions_api
from app.core.cache import cache_invalidate

VIEWER = SimpleNamespace()


@pytest.fixture
async def cached_rankings(monkeypatch):
    monkeypatch.setattr(competitions_api, "_CACHE_TTL_SECONDS", 60)
    await cache_invalidate(competitions_api._CACHE_PREFIX)
    yield
    await cache_invalidate(competitions_api._CACHE_PREFIX)


@pytest.fixture
def race_calls(monkeypatch):
    calls = []

    async def compose(db, period):
        calls.append(period)
        await asyncio.sleep(0.01)
        return {"period": period, "n": len(calls)}

    monkeypatch.setattr(
        competitions_api.comp_service, "compose_monthly_races", compose
    )
    return calls


async def test_parallel_viewers_share_one_computation(cached_rankings, race_calls):
    viewers = [
        competitions_api.monthly_races(VIEWER, None, None) for _ in range(10)
    ]
    results = await asyncio.gather(*viewers)

    assert race_calls == [None]
    assert all(r == {"period": None, "n": 1} for r in results)


async def test_freeze_drops_the_cached_ranking(
    cached_rankings, race_calls, monkeypatch
):
    async def frozen(db, ctype, period):
        return SimpleNamespace(
            saved_count=3, already_frozen=False, closure_status="frozen"
        )

    monkeypatch.setattr(competitions_api.comp_service, "freeze_competition", frozen)

    await competitions_api.monthly_races(VIEWER, None, None)
    await competitions_api.freeze(VIEWER, None, "monthly_placements", "2026-08")
    after = await competitions_api.monthly_races(VIEWER, None, None)

    assert after == {"period": None, "n": 2}
    assert len(race_calls) == 2


async def test_disabled_ttl_recomputes_every_time(race_calls):
    # Tak działa autouse z conftest: ujemny TTL = brak cache'u w testach.
    await competitions_api.monthly_races(VIEWER, None, None)
    await competitions_api.monthly_races(VIEWER, None, None)

    assert len(race_calls) == 2
