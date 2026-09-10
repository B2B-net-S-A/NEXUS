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


# ── Full search (C2 / Radar) impressions + pipeline outcomes ────────────────


def test_numeric_breakdown_keeps_numbers_and_drops_free_text():
    """Reasons quote locations, rates and skills verbatim; they never reach the
    analytics table. A redacted salary stays redacted (None), not recomputed."""
    served = {
        "total": 71.2,
        "semantic": {"points": 40.1, "max": 66.7, "reason": "sim 0.61"},
        "salary": {"points": None, "max": None, "reason": None, "status": "redacted"},
        "location": {"points": 5, "max": 5.6, "reason": "Warszawa, ul. Prosta 1"},
        "matching_must": ["python"],
        "seniority_note": "3 lata",
    }
    out = tel.numeric_fit_breakdown(served, total=71.2, measurement="measured")
    assert out == {
        "semantic": {"points": 40.1, "max": 66.7},
        "salary": {"points": None, "max": None},
        "location": {"points": 5.0, "max": 5.6},
        "total": 71.2,
        "measurement": "measured",
    }
    assert "Warszawa" not in str(out) and "python" not in str(out)
    assert tel.numeric_fit_breakdown(None, total=None) == {"total": None}
    # A non-finite number would make the whole page's JSONB insert fail.
    odd = {"skills": {"points": float("nan"), "max": True}}
    assert tel.numeric_fit_breakdown(odd, total=float("inf")) == {
        "skills": {"points": None, "max": None},
        "total": None,
    }


async def _cleanup_job(job_id: int, run_ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        for run_id in run_ids:
            await db.execute(
                text("DELETE FROM match_impressions WHERE run_id = :r"), {"r": run_id}
            )
        await db.execute(
            text("DELETE FROM match_outcomes WHERE job_id = :j"), {"j": job_id}
        )
        await db.commit()


def _job_id() -> int:
    # No FK on the telemetry tables; a random high id never collides with seeds.
    return 900_000_000 + uuid.uuid4().int % 90_000_000


@pytest.mark.asyncio
async def test_full_search_page_stamps_the_run_and_its_surface(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    monkeypatch.setattr(tel, "MAX_ROWS_PER_CALL", 2)
    job_id = _job_id()
    saved, radar = _run_id(), _run_id()
    trace = {"ranker_version": "r" * 80, "text_schema_version": "text-v2"}
    try:
        n = await tel.record_full_search_page(
            None,
            run_id=saved,
            job_id=job_id,
            client_id=9,
            user_id=7,
            version_trace=trace,
            entries=[
                ImpressionEntry(candidate_id=c, rank=i) for i, c in enumerate([5, 6, 7])
            ],
            degraded=True,
        )
        assert n == 2, "capped at MAX_ROWS_PER_CALL — only served rows, bounded"
        await tel.record_full_search_page(
            None,
            run_id=radar,
            job_id=None,
            client_id=9,
            user_id=7,
            version_trace=None,
            entries=[ImpressionEntry(candidate_id=5, rank=0)],
            degraded=False,
        )
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT run_id, surface, ranker_version, text_schema_version,"
                        " index_version, degraded FROM match_impressions"
                        " WHERE run_id IN (:a, :b) ORDER BY run_id, rank"
                    ),
                    {"a": saved, "b": radar},
                )
            ).all()
        by_run = {}
        for row in rows:
            by_run.setdefault(row.run_id, []).append(row)
        assert [r.surface for r in by_run[saved]] == ["full_search", "full_search"]
        assert by_run[saved][0].ranker_version == "r" * 64
        assert by_run[saved][0].text_schema_version == "text-v2"
        assert by_run[saved][0].index_version == "index-legacy-v1"
        assert by_run[saved][0].degraded is True
        assert [r.surface for r in by_run[radar]] == ["talent_radar"]
    finally:
        await _cleanup_job(job_id, [saved, radar])


@pytest.mark.asyncio
async def test_pipeline_addition_joins_the_run_this_user_was_shown(monkeypatch):
    """The outcome carries the run of the LAST impression this user saw for the
    candidate in this job — so it joins its page, rank and fit. Another user's
    impression is not this user's exposure. Without any impression the outcome
    still lands, on the fallback correlation."""
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    job_id = _job_id()
    old, newest, other_user = _run_id(), _run_id(), _run_id()

    async def shown(run_id: str, user_id: int, candidate_ids: list[int]) -> None:
        await tel.record_full_search_page(
            None,
            run_id=run_id,
            job_id=job_id,
            client_id=1,
            user_id=user_id,
            version_trace=None,
            entries=[
                ImpressionEntry(candidate_id=c, rank=i)
                for i, c in enumerate(candidate_ids)
            ],
            degraded=False,
        )

    try:
        await shown(old, 7, [101, 102])
        await shown(newest, 7, [101])
        await shown(other_user, 8, [102])

        runs = await tel.latest_impression_runs(
            job_id=job_id, candidate_ids=[101, 102, 103], user_id=7
        )
        assert runs == {101: newest, 102: old}

        n = await tel.emit_pipeline_additions(
            job_id=job_id, candidate_ids=[101, 103, 101], user_id=7
        )
        assert n == 2
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT candidate_id, run_id, event_type, event_id"
                        " FROM match_outcomes WHERE job_id = :j ORDER BY candidate_id"
                    ),
                    {"j": job_id},
                )
            ).all()
        assert [(r.candidate_id, r.run_id, r.event_type) for r in rows] == [
            (101, newest, "add_to_pipeline"),
            (103, None, "add_to_pipeline"),
        ]
        assert rows[1].event_id == f"add_to_pipeline:norun:{job_id}:103"

        # A retried request (double click, proxy retry) records nothing new.
        assert (
            await tel.emit_pipeline_additions(
                job_id=job_id, candidate_ids=[101, 103], user_id=7
            )
            == 0
        )
    finally:
        await _cleanup_job(job_id, [old, newest, other_user])


@pytest.mark.asyncio
async def test_pipeline_additions_are_a_noop_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", False)
    job_id = _job_id()
    assert (
        await tel.emit_pipeline_additions(job_id=job_id, candidate_ids=[1], user_id=7)
        == 0
    )
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            text("SELECT count(*) FROM match_outcomes WHERE job_id = :j"),
            {"j": job_id},
        )
    assert count == 0
