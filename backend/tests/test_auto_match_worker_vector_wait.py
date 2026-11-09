"""Zdarzenie CV czekające na wektor nie zużywa prób (08.11.2026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import auto_match_service as ams
from app.tasks import candidate_auto_match as worker


class _Session:
    def __init__(self, event, statements):
        self.event = event
        self.statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, _model, _id):
        return self.event

    async def rollback(self):
        return None

    async def commit(self):
        return None

    async def execute(self, statement):
        self.statements.append(statement.compile().params)


async def test_pending_vector_returns_the_event_without_spending_an_attempt(
    monkeypatch,
):
    event = SimpleNamespace(
        candidate_id=7,
        job_id=None,
        trigger="cv_upload",
        attempts=1,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    statements: list[dict] = []

    async def pending(_db, _event):
        raise ams.AutoMatchVectorPending("wektor")

    monkeypatch.setattr(ams, "run_candidate_event", pending)
    monkeypatch.setattr(
        worker, "AsyncSessionLocal", lambda: _Session(event, statements)
    )

    assert await worker._process(1) == "waiting"

    [params] = statements
    assert params["status"] == "failed"
    assert params["attempts"] == 0
    assert params["last_error"] == "vector_pending"
