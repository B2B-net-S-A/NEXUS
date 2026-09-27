"""Runda 9 (R9-X1-7): awaria digestu jednej rekrutacji nie psuje pozostałych.

Dawny ``db.rollback()`` całej sesji w pętli cofał niezatwierdzone digesty
poprzednich rekrutacji i wygaszał obiekty ``Job`` — następna iteracja padała
na leniwym odczycie ``job.title`` (``MissingGreenlet`` w async).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import auto_match_service as ams


class _Savepoint:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> "_Savepoint":
        self.log.append("savepoint")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.log.append("savepoint_rollback" if exc_type else "savepoint_release")
        return False


class _Db:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.scalar = AsyncMock(return_value=1)
        self.commit = AsyncMock()

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self.log)

    async def rollback(self) -> None:
        self.log.append("SESSION_ROLLBACK")


@pytest.mark.asyncio
async def test_failed_digest_rolls_back_only_its_own_savepoint(monkeypatch) -> None:
    from app.services import notification_triggers

    calls: list[int] = []

    async def fake_emit(db, *, user_id, related_entity_id, **kwargs):
        calls.append(related_entity_id)
        if related_entity_id == 1:
            raise RuntimeError("zapis padł")
        return object()

    monkeypatch.setattr(notification_triggers, "emit", fake_emit)
    db = _Db()
    jobs = {
        1: SimpleNamespace(title="A", recruiter_id=10, tac_id=None),
        2: SimpleNamespace(title="B", recruiter_id=11, tac_id=None),
    }

    sent = await ams._notify_proposals(db, proposed={1: 1, 2: 1}, jobs_by_id=jobs)

    assert calls == [1, 2]
    assert sent == 1
    assert "SESSION_ROLLBACK" not in db.log
    assert db.log == [
        "savepoint",
        "savepoint_rollback",
        "savepoint",
        "savepoint_release",
    ]
    db.commit.assert_awaited_once()
