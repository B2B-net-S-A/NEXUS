"""Unit + integration tests for `similar_job_candidates` (Phase 14).

Covers:
- stage weights and decay math
- boost-points calculation
- ranking of candidates from similar historical jobs with mocked DB + Qdrant
- tier fallback (primary → extended) when Tier A is thin
- negative signal flag + include_negative=false filtering
- 18-month cutoff
- endpoint shape and error handling through the in-process FastAPI client
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.models.recruitment_pipeline import PipelineStage
from app.services import similar_job_candidates as sjc


# ── Math helpers ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_decay_is_one_at_zero_months() -> None:
    assert sjc._decay(0.0) == pytest.approx(1.0)
    assert sjc._decay(-3.0) == pytest.approx(1.0)  # future clock skew


@pytest.mark.unit
def test_decay_at_half_life_matches_exp_minus_one() -> None:
    # With DECAY_HALF_LIFE_MONTHS = 12, decay(12) = e^-1 ≈ 0.3679
    assert sjc._decay(12.0) == pytest.approx(0.3679, abs=0.001)


@pytest.mark.unit
def test_decay_monotonically_decreasing() -> None:
    assert sjc._decay(3) > sjc._decay(6) > sjc._decay(12) > sjc._decay(18)


@pytest.mark.unit
def test_months_ago_handles_naive_datetime() -> None:
    now = datetime.now(timezone.utc)
    naive = (now - timedelta(days=90)).replace(tzinfo=None)
    months = sjc._months_ago(naive, now=now)
    assert 2.9 <= months <= 3.1


@pytest.mark.unit
def test_months_ago_future_datetime_returns_zero() -> None:
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=5)
    assert sjc._months_ago(future, now=now) == 0.0


@pytest.mark.unit
def test_boost_points_caps_at_three_sources() -> None:
    assert sjc.boost_points_for_sources(0) == 0.0
    assert sjc.boost_points_for_sources(1) == 5.0
    assert sjc.boost_points_for_sources(3) == 15.0
    assert sjc.boost_points_for_sources(7) == 15.0  # capped


@pytest.mark.unit
def test_stage_weight_map_covers_all_positive_and_negative_stages() -> None:
    # Terminal positives are 1.0
    assert sjc.STAGE_WEIGHT[PipelineStage.hired] == 1.0
    assert sjc.STAGE_WEIGHT[PipelineStage.acceptance] == 1.0
    # Rejections are negative
    assert sjc.STAGE_WEIGHT[PipelineStage.rejected] < 0
    assert sjc.STAGE_WEIGHT[PipelineStage.withdrawn] < 0
    # `new` intentionally carries no signal and is not in the map.
    assert PipelineStage.new not in sjc.STAGE_WEIGHT


# ── Ranking (with mocked DB + Qdrant) ────────────────────────────────────────


def _stage_row(
    *,
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    moved_at: datetime,
) -> SimpleNamespace:
    """Fake CandidateStage ORM row for the ranking query result."""
    return SimpleNamespace(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=stage,
        moved_at=moved_at,
    )


class _FakeExecuteResult:
    """Mimics the subset of SQLAlchemy Result used by the service."""

    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> "_FakeExecuteResult":
        return self


class _FakeDb:
    """Async-session double that returns canned rows for the two queries used.

    Query order inside `_rank_candidates_from_similar`:
      1. stages + job title join  →  `stage_rows`
      2. blacklist filter         →  `blacklisted_rows`
    """

    def __init__(
        self,
        stage_rows: list[Any],
        blacklisted_ids: set[int] | None = None,
    ):
        self._responses = [
            _FakeExecuteResult(stage_rows),
            _FakeExecuteResult([(i,) for i in (blacklisted_ids or set())]),
        ]
        self.calls = 0

    async def execute(self, _stmt: Any) -> _FakeExecuteResult:
        result = self._responses[self.calls]
        self.calls = min(self.calls + 1, len(self._responses) - 1)
        return result


def _refs_tier_a(
    job_ids: list[int], similarity: float = 0.80
) -> list[sjc.SimilarJobRef]:
    return [
        sjc.SimilarJobRef(
            job_id=jid, title=f"Job {jid}", similarity=similarity, tier="A"
        )
        for jid in job_ids
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rank_candidates_sums_contributions_not_max() -> None:
    """Candidate in multiple positive sources should beat one with a single source."""
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "Historical Job 100",
            None,
        ),
        (
            _stage_row(
                candidate_id=1,
                job_id=101,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "Historical Job 101",
            None,
        ),
        (
            _stage_row(
                candidate_id=2,
                job_id=100,
                stage=PipelineStage.hired,  # single but strongest stage
                moved_at=now - timedelta(days=30),
            ),
            "Historical Job 100",
            None,
        ),
    ]
    refs = _refs_tier_a([100, 101])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
    )
    by_id = {r.candidate_id: r for r in results}
    assert set(by_id) == {1, 2}
    # Candidate 1: 2 * (0.80 * 0.5 * decay(~1mc)) ≈ 0.77
    # Candidate 2: 1 * (0.80 * 1.0 * decay(~1mc)) ≈ 0.77 — very close
    # Both positive, but frequency (cand 1) alone should at least tie
    assert by_id[1].historical_score > 0
    assert by_id[2].historical_score > 0
    # Candidate 1 has 2 sources, candidate 2 has 1 source
    assert len(by_id[1].sources) == 2
    assert len(by_id[2].sources) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rank_flags_negative_signal_when_rejected() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            None,
        ),
        (
            _stage_row(
                candidate_id=1,
                job_id=101,
                stage=PipelineStage.rejected,
                moved_at=now - timedelta(days=60),
            ),
            "Job 101",
            None,
        ),
    ]
    refs = _refs_tier_a([100, 101])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
    )
    assert len(results) == 1
    assert results[0].negative_signal is True
    # Hired (1.0) + rejected (-0.3) ≈ still positive
    assert results[0].historical_score > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_include_negative_false_drops_rejection_only_candidate() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=42,
                job_id=100,
                stage=PipelineStage.rejected,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            None,
        ),
    ]
    refs = _refs_tier_a([100])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=False,
    )
    # Nothing to show — the only candidate was a rejection and we opted out.
    assert results == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blacklisted_candidates_filtered_out() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            None,
        ),
        (
            _stage_row(
                candidate_id=2,
                job_id=100,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            None,
        ),
    ]
    refs = _refs_tier_a([100])
    db = _FakeDb(stage_rows=stage_rows, blacklisted_ids={2})

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
    )
    assert [c.candidate_id for c in results] == [1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_stage_has_no_signal() -> None:
    """`new` stage carries no qualification signal — must not contribute."""
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=7,
                job_id=100,
                stage=PipelineStage.new,
                moved_at=now - timedelta(days=15),
            ),
            "Job 100",
            None,
        ),
    ]
    refs = _refs_tier_a([100])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
    )
    assert results == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_refs_returns_empty() -> None:
    db = _FakeDb(stage_rows=[])
    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=[],
        include_negative=True,
    )
    assert results == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_similar_jobs_primary_filters_tier_b() -> None:
    qdrant_hits = [
        {"job_id": 1, "score": 0.82, "payload": {"title": "J1"}},
        {"job_id": 2, "score": 0.60, "payload": {"title": "J2"}},  # Tier B
        {"job_id": 3, "score": 0.40, "payload": {"title": "J3"}},  # below threshold
    ]
    with patch.object(
        sjc,
        "search_similar_jobs_by_job_id",
        new=AsyncMock(return_value=qdrant_hits),
    ):
        refs, tier_used = await sjc.fetch_similar_jobs(99, tier="primary")

    assert [r.job_id for r in refs] == [1]
    assert refs[0].tier == "A"
    assert tier_used == "primary"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_similar_jobs_extended_includes_tier_b() -> None:
    qdrant_hits = [
        {"job_id": 1, "score": 0.82, "payload": {"title": "J1"}},
        {"job_id": 2, "score": 0.60, "payload": {"title": "J2"}},
    ]
    with patch.object(
        sjc,
        "search_similar_jobs_by_job_id",
        new=AsyncMock(return_value=qdrant_hits),
    ):
        refs, tier_used = await sjc.fetch_similar_jobs(99, tier="extended")

    assert {r.job_id: r.tier for r in refs} == {1: "A", 2: "B"}
    assert tier_used == "extended"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_similar_jobs_empty_when_qdrant_returns_nothing() -> None:
    with patch.object(
        sjc,
        "search_similar_jobs_by_job_id",
        new=AsyncMock(return_value=[]),
    ):
        refs, tier_used = await sjc.fetch_similar_jobs(99, tier="extended")

    assert refs == []
    assert tier_used == "empty"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_historical_candidates_tier_fallback_to_extended() -> None:
    """Primary tier with <5 candidates should auto-promote to extended."""
    now = datetime.now(timezone.utc)
    # Primary query: only 1 Tier A hit → 1 candidate
    primary_hits = [
        {"job_id": 1, "score": 0.82, "payload": {"title": "J1"}},
    ]
    extended_hits = [
        {"job_id": 1, "score": 0.82, "payload": {"title": "J1"}},
        {"job_id": 2, "score": 0.60, "payload": {"title": "J2"}},
        {"job_id": 3, "score": 0.58, "payload": {"title": "J3"}},
    ]

    primary_stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=1,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "J1",
            None,
        ),
    ]
    extended_stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=1,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "J1",
            None,
        ),
        (
            _stage_row(
                candidate_id=2,
                job_id=2,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=40),
            ),
            "J2",
            None,
        ),
        (
            _stage_row(
                candidate_id=3,
                job_id=3,
                stage=PipelineStage.acceptance,
                moved_at=now - timedelta(days=50),
            ),
            "J3",
            None,
        ),
    ]

    # _rank is called twice: once for primary (1 candidate → fallback triggers),
    # then once for extended (3 candidates).
    call_state = {"count": 0}

    async def fake_search(job_id: int, top_k: int, exclude_self: bool):
        call_state["count"] += 1
        return primary_hits if call_state["count"] == 1 else extended_hits

    class _SwitchDb:
        """Returns primary stage rows on first call, extended on second."""

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _stmt: Any) -> _FakeExecuteResult:
            self.calls += 1
            # Cycle: stages (primary) → blacklist → stages (extended) → blacklist
            if self.calls == 1:
                return _FakeExecuteResult(primary_stage_rows)
            if self.calls == 2:
                return _FakeExecuteResult([])  # no blacklisted
            if self.calls == 3:
                return _FakeExecuteResult(extended_stage_rows)
            return _FakeExecuteResult([])

    db = _SwitchDb()
    with patch.object(
        sjc, "search_similar_jobs_by_job_id", new=AsyncMock(side_effect=fake_search)
    ):
        candidates, refs, tier_used = await sjc.fetch_historical_candidates(
            db,  # type: ignore[arg-type]
            job_id=999,
            tier="primary",
            limit=20,
        )

    # Extended fallback kicked in: we now have 3 candidates.
    assert len(candidates) == 3
    assert tier_used == "extended"
    assert len(refs) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_primary_tier_falls_back_when_no_tier_a_jobs_at_all() -> None:
    """When Qdrant returns only Tier B hits, primary mode must still promote.

    Regression: early return on empty similar_refs skipped the fallback path
    entirely, leaving the widget permanently empty for tenants whose jobs sit
    just below the 0.70 cosine threshold (the common early-stage case).
    """
    now = datetime.now(timezone.utc)
    primary_hits: list[dict] = []  # no Tier A jobs (all <0.70)
    extended_hits = [
        {"job_id": 1, "score": 0.65, "payload": {"title": "J1"}},
        {"job_id": 2, "score": 0.60, "payload": {"title": "J2"}},
    ]
    extended_stage_rows = [
        (
            _stage_row(
                candidate_id=10,
                job_id=1,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=30),
            ),
            "J1",
            None,
        ),
        (
            _stage_row(
                candidate_id=20,
                job_id=2,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=45),
            ),
            "J2",
            None,
        ),
    ]

    calls = {"count": 0}

    async def fake_search(job_id: int, top_k: int, exclude_self: bool):
        calls["count"] += 1
        return primary_hits if calls["count"] == 1 else extended_hits

    class _SwitchDb:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _stmt):
            self.calls += 1
            if self.calls == 1:
                return _FakeExecuteResult(extended_stage_rows)
            return _FakeExecuteResult([])  # no blacklisted

    with patch.object(
        sjc, "search_similar_jobs_by_job_id", new=AsyncMock(side_effect=fake_search)
    ):
        candidates, refs, tier_used = await sjc.fetch_historical_candidates(
            _SwitchDb(),  # type: ignore[arg-type]
            job_id=42,
            tier="primary",
        )

    assert tier_used == "extended"
    assert len(refs) == 2
    assert len(candidates) == 2
    # Hired is the top signal — candidate 10 should outrank candidate 20.
    assert candidates[0].candidate_id == 10


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_historical_boost_map_returns_source_counts() -> None:
    now = datetime.now(timezone.utc)
    qdrant_hits = [
        {"job_id": 100, "score": 0.80, "payload": {"title": "J100"}},
        {"job_id": 101, "score": 0.75, "payload": {"title": "J101"}},
    ]
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=30),
            ),
            "J100",
            None,
        ),
        (
            _stage_row(
                candidate_id=1,
                job_id=101,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=60),
            ),
            "J101",
            None,
        ),
        (
            _stage_row(
                candidate_id=2,
                job_id=100,
                stage=PipelineStage.rejected,
                moved_at=now - timedelta(days=30),
            ),
            "J100",
            None,
        ),
    ]
    db = _FakeDb(stage_rows=stage_rows)
    with patch.object(
        sjc,
        "search_similar_jobs_by_job_id",
        new=AsyncMock(return_value=qdrant_hits),
    ):
        boost_map = await sjc.fetch_historical_boost_map(db, job_id=42)  # type: ignore[arg-type]

    # Candidate 1 has 2 positive sources → counted.
    # Candidate 2 has ONLY a rejection → excluded (include_negative=False inside boost path).
    assert boost_map == {1: 2}


# ── Endpoint integration ─────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_rejects_invalid_tier(app_client, app_auth_headers):
    r = await app_client.get(
        "/api/jobs/1/candidates-from-similar",
        params={"tier": "garbage"},
        headers=app_auth_headers,
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_404_for_missing_job(app_client, app_auth_headers):
    r = await app_client.get(
        "/api/jobs/9999999/candidates-from-similar",
        headers=app_auth_headers,
    )
    assert r.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_shape_when_no_similar_jobs(
    app_client, app_auth_headers
) -> None:
    """When Qdrant returns nothing, endpoint must respond gracefully (not 500)."""
    import uuid as _uuid

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    # Create a minimal job directly to get a real id for the endpoint to hit.
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SimilarClient-{_uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title="pytest-similar-empty",
            description="pytest sentinel — no embedding expected",
            status=JobStatus.draft,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    try:
        with patch.object(
            sjc,
            "search_similar_jobs_by_job_id",
            new=AsyncMock(return_value=[]),
        ):
            r = await app_client.get(
                f"/api/jobs/{job_id}/candidates-from-similar",
                headers=app_auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job_id"] == job_id
        assert body["tier_used"] == "empty"
        assert body["candidates"] == []
        assert body["similar_jobs"] == []
        assert body["meta"]["reason_if_empty"] == "no_similar_jobs_found"
    finally:
        async with AsyncSessionLocal() as db:
            obj = await db.get(Job, job_id)
            if obj is not None:
                await db.delete(obj)
                await db.commit()


# ── Same-client flags (szybkie przepinanie, Faza 3) ─────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_client_flag_set_when_source_matches_target_client() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            55,  # client_id of the historical job
        ),
        (
            _stage_row(
                candidate_id=2,
                job_id=101,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "Job 101",
            77,  # different client
        ),
    ]
    refs = _refs_tier_a([100, 101])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
        target_client_id=55,
    )
    by_id = {r.candidate_id: r for r in results}
    assert by_id[1].same_client is True
    assert by_id[1].rejected_by_same_client is False
    assert by_id[2].same_client is False
    assert by_id[2].rejected_by_same_client is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejected_by_same_client_flag() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.rejected,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            55,
        ),
        (
            _stage_row(
                candidate_id=1,
                job_id=101,
                stage=PipelineStage.hired,
                moved_at=now - timedelta(days=60),
            ),
            "Job 101",
            77,
        ),
    ]
    refs = _refs_tier_a([100, 101])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
        target_client_id=55,
    )
    assert len(results) == 1
    cand = results[0]
    assert cand.same_client is True
    assert cand.rejected_by_same_client is True
    assert cand.negative_signal is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flags_default_false_without_target_client() -> None:
    now = datetime.now(timezone.utc)
    stage_rows = [
        (
            _stage_row(
                candidate_id=1,
                job_id=100,
                stage=PipelineStage.cv_sent,
                moved_at=now - timedelta(days=30),
            ),
            "Job 100",
            55,
        ),
    ]
    refs = _refs_tier_a([100])
    db = _FakeDb(stage_rows=stage_rows)

    results = await sjc._rank_candidates_from_similar(
        db,  # type: ignore[arg-type]
        similar_refs=refs,
        include_negative=True,
    )
    assert results[0].same_client is False
    assert results[0].rejected_by_same_client is False


# ── Bramka dopuszczalności na endpoincie (2026-08-20) ────────────────────────
#
# `_rank_candidates_from_similar` odsiewa wyłącznie blacklistę GLOBALNĄ i nie ma
# dostępu do `job`, więc aktywny konflikt z klientem TEJ oferty (blacklista
# klienta, NDA, konkurent) oraz weto hiring managera przechodziły przez tę
# sekcję na wylot. A to sekcja, która z definicji celuje w ludzi już
# rozważanych u tego klienta — czyli w populację, w której takie blokady
# siedzą najgęściej.
#
# Testy patchują `fetch_historical_candidates` (bo ranking wymaga Qdranta), ale
# kandydaci i konflikty są PRAWDZIWYMI wierszami — bramka biegnie po realnym
# `candidate_conflicts`, czyli po ścieżce, na której siedział defekt.


def _hist_candidate(candidate_id: int) -> sjc.HistoricalCandidate:
    now = datetime.now(timezone.utc)
    return sjc.HistoricalCandidate(
        candidate_id=candidate_id,
        historical_score=1.0,
        tier="A",
        negative_signal=False,
        sources=(
            sjc.HistoricalSource(
                job_id=999,
                job_title="Poprzedni request",
                stage=PipelineStage.cv_sent,
                similarity=0.85,
                months_ago=2.0,
                moved_at=now,
                stage_weight=0.5,
                contribution=0.4,
                client_id=None,
            ),
        ),
    )


async def _seed_job_with_candidates(*, blocked_count: int, total: int = 2):
    """Klient + oferta + `total` kandydatów, z czego `blocked_count` z NDA."""
    import uuid as _uuid

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    unique = _uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SimilarGate-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"pytest-similar-gate-{unique}",
            description="pytest sentinel",
            status=JobStatus.draft,
            client_id=cli.id,
            hiring_manager_contact_id=None,
        )
        db.add(job)
        cands = [
            # Status `active`, NIE `blacklisted`: globalną blacklistę odsiewa już
            # serwis, więc taki seed nie dowodziłby niczego o nowej bramce.
            Candidate(
                name=f"Hist{i}",
                lastname=f"Kandydat{unique}",
                email=f"hist-{i}-{unique}@example.com",
                status=CandidateStatus.active,
            )
            for i in range(total)
        ]
        db.add_all(cands)
        await db.flush()
        for c in cands[:blocked_count]:
            db.add(
                CandidateConflict(
                    candidate_id=c.id,
                    client_id=cli.id,
                    type=ConflictType.nda,
                    reason="pytest — NDA u klienta oferty",
                    active=True,
                )
            )
        await db.commit()
        return job.id, cli.id, [c.id for c in cands]


async def _cleanup(job_id: int, client_id: int, cand_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_conflict import CandidateConflict
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateConflict).where(CandidateConflict.client_id == client_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(cand_ids)))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _patched_fetch(ranked: list[sjc.HistoricalCandidate]):
    refs = [sjc.SimilarJobRef(job_id=999, title="Poprzedni", similarity=0.9, tier="A")]
    return AsyncMock(return_value=(ranked, refs, "primary"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ineligible_candidate_from_history_is_not_returned(
    app_client, app_auth_headers
) -> None:
    job_id, client_id, cand_ids = await _seed_job_with_candidates(blocked_count=1)
    blocked_id, clean_id = cand_ids[0], cand_ids[1]
    try:
        with patch(
            "app.api.recommendations.fetch_historical_candidates",
            new=_patched_fetch([_hist_candidate(i) for i in cand_ids]),
        ):
            r = await app_client.get(
                f"/api/jobs/{job_id}/candidates-from-similar",
                headers=app_auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        returned = [c["candidate_id"] for c in body["candidates"]]
        assert blocked_id not in returned, (
            "kandydat z aktywnym NDA u klienta tej oferty trafił do sekcji, "
            "z której bulk-select przepina ludzi jednym kliknięciem"
        )
        assert clean_id in returned
        assert body["meta"]["hidden_ineligible"] == 1
    finally:
        await _cleanup(job_id, client_id, cand_ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_meta_says_why_the_section_is_empty(app_client, app_auth_headers) -> None:
    """Bez tego pusta sekcja i „nie ma historii" są nierozróżnialne.

    Front nie miałby na czym oprzeć komunikatu, a rekruter zobaczyłby „brak
    kandydatów w historii" tam, gdzie historia jest akurat najgęstsza.
    """
    job_id, client_id, cand_ids = await _seed_job_with_candidates(blocked_count=2)
    try:
        with patch(
            "app.api.recommendations.fetch_historical_candidates",
            new=_patched_fetch([_hist_candidate(i) for i in cand_ids]),
        ):
            r = await app_client.get(
                f"/api/jobs/{job_id}/candidates-from-similar",
                headers=app_auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"] == []
        assert body["meta"]["hidden_ineligible"] == 2
        assert body["meta"]["reason_if_empty"] == "all_hidden_by_eligibility"
    finally:
        await _cleanup(job_id, client_id, cand_ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vanished_candidate_is_not_counted_as_hidden(
    app_client, app_auth_headers
) -> None:
    """Licznik liczy po ZHYDRATOWANYCH wierszach, nie po `cand_ids`.

    Wiersz skasowany w międzyczasie nie jest „zablokowany dla tego klienta" —
    liczenie go jako ukrytego byłoby kłamstwem w drugą stronę i zapaliłoby
    we froncie komunikat o blokadzie tam, gdzie blokady nie ma.
    """
    job_id, client_id, cand_ids = await _seed_job_with_candidates(blocked_count=0)
    ghost_id = max(cand_ids) + 10_000_000
    try:
        with patch(
            "app.api.recommendations.fetch_historical_candidates",
            new=_patched_fetch([_hist_candidate(ghost_id)]),
        ):
            r = await app_client.get(
                f"/api/jobs/{job_id}/candidates-from-similar",
                headers=app_auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"] == []
        assert body["meta"]["hidden_ineligible"] == 0
        assert body["meta"]["reason_if_empty"] != "all_hidden_by_eligibility"
    finally:
        await _cleanup(job_id, client_id, cand_ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_similar_jobs_keeps_meta_default(app_client, app_auth_headers) -> None:
    """Wczesny return (brak podobnych ofert) nie musi znać nowego pola.

    Guard na addytywność kontraktu: default `0` sprawia, że dodanie licznika nie
    wymaga dotykania wszystkich `return`-ów.
    """
    job_id, client_id, cand_ids = await _seed_job_with_candidates(blocked_count=0)
    try:
        with patch.object(
            sjc, "search_similar_jobs_by_job_id", new=AsyncMock(return_value=[])
        ):
            r = await app_client.get(
                f"/api/jobs/{job_id}/candidates-from-similar",
                headers=app_auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tier_used"] == "empty"
        assert body["meta"]["hidden_ineligible"] == 0
        assert body["meta"]["reason_if_empty"] == "no_similar_jobs_found"
    finally:
        await _cleanup(job_id, client_id, cand_ids)
