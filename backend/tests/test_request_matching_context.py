from dataclasses import replace

import pytest

from app.services import scoring_service as scoring
from app.services.request_matching_context import build_request_context
from tests.test_scoring_service import make_candidate, make_job


def test_full_request_tail_is_preserved_and_changes_fingerprint():
    target = make_job(
        description="Administrative introduction. " * 500 + "Required: Django"
    )
    context = build_request_context(target, scoring.DEFAULT_PROFILE)
    assert "Required: Django" in context.query_text
    assert context.as_job().skill_scan_cap is None
    target.description += " Optional: Kubernetes"
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != context.fingerprint
    )


def test_fingerprint_includes_criteria_weights_and_client_context():
    target = make_job(client_id=12)
    original = build_request_context(target, scoring.DEFAULT_PROFILE)
    target.hiring_manager_contact_id = 88
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )
    target.hiring_manager_contact_id = None
    changed_weights = replace(scoring.DEFAULT_PROFILE, skills=20)
    assert (
        build_request_context(target, changed_weights).fingerprint
        != original.fingerprint
    )
    target.matching_requirements = {"reviewed": True, "all_of": []}
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )


def test_empty_brief_is_explicitly_preliminary():
    context = build_request_context(make_job(), scoring.DEFAULT_PROFILE)
    assert context.brief_status == "title_only"
    assert context.weights["champion_fit"] == 0
    assert sum(
        context.weights[name]
        for name in ("semantic", "skills", "salary", "location", "availability")
    ) == pytest.approx(100)


def test_workflow_updates_do_not_invalidate_or_enrich_base_fit_context():
    target = make_job(updated_at="yesterday")
    original = build_request_context(target, scoring.DEFAULT_PROFILE)
    target.updated_at = "today"
    target.champion_profile = {
        "verification": {"status": "approved"},
        "recommended_searches": [{"query": "Java"}],
    }
    changed = build_request_context(target, scoring.DEFAULT_PROFILE)
    assert changed.fingerprint == original.fingerprint
    assert changed.query_text == original.query_text
    assert changed.brief_status == "title_only"
    target.champion_profile["stack"] = {"must": ["Django"]}
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )


@pytest.mark.asyncio
async def test_same_base_fit_is_independent_of_screening_and_conflicts():
    target = make_job(must_skills=["Python"])
    candidate = make_candidate(skills=["Python"])
    request = build_request_context(target, scoring.DEFAULT_PROFILE)
    empty = scoring.JobScoringContext({}, frozenset())
    process = scoring.JobScoringContext(
        {candidate.id: {"overall_fit": "bad"}}, frozenset({candidate.id})
    )
    one = await scoring.score_candidate_job(
        candidate,
        request.as_job(),
        None,
        semantic_similarity=0.8,
        profile=request.profile(),
        context=empty,
        base_fit=True,
    )
    two = await scoring.score_candidate_job(
        candidate,
        request.as_job(),
        None,
        semantic_similarity=0.8,
        profile=request.profile(),
        context=process,
        base_fit=True,
    )
    assert one.total == two.total
    assert one.penalties == two.penalties == []
    assert one.champion_fit.points == 0
