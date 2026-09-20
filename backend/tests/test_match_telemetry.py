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


async def _run_world() -> dict:
    """Two users, two jobs of one client, and durable search runs between them
    (`candidate_search_runs` is what a declared run id must resolve to)."""
    from app.models.candidate_search_run import CandidateSearchRun
    from app.models.client import Client
    from app.models.job import Job
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Telemetry runs {tag}")
        me = User(email=f"tel-me-{tag}@example.com", name="Me", role=UserRole.recruiter)
        other = User(
            email=f"tel-other-{tag}@example.com", name="Other", role=UserRole.recruiter
        )
        db.add_all([client, me, other])
        await db.flush()
        job = Job(title=f"Telemetry job {tag}", client_id=client.id)
        other_job = Job(title=f"Telemetry other job {tag}", client_id=client.id)
        db.add_all([job, other_job])
        await db.flush()

        def run(owner, for_job) -> CandidateSearchRun:
            return CandidateSearchRun(
                id=str(uuid.uuid4()),
                created_by=owner.id,
                client_id=client.id,
                job_id=for_job.id,
                state="complete",
                request_fingerprint="f" * 64,
                request_context={},
                version_trace={},
                population_size=0,
                metrics={},
            )

        mine, foreign, elsewhere = run(me, job), run(other, job), run(me, other_job)
        db.add_all([mine, foreign, elsewhere])
        await db.commit()
        return {
            "user_id": me.id,
            "other_user_id": other.id,
            "job_id": job.id,
            "other_job_id": other_job.id,
            "mine": mine.id,
            "foreign": foreign.id,
            "elsewhere": elsewhere.id,
        }


async def _shown(run_id: str, *, job_id: int, user_id: int, candidates: list[int]):
    await tel.record_full_search_page(
        None,
        run_id=run_id,
        job_id=job_id,
        client_id=1,
        user_id=user_id,
        version_trace=None,
        entries=[ImpressionEntry(candidate_id=c, rank=i) for i, c in enumerate(candidates)],
        degraded=False,
    )


async def _outcomes(job_id: int) -> list:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT candidate_id, run_id, event_type, event_id, reason_code"
                    " FROM match_outcomes WHERE job_id = :j ORDER BY candidate_id"
                ),
                {"j": job_id},
            )
        ).all()


@pytest.mark.asyncio
async def test_pipeline_addition_joins_only_the_declared_run_that_showed_it(
    monkeypatch,
):
    """The outcome joins a ranking only through the run the caller declares,
    and only for candidates that run showed THIS user for THIS job. Everything
    else lands with `run_id = NULL` — no attribution is guessed."""
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    w = await _run_world()
    job_id = w["job_id"]
    try:
        await _shown(w["mine"], job_id=job_id, user_id=w["user_id"], candidates=[101])

        n = await tel.emit_pipeline_additions(
            job_id=job_id,
            candidate_ids=[101, 103, 101],
            user_id=w["user_id"],
            run_id=w["mine"],
            source="full_search",
        )

        assert n == 2
        rows = await _outcomes(job_id)
        # 103 was never on that run's page: added, but not joined to it.
        assert [(r.candidate_id, r.run_id, r.reason_code) for r in rows] == [
            (101, w["mine"], "full_search"),
            (103, None, "full_search"),
        ]
        assert rows[0].event_id == f"add_to_pipeline:{w['mine']}:{job_id}:101"
        assert rows[1].event_id == f"add_to_pipeline:norun:{job_id}:103"
        # A retried request (double click, proxy retry) records nothing new.
        assert (
            await tel.emit_pipeline_additions(
                job_id=job_id,
                candidate_ids=[101, 103],
                user_id=w["user_id"],
                run_id=w["mine"],
                source="full_search",
            )
            == 0
        )
    finally:
        await _cleanup_job(job_id, [w["mine"]])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["no_run_declared", "someone_elses_run", "run_for_another_job", "unknown_run"],
)
async def test_pipeline_addition_never_guesses_a_run(monkeypatch, case):
    """Before 11.09 an add without a run (manual search, historical section,
    quick-add) was credited to the latest impression this user saw for the job,
    i.e. to an unrelated C2 ranking. Now: not verifiable → NULL."""
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    w = await _run_world()
    job_id = w["job_id"]
    # The user WAS shown candidate 201 in their own run, and so was everyone
    # else in theirs — exactly the history the old fallback picked from.
    await _shown(w["mine"], job_id=job_id, user_id=w["user_id"], candidates=[201])
    await _shown(
        w["foreign"], job_id=job_id, user_id=w["other_user_id"], candidates=[201]
    )
    await _shown(
        w["elsewhere"], job_id=w["other_job_id"], user_id=w["user_id"], candidates=[201]
    )
    declared = {
        "no_run_declared": None,
        "someone_elses_run": w["foreign"],
        "run_for_another_job": w["elsewhere"],
        "unknown_run": str(uuid.uuid4()),
    }[case]
    try:
        n = await tel.emit_pipeline_additions(
            job_id=job_id,
            candidate_ids=[201],
            user_id=w["user_id"],
            run_id=declared,
            source="manual_search" if declared is None else "full_search",
        )

        assert n == 1
        (row,) = await _outcomes(job_id)
        assert row.run_id is None
        assert row.event_id == f"add_to_pipeline:norun:{job_id}:201"
    finally:
        await _cleanup_job(job_id, [w["mine"], w["foreign"], w["elsewhere"]])


