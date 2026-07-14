"""Regression tests for fail-safe AI matching retrieval."""

import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.api import cv_match_preview, matching


class _ScalarResult:
    def __init__(self, *, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._scalars


def _candidate(candidate_id: int):
    return SimpleNamespace(
        id=candidate_id,
        name="Anna",
        lastname="Nowak",
        email="anna@example.test",
        phone=None,
        location="Warszawa",
        status=SimpleNamespace(value="active"),
        competence_category="Backend",
        salary_expectation=None,
        salary_currency=None,
        tags=["python"],
        skills=["python", "fastapi"],
        ai_summary="Backend developer",
        avatar_url=None,
    )


@pytest.mark.asyncio
async def test_qdrant_empty_uses_bm25_without_match_score(monkeypatch):
    job = SimpleNamespace(
        id=7,
        title="Python Developer",
        requirements="Python, FastAPI",
        description="Backend services",
        location=None,
    )
    candidate = _candidate(42)
    db = AsyncMock()
    db.execute.side_effect = [
        _ScalarResult(scalar=job),
        _ScalarResult(scalars=[candidate]),
    ]

    semantic = AsyncMock(return_value=[])
    bm25 = AsyncMock(return_value=[42])
    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", semantic
    )
    monkeypatch.setattr(matching, "bm25_candidates", bm25)
    monkeypatch.setattr(matching.settings, "AI_MATCH_POOL_SIZE", 100)
    monkeypatch.setattr(matching.settings, "MATCH_MAX_RESULTS", 20)
    monkeypatch.setattr(matching.settings, "AI_MATCH_MIN_SCORE", 0.25)
    monkeypatch.setattr(matching.settings, "RERANKER_ENABLED", False)

    result = await matching.get_ai_matches(
        job_id=7,
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert [row["candidate"]["id"] for row in result["matches"]] == [42]
    assert result["matches"][0]["match_score"] is None
    assert result["search_type"] == "bm25"
    assert result["min_score"] is None
    assert result["meta"] == {
        "mode": "bm25",
        "degraded": True,
        "reason": "semantic_unavailable",
    }
    semantic.assert_awaited_once()
    bm25.assert_awaited_once()


@pytest.mark.asyncio
async def test_bm25_failure_returns_explicitly_unavailable(monkeypatch):
    job = SimpleNamespace(
        id=7,
        title="Python Developer",
        requirements="Python",
        description=None,
        location=None,
    )
    db = AsyncMock()
    db.execute.return_value = _ScalarResult(scalar=job)

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        matching,
        "bm25_candidates",
        AsyncMock(side_effect=RuntimeError("postgres unavailable")),
    )
    monkeypatch.setattr(matching.settings, "AI_MATCH_POOL_SIZE", 100)
    monkeypatch.setattr(matching.settings, "MATCH_MAX_RESULTS", 20)
    monkeypatch.setattr(matching.settings, "AI_MATCH_MIN_SCORE", 0.25)
    monkeypatch.setattr(matching.settings, "RERANKER_ENABLED", False)

    result = await matching.get_ai_matches(
        job_id=7,
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert result["matches"] == []
    assert result["meta"] == {
        "mode": "unavailable",
        "degraded": True,
        "reason": "semantic_and_bm25_unavailable",
    }


@pytest.mark.asyncio
async def test_cv_preview_bm25_skips_standard_scoring(monkeypatch):
    job = SimpleNamespace(
        id=9,
        title="Python Developer",
        client_id=2,
        location="Warszawa",
        salary_min=18_000,
        salary_max=25_000,
        remote_policy=SimpleNamespace(value="remote"),
        status=SimpleNamespace(value="published"),
        priority=None,
        seniority=None,
        industry="IT",
        deadline=None,
    )
    db = AsyncMock()
    db.execute.return_value = _ScalarResult(scalars=[job])
    scorer = AsyncMock()
    bm25 = AsyncMock(return_value=[9])
    filtered_job = SimpleNamespace(job=job, warning=None)

    monkeypatch.setattr(cv_match_preview, "extract_text", lambda *_a: "Python FastAPI")
    monkeypatch.setattr(
        cv_match_preview,
        "parse_cv",
        AsyncMock(
            return_value={
                "first_name": "Anna",
                "last_name": "Nowak",
                "skills": [{"name": "Python"}],
                "current_position": "Python Developer",
            }
        ),
    )
    monkeypatch.setattr(
        cv_match_preview, "generate_embedding", AsyncMock(return_value=None)
    )
    semantic = AsyncMock()
    monkeypatch.setattr(cv_match_preview, "search_jobs_semantic", semantic)
    monkeypatch.setattr(cv_match_preview, "bm25_jobs", bm25)
    monkeypatch.setattr(
        cv_match_preview,
        "apply_user_filters",
        AsyncMock(return_value=([filtered_job], SimpleNamespace())),
    )
    monkeypatch.setattr(cv_match_preview, "rank_jobs_for_candidate", scorer)
    monkeypatch.setattr(
        "app.services.ai_quota.check_and_increment", AsyncMock(return_value=None)
    )

    upload = UploadFile(filename="anna.txt", file=BytesIO(b"Python FastAPI"))
    endpoint = inspect.unwrap(cv_match_preview.cv_upload_preview)
    result = await endpoint(
        request=SimpleNamespace(),
        file=upload,
        top_k=10,
        threshold=0.0,
        location=None,
        salary_min=None,
        salary_max=None,
        competence_category=None,
        current_user=SimpleNamespace(id=1),
        db=db,
    )

    assert result["matches"] == [
        {
            "job": cv_match_preview._shape_job(job),
            "total_score": None,
            "breakdown": None,
            "warning": None,
        }
    ]
    assert result["meta"] == {
        "mode": "bm25",
        "degraded": True,
        "reason": "semantic_unavailable",
    }
    semantic.assert_not_awaited()
    bm25.assert_awaited_once()
    scorer.assert_not_awaited()
