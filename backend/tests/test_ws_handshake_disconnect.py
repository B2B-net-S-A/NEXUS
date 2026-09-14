from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from uvicorn.protocols.utils import ClientDisconnected
from app.api import ws


@pytest.mark.asyncio
async def test_disconnect_during_accept_is_cleaned_up(monkeypatch):
    socket = object()
    monkeypatch.setattr(ws, "_extract_ws_token", lambda *args: ("synthetic", None))
    monkeypatch.setattr(
        ws, "_authenticate_ws_token", AsyncMock(return_value=SimpleNamespace(id=1))
    )
    manager = SimpleNamespace(
        connect=AsyncMock(side_effect=ClientDisconnected()), disconnect=AsyncMock()
    )
    monkeypatch.setattr(ws, "manager", manager)
    await ws.ws_notifications(socket, token=None)
    manager.disconnect.assert_awaited_once_with(1, socket)
