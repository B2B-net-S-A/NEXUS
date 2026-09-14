"""The monitor counts committed rows, never attempts or rolled-back inserts."""

from uuid import uuid4
from unittest.mock import AsyncMock
import logging

import pytest
from sqlalchemy import text

from app.core.database import engine
from app.tasks import notification_volume_monitor as monitor


@pytest.mark.asyncio
async def test_counts_committed_window_and_excludes_rollback():
    # Isolated synthetic schema: no dependency on other tests' notifications.
    schema = "monitor_test_" + uuid4().hex
    async with engine.connect() as writer, engine.connect() as reader:
        await writer.execute(text(f'CREATE SCHEMA "{schema}"'))
        await writer.execute(text(f'SET search_path TO "{schema}"'))
        await writer.execute(
            text("CREATE TABLE notifications (created_at timestamptz)")
        )
        await writer.commit()
        await reader.execute(text(f'SET search_path TO "{schema}"'))
        try:
            await writer.execute(
                text("INSERT INTO notifications VALUES (now() - interval '1 minute')")
            )
            assert await monitor.read_notification_volume(reader) == 0
            await writer.commit()
            assert await monitor.read_notification_volume(reader) == 1
            await writer.execute(
                text("INSERT INTO notifications VALUES (now() - interval '1 minute')")
            )
            await writer.rollback()
            await writer.execute(
                text(
                    "INSERT INTO notifications VALUES (now() - interval '6 minutes'), (now() + interval '1 minute')"
                )
            )
            await writer.commit()
            assert await monitor.read_notification_volume(reader) == 1
        finally:
            await reader.rollback()
            await reader.execute(text("RESET search_path"))
            await reader.commit()
            await writer.rollback()
            await writer.execute(text("RESET search_path"))
            await writer.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await writer.commit()


@pytest.mark.asyncio
async def test_read_failure_is_not_zero_and_next_sample_recovers(monkeypatch, caplog):
    session = AsyncMock()
    monkeypatch.setattr(monitor, "AsyncSessionLocal", lambda: session)
    read = AsyncMock(side_effect=[TimeoutError("synthetic-private-content"), 0])
    monkeypatch.setattr(monitor, "read_notification_volume", read)
    with caplog.at_level(logging.INFO, logger=monitor.__name__):
        await monitor.sample_notification_volume()
        await monitor.sample_notification_volume()
    events = [
        r
        for r in caplog.records
        if getattr(r, "event_kind", None) == "notification_volume"
    ]
    assert [e.monitor_status for e in events] == ["error", "ok"]
    assert not hasattr(events[0], "persisted_rows")
    assert events[1].persisted_rows == 0
    assert "synthetic-private-content" not in caplog.text
