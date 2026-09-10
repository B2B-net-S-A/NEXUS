from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import cv_preview_retention as service


@pytest.mark.parametrize(
    "state",
    ["complete", "failed", "interrupted", "queued", "running", "locked", "legacy"],
)
async def test_retention_preserves_active_jobs_and_schedules_owned_source(
    monkeypatch, state
):
    preview = SimpleNamespace(id=7)
    db = AsyncMock()
    db.scalars.return_value = Mock(all=Mock(return_value=[preview]))
    if state in {"locked", "legacy"}:
        db.scalar.side_effect = [None, 12 if state == "locked" else None]
    else:
        db.scalar.return_value = SimpleNamespace(
            status=state, input_storage_key="private-source"
        )
    schedule = AsyncMock()
    monkeypatch.setattr(service, "schedule_source_cleanup", schedule)
    await service.retire_previews(db, 3, datetime.now(timezone.utc))
    if state in {"queued", "running", "locked"}:
        db.delete.assert_not_awaited()
        schedule.assert_not_awaited()
    else:
        db.delete.assert_awaited_once_with(preview)
        if state == "legacy":
            schedule.assert_not_awaited()
        else:
            schedule.assert_awaited_once_with(db, "private-source")
    db.commit.assert_not_awaited()