@pytest.mark.asyncio
async def test_talent_radar_run_without_a_job_never_joins_the_add(monkeypatch):
    """17.09.2026: Talent Radar result cards and the /candidates bulk bar add
    through the same route. A Radar run has no job, so even when the user WAS
    shown the candidate in it, the add cannot join that run (``job_id`` of the
    run never equals the job added to) — ``run_id`` stays NULL, the source is
    still recorded from the closed vocabulary."""
    from app.models.candidate_search_run import CandidateSearchRun
    from app.models.client import Client
    from app.models.job import Job
    from app.models.user import User, UserRole

    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Telemetry radar {tag}")
        me = User(
            email=f"tel-radar-{tag}@example.com", name="Me", role=UserRole.recruiter
        )
        db.add_all([client, me])
        await db.flush()
        job = Job(title=f"Telemetry radar job {tag}", client_id=client.id)
        db.add(job)
        await db.flush()
        radar = CandidateSearchRun(
            id=str(uuid.uuid4()),
            created_by=me.id,
            client_id=client.id,
            job_id=None,
            state="complete",
            request_fingerprint="f" * 64,
            request_context={},
            version_trace={},
            population_size=0,
            metrics={},
        )
        db.add(radar)
        await db.commit()
        job_id, user_id, radar_id = job.id, me.id, radar.id
    try:
        await tel.record_full_search_page(
            None,
            run_id=radar_id,
            job_id=None,
            client_id=1,
            user_id=user_id,
            version_trace=None,
            entries=[ImpressionEntry(candidate_id=401, rank=0)],
            degraded=False,
        )
        await tel.emit_pipeline_additions(
            job_id=job_id,
            candidate_ids=[401],
            user_id=user_id,
            run_id=radar_id,
            source="talent_radar",
        )
        await tel.emit_pipeline_additions(
            job_id=job_id,
            candidate_ids=[402],
            user_id=user_id,
            source="candidate_list",
        )
        rows = await _outcomes(job_id)
        assert [(r.candidate_id, r.run_id, r.reason_code) for r in rows] == [
            (401, None, "talent_radar"),
            (402, None, "candidate_list"),
        ]
    finally:
        await _cleanup_job(job_id, [radar_id])


@pytest.mark.asyncio
async def test_unknown_add_source_is_stored_as_null_not_free_text(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    job_id = _job_id()
    try:
        await tel.emit_pipeline_additions(
            job_id=job_id, candidate_ids=[301], user_id=7, source="jan.kowalski"
        )
        (row,) = await _outcomes(job_id)
        assert row.reason_code is None
    finally:
        await _cleanup_job(job_id, [])


@pytest.mark.asyncio
async def test_a_results_page_is_one_insert(monkeypatch):
    """Up to 100 served rows used to be up to 100 sequential INSERTs on the
    request path. One statement now, still idempotent per (run, candidate),
    and a candidate repeated in the entries keeps its first (best) rank."""
    from sqlalchemy.ext.asyncio import AsyncSession

    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    executed: list[str] = []
    original = AsyncSession.execute

    async def counting(self, statement, *args, **kwargs):
        executed.append(str(statement))
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", counting)
    run_id = _run_id()
    entries = [
        ImpressionEntry(candidate_id=400 + i, rank=i, fit_score=90 - i)
        for i in range(20)
    ] + [ImpressionEntry(candidate_id=400, rank=99)]
    try:
        first = await tel.record_impressions(
            None, run_id=run_id, surface="test", entries=entries, user_id=7
        )
        inserts = [s for s in executed if "INSERT INTO match_impressions" in s]
        assert first == 20
        assert len(inserts) == 1
        again = await tel.record_impressions(
            None, run_id=run_id, surface="test", entries=entries
        )
        assert again == 0
        async with AsyncSessionLocal() as db:
            rank, fit = (
                await db.execute(
                    text(
                        "SELECT rank, fit_score FROM match_impressions"
                        " WHERE run_id = :r AND candidate_id = 400"
                    ),
                    {"r": run_id},
                )
            ).one()
        assert (rank, fit) == (0, 90.0)
    finally:
        await _cleanup(run_id)


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
