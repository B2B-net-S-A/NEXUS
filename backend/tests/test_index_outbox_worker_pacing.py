import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks import index_outbox_worker as worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "busy_interval", "expected"),
    [
        ({"done": 50}, 1, 1),
        ({"done": 50}, 30, 30),
        ({"done": 50}, 0, 1),
        ({"done": 49}, 1, 30),
        ({}, 1, 30),
        ({"done": 49, "failed": 1}, 1, 30),
        ({"done": 49, "dead": 1}, 1, 30),
        (RuntimeError("temporary database failure"), 1, 30),
    ],
)
async def test_only_full_successful_batches_skip_idle_pause(
    monkeypatch, result, busy_interval, expected
):
    monkeypatch.setattr(worker.outbox, "worker_enabled", lambda: True)
    monkeypatch.setattr(worker.settings, "AI_INDEX_WORKER_BATCH", 50)
    monkeypatch.setattr(worker.settings, "AI_INDEX_WORKER_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(
        worker.settings, "AI_INDEX_WORKER_BUSY_INTERVAL_SECONDS", busy_interval
    )
    session = AsyncMock()
    monkeypatch.setattr(worker, "AsyncSessionLocal", MagicMock(return_value=session))
    drain = AsyncMock(side_effect=[result])
    monkeypatch.setattr(worker.outbox, "drain_once", drain)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.index_outbox_loop()
    drain.assert_awaited_once_with(session.__aenter__.return_value, batch=50)
    session.__aexit__.assert_awaited_once()
    sleep.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_worker_cancellation_propagates_without_another_poll(monkeypatch):
    monkeypatch.setattr(worker.outbox, "worker_enabled", lambda: True)
    monkeypatch.setattr(
        worker, "AsyncSessionLocal", MagicMock(return_value=AsyncMock())
    )
    drain = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker.outbox, "drain_once", drain)
    sleep = AsyncMock()
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.index_outbox_loop()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_after_success_restores_normal_pause(monkeypatch):
    monkeypatch.setattr(worker.outbox, "worker_enabled", lambda: True)
    monkeypatch.setattr(worker.settings, "AI_INDEX_WORKER_BATCH", 50)
    monkeypatch.setattr(worker.settings, "AI_INDEX_WORKER_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(worker.settings, "AI_INDEX_WORKER_BUSY_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(
        worker, "AsyncSessionLocal", MagicMock(return_value=AsyncMock())
    )
    monkeypatch.setattr(
        worker.outbox,
        "drain_once",
        AsyncMock(side_effect=[{"done": 50}, {"done": 49, "failed": 1}]),
    )
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await worker.index_outbox_loop()
    assert [call.args for call in sleep.await_args_list] == [(1,), (30,)]
