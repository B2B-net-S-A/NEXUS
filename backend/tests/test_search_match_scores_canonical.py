"""Manual search score column = canonical fit of the visible rows.

`POST /api/search/candidates/scores` used to return only FRESH rows of the
legacy composite cache. Since #1428 moved every C2 screen to canonical fit,
nothing writes that cache for the current ranker, so on production the column
next to each job-context search row was silently empty. The route now measures
canonical fit on demand, bounded to the rows on screen, scoped by the same
guard as the full-search runs — and it must produce the same number as the
other C2 screens.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import search
from app.models.user import User, UserRole
from app.schemas.candidate_search import (
    MATCH_SCORES_MAX_CANDIDATES,
    MatchScoresRequest,
)
from app.services import canonical_fit
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from app.services.section_permissions import ProductSection
from tests.test_scoring_service import make_candidate, make_job

# The route carries `@limiter.limit`; unit tests call the handler itself.
candidate_match_scores = inspect.unwrap(search.candidate_match_scores)


def _db(candidates, *, job=None):
    return SimpleNamespace(
        get=AsyncMock(return_value=job),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: list(candidates))
            )
        ),
    )


def _user(*, pipeline: str) -> User:
    user = User(
        id=424242, email="scores@example.com", name="Scores", role=UserRole.recruiter
    )
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    } | {"sourcing": "write", "pipeline": pipeline}
    return user


@pytest.fixture
def wiring(monkeypatch):
    """Access, profile and measurement stubs; returns the mocks to assert on."""
    access = AsyncMock()
    monkeypatch.setattr("app.api.candidate_search._authorized_job", access)
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
    wiring.access.return_value = job
    candidates = [make_candidate(id=i, skills=["Python"]) for i in (1, 2)]
    db = _db(candidates)
    user = SimpleNamespace(id=42)

    response = await candidate_match_scores(
        None,
        MatchScoresRequest(job_id=7, candidate_ids=[1, 2, 1]),
        current_user=user,
        db=db,
    )

    context = build_request_context(job, DEFAULT_PROFILE)
    expected = await canonical_fit.score_pair(
        None, context, candidates[0], wiring.measurements[1]
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
    # Which profile these numbers belong to: the client keys its cache by it.
    assert response.profile_key == search._profile_key(context.weights)
    assert response.profile_key.startswith(f"{DEFAULT_PROFILE.id}:")

    # The full-search guard, and nothing stricter.
    wiring.access.assert_awaited_once_with(db, user, 7)
    wiring.profile.assert_awaited_once_with(db, user_id=42, client_id=8)
    # The fit is measured against the full request, deduplicated ids.
    assert "Django" in wiring.vector.await_args.args[0]
    assert [c.id for c in wiring.measure.await_args.args[1]] == [1, 2]


def test_profile_key_moves_with_the_weights_not_only_the_profile_id():
    """An admin editing a profile's weights keeps its id; scores computed
    before the edit must not be served as current."""
    before = {"id": 3, "name": "Zespół", "semantic": 50.0, "skills": 50.0}
    edited = {**before, "semantic": 60.0, "skills": 40.0}
    assert search._profile_key(before) != search._profile_key(edited)
    assert search._profile_key(before) == search._profile_key(dict(before))


@pytest.mark.asyncio
async def test_finance_viewer_keeps_the_salary_layer(wiring):
    wiring.finance["value"] = True
    wiring.access.return_value = make_job(id=7, client_id=8)
    db = _db([make_candidate(id=1)])

    response = await candidate_match_scores(
        None,
        MatchScoresRequest(job_id=7, candidate_ids=[1]),
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert response.breakdowns["1"]["salary"].get("status") != "redacted"


@pytest.mark.asyncio
async def test_refused_recruitment_is_refused_before_any_measurement(wiring):
    wiring.access.side_effect = HTTPException(403, "Brak dostępu")
    db = _db([make_candidate(id=1)])

    with pytest.raises(HTTPException) as error:
        await candidate_match_scores(
            None,
            MatchScoresRequest(job_id=7, candidate_ids=[1]),
            current_user=SimpleNamespace(id=1),
            db=db,
        )

    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    wiring.vector.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_ids_touch_nothing(wiring):
    db = _db([])

    response = await candidate_match_scores(
        None,
        MatchScoresRequest(job_id=7, candidate_ids=[]),
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert response.scores == {} and response.breakdowns == {}
    assert response.profile_key is None
    wiring.access.assert_not_awaited()
    db.get.assert_not_awaited()


# ── The real guard (`_authorized_job`), not a stub ─────────────────────────


@pytest.mark.asyncio
async def test_without_pipeline_access_it_is_403_before_the_job_is_read(monkeypatch):
    monkeypatch.setattr(
        canonical_fit, "request_vector", AsyncMock(side_effect=AssertionError)
    )
    db = _db([make_candidate(id=1)], job=make_job(id=7))

    with pytest.raises(HTTPException) as error:
        await candidate_match_scores(
            None,
            MatchScoresRequest(job_id=7, candidate_ids=[1]),
            current_user=_user(pipeline="none"),
            db=db,
        )

    assert error.value.status_code == 403
    db.get.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_recruitment_is_404(monkeypatch):
    monkeypatch.setattr(
        canonical_fit, "request_vector", AsyncMock(side_effect=AssertionError)
    )
    db = _db([make_candidate(id=1)], job=None)

    with pytest.raises(HTTPException) as error:
        await candidate_match_scores(
            None,
            MatchScoresRequest(job_id=7, candidate_ids=[1]),
            current_user=_user(pipeline="read"),
            db=db,
        )

    assert error.value.status_code == 404
    db.execute.assert_not_awaited()


def test_the_column_reuses_the_full_search_guard():
    """One definition of "may see canonical fit for this recruitment": the
    column must not grow a third, stricter copy (it used `ensure_job_read_access`
    — team membership — while the same number was visible on C2)."""
    from tests._ast_calls import calls_in

    calls = calls_in("app/api/search.py", "candidate_match_scores")
    assert "_authorized_job" in calls
    assert not calls & {"ensure_job_read_access", "ensure_job_membership"}


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
