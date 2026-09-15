"""`marketplace_sweeper_loop` — kill-switch, one pass and survival of a crash.

The services themselves have their own suites; here only the loop contract is
pinned: a disabled marketplace does no work at all, a pass reconciles the
membership and rescans recent jobs (committing after each), and an exception
from either service is logged instead of ending the task.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.marketplace_service import SyncCounters
from app.tasks import marketplace_sweeper as sweeper


def _session(monkeypatch) -> AsyncMock:
    session = AsyncMock()
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(sweeper, "AsyncSessionLocal", factory)
    return session


async def test_disabled_marketplace_exits_without_work(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_ENABLED", False)

    async def _forbidden(*_a, **_kw):
        raise AssertionError("a disabled sweeper must not wait or sweep")

    monkeypatch.setattr(sweeper.asyncio, "sleep", _forbidden)
    monkeypatch.setattr(sweeper, "auto_sync_marketplace_membership", _forbidden)
    monkeypatch.setattr(sweeper, "rescan_recent_jobs", _forbidden)

    assert await sweeper.marketplace_sweeper_loop() is None


async def test_one_pass_syncs_membership_and_rescans(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_ENABLED", True)
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_SWEEP_INTERVAL_SECONDS", 900)
    session = _session(monkeypatch)
    sync = AsyncMock(return_value=SyncCounters(added=2))
    rescan = AsyncMock(return_value=3)
    monkeypatch.setattr(sweeper, "auto_sync_marketplace_membership", sync)
    monkeypatch.setattr(sweeper, "rescan_recent_jobs", rescan)
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.marketplace_sweeper_loop()

    db = session.__aenter__.return_value
    sync.assert_awaited_once_with(db)
    rescan.assert_awaited_once_with(db, lookback=timedelta(hours=2))
    assert db.commit.await_count == 2, "commit after sync and after rescan"
    assert [c.args for c in sleep.await_args_list] == [(90,), (900,)]


async def test_interval_is_clamped_to_five_minutes(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_ENABLED", True)
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_SWEEP_INTERVAL_SECONDS", 5)
    _session(monkeypatch)
    monkeypatch.setattr(
        sweeper,
        "auto_sync_marketplace_membership",
        AsyncMock(return_value=SyncCounters()),
    )
    monkeypatch.setattr(sweeper, "rescan_recent_jobs", AsyncMock(return_value=0))
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.marketplace_sweeper_loop()

    assert sleep.await_args_list[-1].args == (300,)


async def test_service_exception_does_not_kill_the_loop(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_ENABLED", True)
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_SWEEP_INTERVAL_SECONDS", 600)
    _session(monkeypatch)
    sync = AsyncMock(side_effect=[RuntimeError("boom"), SyncCounters()])
    rescan = AsyncMock(return_value=0)
    monkeypatch.setattr(sweeper, "auto_sync_marketplace_membership", sync)
    monkeypatch.setattr(sweeper, "rescan_recent_jobs", rescan)
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.marketplace_sweeper_loop()

    assert sync.await_count == 2, "the pass after a crash still runs"
    assert rescan.await_count == 1, "a crashed sync skips that pass's rescan"
    assert [c.args for c in sleep.await_args_list] == [(90,), (600,), (600,)]


async def test_rescan_exception_does_not_kill_the_loop(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_ENABLED", True)
    monkeypatch.setattr(sweeper.settings, "MARKETPLACE_SWEEP_INTERVAL_SECONDS", 600)
    _session(monkeypatch)
    monkeypatch.setattr(
        sweeper,
        "auto_sync_marketplace_membership",
        AsyncMock(return_value=SyncCounters()),
    )
    rescan = AsyncMock(side_effect=RuntimeError("qdrant down"))
    monkeypatch.setattr(sweeper, "rescan_recent_jobs", rescan)
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.marketplace_sweeper_loop()

    assert rescan.await_count == 2
