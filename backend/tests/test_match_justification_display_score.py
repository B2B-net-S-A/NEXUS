"""The "Dopasowanie" tab shows the number C2 shows for the pair.

Since #1428 every C2 screen (recommendations, /ai-matches, shortlist, proposals,
digest, kanban ring) shows canonical base fit. The tab kept the legacy composite
(`get_cached_or_compute`), so the same candidate–job pair carried two different
numbers depending on the screen. The ring now comes from `display_fit`; the
prose keeps its own (legacy) input and cache key — that is deliberate.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import candidate_scoring
from app.models.candidate import Candidate
from app.models.job import Job
from app.services import canonical_fit
from app.services import match_justification_service as mjs
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


def _db(candidate, job):
    async def get(model, pk):
        return {Candidate: candidate, Job: job}[model]

    return SimpleNamespace(get=AsyncMock(side_effect=get), rollback=AsyncMock())


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(
        "app.services.requirement_verification.latest_verifications",
        AsyncMock(return_value=[]),
    )
    profile = AsyncMock(return_value=DEFAULT_PROFILE)
    monkeypatch.setattr("app.services.scoring_service.resolve_active_profile", profile)
    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=[1, 0]))
    measurement = {"value": VectorMeasurement(0.55, "measured")}

    async def measure(vector, batch):
        return {c.id: measurement["value"] for c in batch}

    monkeypatch.setattr(canonical_fit, "measure_candidates", measure)
    return SimpleNamespace(profile=profile, measurement=measurement)


@pytest.mark.asyncio
async def test_display_fit_is_the_canonical_number_under_the_viewers_profile(
    measured,
):
    candidate = make_candidate(id=3, skills=["Python"])
    job = make_job(id=9, client_id=4, must_skills=["Python"])
    db = _db(candidate, job)

    score, measurement = await mjs.display_fit(3, 9, db, user_id=12)

    expected = await canonical_fit.score_pair(
        None,
        build_request_context(job, DEFAULT_PROFILE),
        candidate,
        VectorMeasurement(0.55, "measured"),
    )
    assert score == canonical_fit.display_score(expected.fit_score)
    assert measurement == "measured"
    measured.profile.assert_awaited_once_with(db, user_id=12, client_id=4)
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_unmeasured_pair_shows_no_number(measured):
    measured.measurement["value"] = VectorMeasurement(None, "stale")
    db = _db(make_candidate(id=3), make_job(id=9))

    assert await mjs.display_fit(3, 9, db, user_id=1) == (None, "stale")


@pytest.mark.asyncio
async def test_a_failed_measurement_never_breaks_the_tab(measured, monkeypatch):
    monkeypatch.setattr(
        canonical_fit, "request_vector", AsyncMock(side_effect=RuntimeError("x"))
    )

    async def boom(vector, batch):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(canonical_fit, "measure_candidates", boom)
    db = _db(make_candidate(id=3), make_job(id=9))

    assert await mjs.display_fit(3, 9, db, user_id=1) == (None, "unavailable")
    # A failed query poisons the request transaction; it must be rolled back.
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_pair_is_not_scored(measured):
    db = _db(None, make_job(id=9))

    assert await mjs.display_fit(3, 9, db, user_id=1) == (None, "unavailable")
    measured.profile.assert_not_awaited()


def _row(**overrides):
    base = dict(
        candidate_id=3,
        job_id=9,
        score=88,  # legacy composite the prose was generated from
        summary="Opis",
        pros=["a"],
        watchouts=[],
        model="m",
        rating=None,
        rating_comment=None,
        updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_tab_ring_shows_the_canonical_number_not_the_prose_composite(
    monkeypatch,
):
    order: list[str] = []

    async def fit(*args, **kwargs):
        order.append("fit")
        return 61, "measured"

    async def generate(*args, **kwargs):
        order.append("justification")
        return _row()

    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(candidate_scoring, "get_or_generate", generate)
    monkeypatch.setattr(
        candidate_scoring, "_notes_warnings_for", AsyncMock(return_value=("T", []))
    )
    handler = inspect.unwrap(candidate_scoring.get_scoring_justification)

    out = await handler(
        request=None,
        candidate_id=3,
        job_id=9,
        current_user=SimpleNamespace(id=12),
        refresh=False,
        db=object(),
    )

    assert out.score == 61 and out.score_measurement == "measured"
    # The fit is computed BEFORE the row is loaded: its rollback-on-failure must
    # not expire the row that is serialized afterwards.
    assert order == ["fit", "justification"]


@pytest.mark.asyncio
async def test_rating_response_keeps_the_same_number(monkeypatch):
    """The feedback response replaces the tab's data; a legacy number there
    would flip the ring after every thumbs-up."""
    monkeypatch.setattr(
        candidate_scoring, "display_fit", AsyncMock(return_value=(None, "stale"))
    )
    monkeypatch.setattr(candidate_scoring, "get_cached", AsyncMock(return_value=_row()))
    monkeypatch.setattr(
        candidate_scoring, "_notes_warnings_for", AsyncMock(return_value=("T", []))
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    out = await candidate_scoring.rate_scoring_justification(
        3,
        9,
        candidate_scoring.ScoringFeedbackIn(rating=1),
        current_user=SimpleNamespace(id=12),
        db=db,
    )

    assert out.score is None and out.score_measurement == "stale"
    assert out.rating == 1
