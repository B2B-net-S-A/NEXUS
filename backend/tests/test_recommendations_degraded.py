"""Safety tests for degraded job recommendations.

The semantic provider is allowed to fail, but the endpoint must never replace
it with arbitrary database rows or persist a normal-looking hybrid score.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.api import recommendations
from app.models.candidate import CandidateStatus
from app.models.job import JobStatus
from app.services.scoring_service import DEFAULT_PROFILE


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _FakeDB:
    def __init__(self, job: object, candidate: object):
        self.job = job
        self.candidate = candidate
        self.execute_count = 0

    async def scalar(self, _statement):
        return self.job

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _Rows([])  # candidate is not already in this pipeline
        return _Rows([self.candidate])


@pytest.mark.asyncio
async def test_semantic_outage_returns_bm25_rows_without_match_score(
    monkeypatch: pytest.MonkeyPatch,
):
    job = SimpleNamespace(
        id=11,
        title="Python Developer",
        description="FastAPI",
        requirements="Python",
        location=None,
        seniority=None,
        subcategory=None,
        industry=None,
        train_name=None,
        champion_profile=None,
        must_skills=[],
        nice_skills=[],
        client_id=None,
    )
    candidate = SimpleNamespace(
        id=77,
        name="Jan",
        lastname="Testowy",
        email=None,
        phone=None,
        location=None,
        status=CandidateStatus.active,
        competence_category="Backend",
        salary_expectation=None,
        salary_currency="PLN",
        years_it_experience=5,
        champion=False,
        avatar_url=None,
        tags=[],
        skills=["Python"],
        ai_summary=None,
    )
    db = _FakeDB(job, candidate)

    monkeypatch.setattr(
        recommendations, "search_candidates_semantic", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        recommendations, "bm25_candidates", AsyncMock(return_value=[candidate.id])
    )
    monkeypatch.setattr(
        recommendations,
        "resolve_active_profile",
        AsyncMock(return_value=DEFAULT_PROFILE),
    )
    cache = AsyncMock()
    monkeypatch.setattr(recommendations, "bulk_get_or_compute", cache)

    request = Request({"type": "http", "method": "GET", "path": "/"})
    result = await recommendations.recommend_candidates_for_job(
        request=request,
        job_id=job.id,
        top_k=20,
        min_score=None,
        include_breakdown=True,
        exclude_in_pipeline=True,
        profile_id=None,
        location=None,
        current_user=SimpleNamespace(id=5),
        db=db,
    )

    assert result["meta"] == {
        "mode": "bm25",
        "degraded": True,
        "reason": "semantic_unavailable",
    }
    assert result["matches"][0]["candidate"]["id"] == candidate.id
    assert result["matches"][0]["total_score"] is None
    assert result["matches"][0]["breakdown"] is None
    cache.assert_not_awaited()


class _ReverseFakeDB:
    def __init__(self, candidate: object, job: object):
        self.candidate = candidate
        self.job = job
        self.execute_count = 0

    async def scalar(self, _statement):
        return self.candidate

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _Rows([self.job])
        return _Rows([])  # no existing pipeline assignment


@pytest.mark.asyncio
async def test_reverse_semantic_outage_uses_unscored_bm25_and_skips_scoring(
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = SimpleNamespace(
        id=77,
        name="Jan",
        lastname="Testowy",
        competence_category="Backend",
        skills=["Python"],
        ai_summary=None,
    )
    job = SimpleNamespace(
        id=11,
        title="Python Developer",
        client_id=None,
        location=None,
        salary_min=None,
        salary_max=None,
        remote_policy=None,
        status=JobStatus.published,
        priority=None,
        seniority=None,
        industry=None,
        deadline=None,
    )
    db = _ReverseFakeDB(candidate, job)

    monkeypatch.setattr(
        recommendations, "search_jobs_semantic", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(recommendations, "bm25_jobs", AsyncMock(return_value=[job.id]))
    scorer = AsyncMock()
    monkeypatch.setattr(recommendations, "rank_jobs_for_candidate", scorer)

    request = Request({"type": "http", "method": "GET", "path": "/"})
    result = await recommendations.recommend_jobs_for_candidate(
        request=request,
        candidate_id=candidate.id,
        top_k=10,
        include_breakdown=True,
        only_open=True,
        current_user=SimpleNamespace(id=5),
        db=db,
    )

    assert result["meta"] == {
        "mode": "bm25",
        "degraded": True,
        "reason": "semantic_unavailable",
    }
    assert result["matches"][0]["job"]["id"] == job.id
    assert result["matches"][0]["total_score"] is None
    assert result["matches"][0]["breakdown"] is None
    scorer.assert_not_awaited()
