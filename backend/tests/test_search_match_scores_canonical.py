"""Manual search score column = canonical fit of the visible rows.

`POST /api/search/candidates/scores` used to return only FRESH rows of the
legacy composite cache. Since #1428 moved every C2 screen to canonical fit,
nothing writes that cache for the current ranker, so on production the column
next to each job-context search row was silently empty. The route now measures
canonical fit on demand, bounded to the rows on screen, scoped by recruitment
read access — and it must produce the same number as the other C2 screens.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import search
from app.schemas.candidate_search import (
    MATCH_SCORES_MAX_CANDIDATES,
    MatchScoresRequest,
)
from app.services import canonical_fit
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


def _db(job, candidates):
    return SimpleNamespace(
        scalar=AsyncMock(return_value=job),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: list(candidates))
            )
        ),
    )


@pytest.fixture
def wiring(monkeypatch):
    """Access, profile and measurement stubs; returns the mocks to assert on."""
    access = AsyncMock()
    monkeypatch.setattr("app.api.recruitment_access.ensure_job_read_access", access)
    profile = AsyncMock(return_value=DEFAULT_PROFILE)
    monkeypatch.setattr("app.services.scoring_service.resolve_active_profile", profile)
    monkeypatch.setattr(
        "app.services.requirement_verification.latest_verifications",
        AsyncMock(return_value=[]),
    )
    finance = {"value": False}
    monkeypatch.setattr(
        "app.analytics.capabilities.user_has_capability",
        lambda user, cap: finance["value"],
    )
    vector = AsyncMock(return_value=[1.0, 0.0])
    monkeypatch.setattr(canonical_fit, "request_vector", vector)
    measurements = {
        1: VectorMeasurement(0.42, "measured"),
        2: VectorMeasurement(None, "missing_index"),
    }
    measure = AsyncMock(return_value=measurements)
    monkeypatch.setattr(canonical_fit, "measure_candidates", measure)
    return SimpleNamespace(
        access=access,
        profile=profile,
        vector=vector,
        measure=measure,
        measurements=measurements,
        finance=finance,
    )


@pytest.mark.asyncio
async def test_visible_rows_get_the_same_number_as_the_c2_screens(wiring):
    job = make_job(id=7, client_id=8, must_skills=["Python"], description="Django")
    candidates = [make_candidate(id=i, skills=["Python"]) for i in (1, 2)]
    db = _db(job, candidates)
    user = SimpleNamespace(id=42)

    response = await search.candidate_match_scores(
        MatchScoresRequest(job_id=7, candidate_ids=[1, 2, 1]),
        current_user=user,
        db=db,
    )

    expected = await canonical_fit.score_pair(
        None,
        build_request_context(job, DEFAULT_PROFILE),
        candidates[0],
        wiring.measurements[1],
    )
    assert response.scores == {"1": canonical_fit.display_score(expected.fit_score)}
    # An unmeasured candidate is "not measured", never a 0 and never missing
    # without a reason.
    assert "2" not in response.scores
    assert response.breakdowns["2"] == {"total": None, "measurement": "missing_index"}
    detail = response.breakdowns["1"]
    assert detail["total"] == expected.fit_score
    assert detail["measurement"] == "measured"
    # The detail panel / compare modal read the skill chips from here.
    assert detail["matching_must"] == expected.breakdown.as_dict()["matching_must"]
    # No view_finance → the salary layer cannot become a budget oracle.
    assert detail["salary"]["status"] == "redacted"
    assert detail["salary"]["points"] is None

    wiring.access.assert_awaited_once_with(db, user, 7)
    wiring.profile.assert_awaited_once_with(db, user_id=42, client_id=8)
    # The fit is measured against the full request, deduplicated ids.
    assert "Django" in wiring.vector.await_args.args[0]
    assert [c.id for c in wiring.measure.await_args.args[1]] == [1, 2]


@pytest.mark.asyncio
async def test_finance_viewer_keeps_the_salary_layer(wiring):
    wiring.finance["value"] = True
    job = make_job(id=7, client_id=8)
    db = _db(job, [make_candidate(id=1)])

    response = await search.candidate_match_scores(
        MatchScoresRequest(job_id=7, candidate_ids=[1]),
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert response.breakdowns["1"]["salary"].get("status") != "redacted"


@pytest.mark.asyncio
async def test_out_of_scope_recruitment_is_refused_before_any_measurement(wiring):
    wiring.access.side_effect = HTTPException(403, "Brak dostępu")
    db = _db(make_job(id=7), [make_candidate(id=1)])

    with pytest.raises(HTTPException) as error:
        await search.candidate_match_scores(
            MatchScoresRequest(job_id=7, candidate_ids=[1]),
            current_user=SimpleNamespace(id=1),
            db=db,
        )

    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    wiring.vector.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_recruitment_is_404(wiring):
    db = _db(None, [make_candidate(id=1)])

    with pytest.raises(HTTPException) as error:
        await search.candidate_match_scores(
            MatchScoresRequest(job_id=7, candidate_ids=[1]),
            current_user=SimpleNamespace(id=1),
            db=db,
        )

    assert error.value.status_code == 404
    wiring.vector.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_ids_touch_nothing(wiring):
    db = _db(make_job(id=7), [])

    response = await search.candidate_match_scores(
        MatchScoresRequest(job_id=7, candidate_ids=[]),
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert response.scores == {} and response.breakdowns == {}
    wiring.access.assert_not_awaited()
    db.scalar.assert_not_awaited()


def test_one_request_is_bounded_to_the_rows_on_screen():
    """On-demand measurement is paid per id; the page size (50) is not the
    unit — the viewport is. A client asking for more gets a 422, not a slow
    request that measures rows nobody looks at."""
    assert MATCH_SCORES_MAX_CANDIDATES == 20
    MatchScoresRequest(job_id=1, candidate_ids=list(range(1, 21)))
    with pytest.raises(ValidationError):
        MatchScoresRequest(job_id=1, candidate_ids=list(range(1, 22)))


@pytest.mark.parametrize(
    "value,expected",
    [(None, None), (72.5, 73), (72.49, 72), (0.4, 0), (99.6, 100), (100.0, 100)],
)
def test_display_score_rounds_like_the_ui(value, expected):
    """Half up like JS ``Math.round`` — Python's ``round(72.5)`` is 72, which
    would put a different integer next to the same pair than the kanban ring."""
    assert canonical_fit.display_score(value) == expected
