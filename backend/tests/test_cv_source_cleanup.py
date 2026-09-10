"""Storage failures must retain durable deletion intent, never delete live input."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import cv_source_cleanup as cleanup


@pytest.mark.parametrize(
    "referenced,storage_fails", [(True, False), (False, True), (False, False)]
)
async def test_cleanup_preserves_live_sources_and_retries_failures(
    monkeypatch, referenced, storage_fails
):
    intent = SimpleNamespace(
        storage_key="synthetic-source",
        attempts=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    before = intent.next_attempt_at
    db = AsyncMock()
    db.scalars.return_value = Mock(all=Mock(return_value=[intent]))
    db.scalar.return_value = 42 if referenced else None
    storage = AsyncMock(
        side_effect=OSError("synthetic failure") if storage_fails else None
    )
    monkeypatch.setattr(cleanup, "run_in_threadpool", storage)
    await cleanup.clean_pending_sources(db)
    if referenced:
        storage.assert_not_awaited()
        db.delete.assert_not_awaited()
        assert intent.attempts == 0
        assert intent.next_attempt_at > before
    elif storage_fails:
        db.delete.assert_not_awaited()
        assert intent.attempts == 1
        assert intent.next_attempt_at > before
    else:
        db.delete.assert_awaited_once_with(intent)
    db.commit.assert_awaited_once()


async def test_scheduling_never_commits_or_deletes_storage(monkeypatch):
    db = AsyncMock()
    storage = Mock()
    monkeypatch.setattr(cleanup.object_storage, "delete_cv", storage)
    await cleanup.schedule_source_cleanup(db, "synthetic-source")
    assert "ON CONFLICT" in str(db.execute.call_args.args[0])
    db.commit.assert_not_awaited()
    storage.assert_not_called()
