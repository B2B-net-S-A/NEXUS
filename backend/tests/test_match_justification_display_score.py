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
from fastapi import HTTPException

from app.api import candidate_scoring
from app.models.candidate import Candidate
from app.models.job import Job
from app.services import canonical_fit
from app.services import match_justification_service as mjs
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


class _Session:
    """Stand-in for the session ``display_fit`` opens for itself."""

    def __init__(self, candidate, job):
        async def get(model, pk):
            return {Candidate: candidate, Job: job}[model]

        self.get = AsyncMock(side_effect=get)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False


@pytest.fixture
def own_session(monkeypatch):
    """Route ``display_fit``'s own session to a stub; returns a setter."""
    holder = {}

    def use(candidate, job):
        holder["session"] = _Session(candidate, job)
        monkeypatch.setattr(mjs, "AsyncSessionLocal", lambda: holder["session"])
        return holder["session"]

    return use


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
    measured, own_session
):
    candidate = make_candidate(id=3, skills=["Python"])
    job = make_job(id=9, client_id=4, must_skills=["Python"])
    session = own_session(candidate, job)

    score, measurement = await mjs.display_fit(3, 9, user_id=12)

    expected = await canonical_fit.score_pair(
        None,
        build_request_context(job, DEFAULT_PROFILE),
        candidate,
        VectorMeasurement(0.55, "measured"),
    )
    assert score == canonical_fit.display_score(expected.fit_score)
    assert measurement == "measured"
    # Everything is read through the function's OWN session, which it closes.
    measured.profile.assert_awaited_once_with(session, user_id=12, client_id=4)
    assert session.closed


@pytest.mark.asyncio
async def test_unmeasured_pair_shows_no_number(measured, own_session):
    measured.measurement["value"] = VectorMeasurement(None, "stale")
    own_session(make_candidate(id=3), make_job(id=9))

    assert await mjs.display_fit(3, 9, user_id=1) == (None, "stale")


@pytest.mark.asyncio
async def test_a_failed_measurement_never_breaks_the_tab(
    measured, own_session, monkeypatch
):
    monkeypatch.setattr(
        canonical_fit, "request_vector", AsyncMock(side_effect=RuntimeError("x"))
    )

    async def boom(vector, batch):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(canonical_fit, "measure_candidates", boom)
    session = own_session(make_candidate(id=3), make_job(id=9))

    assert await mjs.display_fit(3, 9, user_id=1) == (None, "unavailable")
    # The failed transaction was the function's own, and it is gone.
    assert session.closed


@pytest.mark.asyncio
async def test_missing_pair_is_not_scored(measured, own_session):
    own_session(None, make_job(id=9))

    assert await mjs.display_fit(3, 9, user_id=1) == (None, "unavailable")
    measured.profile.assert_not_awaited()


def test_display_fit_cannot_reach_the_request_session():
    """No session parameter at all: the only way to share the request's
    transaction (and its identity map) would be to add one back."""
    assert list(inspect.signature(mjs.display_fit).parameters) == [
        "candidate_id",
        "job_id",
        "user_id",
    ]


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
    calls: list[tuple] = []

    async def fit(*args, **kwargs):
        calls.append(("fit", args, kwargs))
        return 61, "measured"

    async def generate(*args, **kwargs):
        calls.append(("justification", args, kwargs))
        return _row()

    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(candidate_scoring, "get_or_generate", generate)
    monkeypatch.setattr(
        candidate_scoring, "_notes_warnings_for", AsyncMock(return_value=("T", []))
    )
    handler = inspect.unwrap(candidate_scoring.get_scoring_justification)
    request_db = object()

    out = await handler(
        request=None,
        candidate_id=3,
        job_id=9,
        current_user=SimpleNamespace(id=12),
        refresh=False,
        db=request_db,
    )

    assert out.score == 61 and out.score_measurement == "measured"
    assert [name for name, *_ in calls] == ["justification", "fit"]
    _, fit_args, fit_kwargs = calls[1]
    # Measured for the viewer, and never through the request's session.
    assert fit_args == (3, 9) and fit_kwargs == {"user_id": 12}


@pytest.mark.asyncio
async def test_no_measurement_for_a_justification_that_cannot_be_served(
    monkeypatch,
):
    fit = AsyncMock(return_value=(61, "measured"))
    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(
        candidate_scoring,
        "get_or_generate",
        AsyncMock(side_effect=mjs.MatchJustificationNotFound("Kandydat nie istnieje")),
    )
    handler = inspect.unwrap(candidate_scoring.get_scoring_justification)

    with pytest.raises(HTTPException) as error:
        await handler(
            request=None,
            candidate_id=3,
            job_id=9,
            current_user=SimpleNamespace(id=12),
            refresh=False,
            db=object(),
        )

    assert error.value.status_code == 404
    fit.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_failure_detail_never_carries_the_provider_error(monkeypatch):
    """The 502 detail is rendered on the recruiter's screen; the provider's
    error text (model id, request id, raw output) belongs in the log only."""
    secret = "anthropic 529 overloaded req_011CSecretRequestId model=claude-x"
    fit = AsyncMock(return_value=(61, "measured"))
    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(
        candidate_scoring,
        "get_or_generate",
        AsyncMock(side_effect=mjs.MatchJustificationLLMError(secret)),
    )
    handler = inspect.unwrap(candidate_scoring.get_scoring_justification)

    with pytest.raises(HTTPException) as error:
        await handler(
            request=None,
            candidate_id=3,
            job_id=9,
            current_user=SimpleNamespace(id=12),
            refresh=False,
            db=object(),
        )

    assert error.value.status_code == 502
    assert error.value.detail == "Nie udało się wygenerować uzasadnienia AI."
    assert "req_011" not in error.value.detail
    fit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rating_response_keeps_the_same_number(monkeypatch):
    """The feedback response replaces the tab's data; a legacy number there
    would flip the ring after every thumbs-up."""
    fit = AsyncMock(return_value=(None, "stale"))
    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(candidate_scoring, "get_cached", AsyncMock(return_value=_row()))
    monkeypatch.setattr(
        candidate_scoring, "_notes_warnings_for", AsyncMock(return_value=("T", []))
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    handler = inspect.unwrap(candidate_scoring.rate_scoring_justification)

    out = await handler(
        None,
        3,
        9,
        candidate_scoring.ScoringFeedbackIn(rating=1),
        current_user=SimpleNamespace(id=12),
        db=db,
    )

    assert out.score is None and out.score_measurement == "stale"
    assert out.rating == 1
    fit.assert_awaited_once_with(3, 9, user_id=12)


@pytest.mark.asyncio
async def test_rating_a_missing_justification_is_404_before_any_measurement(
    monkeypatch,
):
    fit = AsyncMock(return_value=(61, "measured"))
    monkeypatch.setattr(candidate_scoring, "display_fit", fit)
    monkeypatch.setattr(candidate_scoring, "get_cached", AsyncMock(return_value=None))
    handler = inspect.unwrap(candidate_scoring.rate_scoring_justification)

    with pytest.raises(HTTPException) as error:
        await handler(
            None,
            3,
            9,
            candidate_scoring.ScoringFeedbackIn(rating=1),
            current_user=SimpleNamespace(id=12),
            db=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        )

    assert error.value.status_code == 404
    fit.assert_not_awaited()
