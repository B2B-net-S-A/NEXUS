from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import traffit_status
from app.services import dashboard_v2_sources


@pytest.mark.asyncio
async def test_shared_status_preserves_quarantine_and_cursor(monkeypatch):
    monkeypatch.setattr(traffit_status, "sync_is_running", lambda: False)
    row = SimpleNamespace(
        phase="candidates",
        last_synced_at=None,
        last_run_started_at=None,
        last_run_finished_at=None,
        last_status="partial",
        cursor_at=None,
        cursor_payload={"page": 2},
        stats={"quarantined": ["ref-1"], "quarantine": {"ref-1": 3}},
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=[row]))
    result = await traffit_status.read_traffit_status(db)
    assert result["states"][0]["cursor"] == {"page": 2}
    assert result["quarantined"][0]["attempts"] == 3
    assert result["running"] is False


@pytest.mark.asyncio
async def test_dashboard_calls_service_without_decorated_http_endpoint(monkeypatch):
    read = AsyncMock(return_value={"states": [], "running": False})
    monkeypatch.setattr(dashboard_v2_sources, "read_traffit_status", read)
    db = object()
    assert await dashboard_v2_sources.load_traffit_status(object(), db) == {
        "states": [],
        "running": False,
    }
    read.assert_awaited_once_with(db)
