"""The worker starts for the draft flag without enabling the legacy sender."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import settings
from app.tasks import cpro_bot


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_enabled", [False, True])
async def test_worker_respects_draft_flag_with_legacy_sender_disabled(
    monkeypatch, draft_enabled
):
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", draft_enabled)
    monkeypatch.setattr(cpro_bot.runs, "configured", lambda: True)

    @asynccontextmanager
    async def session():
        yield object()

    tick = AsyncMock(return_value=None)
    expire = AsyncMock(return_value=0)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(cpro_bot, "AsyncSessionLocal", session)
    monkeypatch.setattr(cpro_bot.flow, "start_due", tick)
    monkeypatch.setattr(cpro_bot.runs, "expire_runs", expire)
    monkeypatch.setattr(cpro_bot.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        cpro_bot.loop_heartbeat,
        "register",
        Mock(return_value=SimpleNamespace(tick=Mock())),
    )
    if draft_enabled:
        with pytest.raises(asyncio.CancelledError):
            await cpro_bot.cpro_bot_loop()
        tick.assert_awaited_once()
        expire.assert_awaited_once()
        sleep.assert_awaited_once_with(cpro_bot.TICK_SECONDS)
    else:
        await cpro_bot.cpro_bot_loop()
        tick.assert_not_called()
        expire.assert_not_called()
