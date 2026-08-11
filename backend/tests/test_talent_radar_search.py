"""Talent Radar — ad-hoc role in, ranked candidates out.

The composition is thin; what these tests guard are the constraints that make it
safe, because each of them is a defect this codebase has already shipped once.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services import talent_radar_search as tr
from app.services.talent_radar_search import (
    RadarQuery,
    RadarResult,
    TalentRadarError,
    build_ephemeral_job,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_ephemeral_job_sets_every_attribute_the_scoring_path_reads():
    """A missing attribute would surface as AttributeError mid-search.

    The scoring and embedding paths read these off `job` directly; a
    SimpleNamespace only has what we put on it, so the list is enumerated rather
    than assumed.
    """
    job = build_ephemeral_job(RadarQuery(client_id=7, text="Senior Python"))

    for attr in (
        "id",
        "client_id",
        "title",
        "description",
        "requirements",
        "champion_profile",
        "must_skills",
        "nice_skills",
        "location",
        "remote_policy",
        "salary_min",
        "salary_max",
        "deadline",
        "seniority",
        "subcategory",
        "industry",
        "embedding_id",
    ):
        assert hasattr(job, attr), f"scoring reads job.{attr} — it must exist"


def test_ephemeral_job_has_no_id_so_it_cannot_touch_pipeline_history():
    """`id=None` is load-bearing, not a placeholder.

    `build_job_scoring_context` filters `CandidateStage.job_id == job.id`; a real
    id would pull another job's screening answers into an unrelated search.
    """
    job = build_ephemeral_job(RadarQuery(client_id=7, text="x"))
    assert job.id is None


def test_client_is_carried_onto_the_job_or_conflicts_cannot_be_checked():
    job = build_ephemeral_job(RadarQuery(client_id=42, text="x"))
    assert job.client_id == 42, (
        "the eligibility filter reads client_id — losing it here would silently "
        "skip NDA, competitor and veto checks"
    )


@pytest.mark.asyncio
async def test_empty_query_is_refused_before_any_paid_call():
    class _DB:
        async def scalar(self, *_a, **_k):  # pragma: no cover - must not be reached
            raise AssertionError("no DB work before the input is validated")

    with pytest.raises(TalentRadarError):
        await tr.search(_DB(), RadarQuery(client_id=1))


@pytest.mark.asyncio
async def test_unknown_client_is_refused_rather_than_searched_unfiltered():
    """The whole point of the mandatory client.

    Answering without one would produce a list whose NDA / competitor / veto
    checks silently passed — the `/ai-matches` defect, rebuilt on a new surface.
    """

    class _DB:
        async def scalar(self, *_a, **_k):
            return None  # no such client

    with pytest.raises(TalentRadarError) as exc:
        await tr.search(_DB(), RadarQuery(client_id=999, text="Senior Python"))

    assert "klienta" in str(exc.value).lower()


def test_degraded_retrieval_is_reported_not_rendered_as_no_matches():
    result = RadarResult(
        breakdowns=[], pool_size=0, eligible_size=0, degraded=True, reason="x"
    )
    meta = result.as_meta()
    assert meta["degraded"] is True, (
        "an empty list from a broken provider must be distinguishable from "
        "'we have nobody like that'"
    )


def _calls_in(module_rel: str, func_name: str) -> set[str]:
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == func_name
    )
    return {
        n.func.id
        for n in ast.walk(target)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_search_enforces_eligibility():
    assert "filter_eligible_candidates" in _calls_in(
        "app/services/talent_radar_search.py", "search"
    ), "Talent Radar would surface candidates the recruiter cannot assign"


def test_search_does_not_write_the_score_cache():
    """The cache key is (candidate, job, profile) and this job has no id.

    Using `bulk_get_or_compute` here would either collide across unrelated
    ad-hoc searches or write rows keyed on a null job.
    """
    calls = _calls_in("app/services/talent_radar_search.py", "search")
    assert "rank_candidates_for_job" in calls
    assert "bulk_get_or_compute" not in calls


def test_module_makes_no_llm_call():
    """One Voyage query embedding, nothing else — so the module is free to use.

    Implicit must-skills come from `_score_skills`' existing JD/Champion
    fallback, which is why no parse step is needed.
    """
    src = (BACKEND / "app/services/talent_radar_search.py").read_text(encoding="utf-8")
    for forbidden in ("parse_cv", "call_claude", "ai_feature"):
        assert forbidden not in src, (
            f"{forbidden} would add per-search spend and a quota gate to a "
            "module that currently needs neither"
        )
