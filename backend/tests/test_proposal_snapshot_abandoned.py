"""R10-N7-8: migawka rekomendacji nie może zostać `pending` na zawsze.

Dwie drogi do wiecznego `pending`: deploy w trakcie liczenia (zadanie w tle
tego samego procesu ginie) i błąd bazy, po którym `commit` w gałęzi `except`
rzucał, bo sesja wymagała rollbacku. Front odpytywał taką migawkę co 3 s.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.proposal_snapshot import STATUS_FAILED, STATUS_PENDING, STATUS_READY
from app.tasks import compute_proposals as cp


def test_old_pending_reads_as_failed_and_fresh_pending_stays():
    now = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=2)
    abandoned = now - timedelta(hours=1)
    assert cp.effective_snapshot_status(STATUS_PENDING, fresh, now=now) == (
        STATUS_PENDING,
        None,
    )
    status, message = cp.effective_snapshot_status(STATUS_PENDING, abandoned, now=now)
    assert status == STATUS_FAILED
    assert message and "przerwane" in message
    # Gotowa migawka nie zmienia statusu, niezależnie od wieku.
    assert cp.effective_snapshot_status(STATUS_READY, abandoned, now=now) == (
        STATUS_READY,
        None,
    )


class _BrokenSession:
    """Po błędzie zapytania sesja wymaga rollbacku — jak prawdziwe asyncpg."""

    def __init__(self, snap):
        self.snap = snap
        self.calls = 0
        self.needs_rollback = False
        self.rolled_back = False
        self.executed = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalar(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return self.snap
        self.needs_rollback = True
        raise RuntimeError("connection dropped")

    async def execute(self, stmt):
        if self.needs_rollback:
            raise RuntimeError("PendingRollbackError")
        self.executed.append(stmt)

    async def commit(self):
        if self.needs_rollback:
            raise RuntimeError("PendingRollbackError")
        self.committed = True

    async def rollback(self):
        self.needs_rollback = False
        self.rolled_back = True


@pytest.mark.asyncio
async def test_db_error_marks_the_snapshot_failed_after_a_rollback(monkeypatch):
    snap = SimpleNamespace(id=5, status=STATUS_PENDING, error_message=None)
    session = _BrokenSession(snap)
    monkeypatch.setattr(cp, "AsyncSessionLocal", lambda: session)

    await cp.compute_proposal_for_job(5, 9)

    assert session.rolled_back
    assert session.committed, "porażka musi zostać zapisana"
    assert len(session.executed) == 1
    compiled = session.executed[0].compile()
    assert "UPDATE proposal_snapshots" in str(compiled)
    assert compiled.params["status"] == STATUS_FAILED
