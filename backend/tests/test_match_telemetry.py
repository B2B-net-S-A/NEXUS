"""Tests for append-only matching telemetry (plan PR2).

Exercises the flag gate, append-only idempotency, and PII pseudonymisation.
DB-backed (CI provisions Postgres + runs the 0169 migration).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import match_telemetry_service as tel
from app.services.match_telemetry_service import ImpressionEntry


def _run_id() -> str:
    return f"test-{uuid.uuid4().hex[:16]}"


async def _cleanup(run_id: str, event_id: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM match_impressions WHERE run_id = :r"), {"r": run_id}
        )
        if event_id:
            await db.execute(
                text("DELETE FROM match_outcomes WHERE event_id = :e"), {"e": event_id}
            )
        await db.commit()


def test_pseudonymize_is_deterministic_and_not_raw():
    assert tel.pseudonymize(None) is None
    a = tel.pseudonymize(42)
    b = tel.pseudonymize(42)
    assert a == b
    assert a != "42"
    assert len(a) == 32
    assert tel.pseudonymize(42) != tel.pseudonymize(43)


@pytest.mark.asyncio
async def test_flag_off_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", False)
    run_id = _run_id()
    async with AsyncSessionLocal() as db:
        n = await tel.record_impressions(
            db,
            run_id=run_id,
            surface="test",
            entries=[ImpressionEntry(candidate_id=1, rank=0)],
        )
    assert n == 0
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            text("SELECT count(*) FROM match_impressions WHERE run_id = :r"),
            {"r": run_id},
        )
    assert count == 0


@pytest.mark.asyncio
async def test_impressions_append_and_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run_id = _run_id()
    entries = [
        ImpressionEntry(
            candidate_id=101,
            rank=0,
            eligible=True,
            fit_score=87.5,
            fit_breakdown={"semantic": 30, "skills": 25},
            retrieval_sources={"dense": 0.9},
        ),
        ImpressionEntry(candidate_id=102, rank=1, eligible=False, fit_score=40.0),
    ]
    try:
        async with AsyncSessionLocal() as db:
            n1 = await tel.record_impressions(
                db,
                run_id=run_id,
                surface="recommendations",
                entries=entries,
                job_id=555,
                user_id=7,
                client_id=9,
            )
        assert n1 == 2

        # Re-recording the same (run_id, candidate) pair is a no-op.
        async with AsyncSessionLocal() as db:
            n2 = await tel.record_impressions(
                db,
                run_id=run_id,
                surface="recommendations",
                entries=entries,
            )
        assert n2 == 0

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT candidate_id, rank, eligible, fit_score, user_ref, "
                        "ranker_version FROM match_impressions "
                        "WHERE run_id = :r ORDER BY rank"
                    ),
                    {"r": run_id},
                )
            ).all()
        assert len(rows) == 2
        assert rows[0].candidate_id == 101
        assert rows[0].eligible is True
        assert rows[1].eligible is False
        # user id is pseudonymised, never stored raw.
        assert rows[0].user_ref == tel.pseudonymize(7)
        assert rows[0].user_ref != "7"
        assert rows[0].ranker_version == "scoring-v1-legacy"
    finally:
        await _cleanup(run_id)


@pytest.mark.asyncio
async def test_outcome_idempotent_by_event_id(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run_id = _run_id()
    event_id = f"evt-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            first = await tel.record_outcome(
                db,
                event_id=event_id,
                event_type="shortlist",
                run_id=run_id,
                candidate_id=101,
            )
        assert first is True
        # Same event_id again → not recorded twice.
        async with AsyncSessionLocal() as db:
            second = await tel.record_outcome(
                db,
                event_id=event_id,
                event_type="shortlist",
                run_id=run_id,
                candidate_id=101,
            )
        assert second is False

        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                text("SELECT count(*) FROM match_outcomes WHERE event_id = :e"),
                {"e": event_id},
            )
        assert count == 1
    finally:
        await _cleanup(run_id, event_id)


@pytest.mark.asyncio
async def test_unknown_outcome_event_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    async with AsyncSessionLocal() as db:
        ok = await tel.record_outcome(
            db,
            event_id=f"evt-{uuid.uuid4().hex}",
            event_type="not_a_real_event",
        )
    assert ok is False
