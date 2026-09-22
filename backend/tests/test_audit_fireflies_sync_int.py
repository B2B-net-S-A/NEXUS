"""INT-11/12/13 (audyt 22.09.2026): paginacja, DateTime, watermark tylko przy 0 błędów."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.note import Note
from app.services import fireflies_job_matcher
from app.services import fireflies_sync as ff


@pytest.fixture
def fresh_state(monkeypatch):
    monkeypatch.setattr(ff, "FIREFLIES_API_KEY", "test-key")
    monkeypatch.setattr(
        ff,
        "_last_sync_state",
        {
            "last_synced_at": None,
            "last_attempt_at": None,
            "last_success_at": None,
            "transcript_count": 0,
            "error": None,
        },
    )

    async def _no_jobs(*_a, **_k):
        return []

    monkeypatch.setattr(fireflies_job_matcher, "match_meeting_to_jobs", _no_jobs)


def _pager(total: int, prefix: str, calls: list):
    items = [
        {"id": f"{prefix}-{i}", "title": f"Spotkanie {i}", "participants": []}
        for i in range(total)
    ]

    async def _fetch_page(query, variables):
        calls.append(dict(variables))
        skip, limit = variables["skip"], variables["limit"]
        return {"data": {"transcripts": items[skip : skip + limit]}}

    return _fetch_page


async def _cleanup(prefix: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Note).where(Note.source_ref.like(f"fireflies:{prefix}-%"))
        )
        await db.commit()


async def test_125_transcripts_over_three_pages(monkeypatch, fresh_state):
    prefix = f"pg{uuid.uuid4().hex[:8]}"
    calls: list = []
    monkeypatch.setattr(ff, "_fetch_page", _pager(125, prefix, calls))
    try:
        async with AsyncSessionLocal() as db:
            result = await ff.sync_fireflies_transcripts(db)
        assert result["errors"] == 0
        assert result["synced"] == 125
        assert [c["skip"] for c in calls] == [0, 50, 100]
        assert all(c["limit"] == 50 for c in calls)
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count(Note.id)).where(
                    Note.source_ref.like(f"fireflies:{prefix}-%")
                )
            )
        assert count == 125
    finally:
        await _cleanup(prefix)


async def test_from_date_is_full_iso_datetime(monkeypatch, fresh_state):
    calls: list = []
    monkeypatch.setattr(ff, "_fetch_page", _pager(0, "none", calls))
    since = datetime(2026, 9, 21, 14, 30, 5, 123000, tzinfo=timezone.utc)
    await ff._fetch_transcripts(since=since)
    assert calls[0]["fromDate"] == "2026-09-21T14:30:05.123Z"
    assert "$fromDate: DateTime" in ff.TRANSCRIPTS_QUERY
    assert "skip: $skip" in ff.TRANSCRIPTS_QUERY


async def test_watermark_holds_on_error_and_advances_after_clean_run(
    monkeypatch, fresh_state
):
    prefix = f"wm{uuid.uuid4().hex[:8]}"
    calls: list = []
    monkeypatch.setattr(ff, "_fetch_page", _pager(3, prefix, calls))
    original = ff._find_candidate_by_emails
    state = {"fail": True}

    async def _flaky(db, participants):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("boom")
        return await original(db, participants)

    monkeypatch.setattr(ff, "_find_candidate_by_emails", _flaky)
    try:
        async with AsyncSessionLocal() as db:
            first = await ff.sync_fireflies_transcripts(db)
        assert first["errors"] == 1
        status = ff.get_sync_status()
        assert status["last_synced_at"] is None, "no advance with errors"
        assert status["last_success_at"] is None
        assert status["last_attempt_at"] is not None
        assert status["error"]

        async with AsyncSessionLocal() as db:
            second = await ff.sync_fireflies_transcripts(db)
        assert second["errors"] == 0
        assert second["synced"] == 1  # the one that failed before
        status = ff.get_sync_status()
        assert status["last_synced_at"] is not None
        assert status["last_success_at"] is not None
        assert status["error"] is None
    finally:
        await _cleanup(prefix)
