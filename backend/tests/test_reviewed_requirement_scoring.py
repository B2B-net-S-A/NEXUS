from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.matching_requirements import MatchingRequirements, SkillRequirement
from app.services import requirement_verification as reviews
from app.services.dealbreaker_filters import apply_dealbreakers
from app.services.requirement_contract import (
    evaluate_requirements,
    search_dealbreaker_inputs,
)
from app.services.scoring_service import _score_skills
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["met", "not_met", "unknown"])
async def test_review_drives_or_group_score_and_explicit_gate_without_inventing_skills(
    monkeypatch, status
):
    contract = MatchingRequirements(
        reviewed=True,
        missing_evidence_policy="exclude",
        all_of=[SkillRequirement(any_of=["Python", "Java"])],
    )
    job = make_job(id=7, matching_requirements=contract.model_dump())
    candidate = make_candidate(id=1, skills=["Python"])
    row = SimpleNamespace(
        id=9,
        candidate_id=1,
        group_key=reviews.group_key(contract.all_of[0]),
        requirements_fingerprint=reviews.criteria_fingerprint(contract),
        source_fingerprint=reviews.source_fingerprint(candidate),
        status=status,
        evidence="Test praktyczny",
        usage_context="Backend requestu 7",
        verified_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(reviews, "latest_verifications", AsyncMock(return_value=[row]))
    await reviews.load_verified_requirements(object(), job, [candidate])
    evidence = evaluate_requirements(contract, candidate, job_id=7)[0]
    assert evidence["status"] == status and evidence["evidence_basis"] == "reviewed"
    assert evidence["candidate_evidence"] == "Test praktyczny"
    assert "java" not in evidence["matched"]
    layer, matched, missing, _, _ = _score_skills(candidate, job)
    assert bool(layer.points) == (status == "met")
    assert bool(matched) == (status == "met")
    assert bool(missing) == (status != "met")
    assert bool(
        apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(job)).kept
    ) == (status == "met")
    # Default review policy does not acquire a new silent exclusion rule.
    assert apply_dealbreakers(
        [candidate], inputs=search_dealbreaker_inputs(job, exclude_missing_must=False)
    ).kept == [candidate]
    assert candidate.skills == ["Python"]
    # Same text/criteria in another job cannot borrow this interview verdict.
    assert (
        evaluate_requirements(contract, candidate, job_id=8)[0]["evidence_basis"]
        == "profile_signal"
    )


@pytest.mark.asyncio
async def test_stale_or_superseded_review_does_not_restore_an_old_verdict(monkeypatch):
    contract = MatchingRequirements(
        reviewed=True, all_of=[SkillRequirement(any_of=["Python"])]
    )
    job = make_job(id=7, matching_requirements=contract.model_dump())
    candidate = make_candidate(id=1, skills=["Python"])
    row = SimpleNamespace(
        id=9,
        candidate_id=1,
        group_key=reviews.group_key(contract.all_of[0]),
        requirements_fingerprint=reviews.criteria_fingerprint(contract),
        source_fingerprint=reviews.source_fingerprint(candidate),
        status="not_met",
        evidence="Test",
        usage_context="Backend",
        verified_at=datetime.now(timezone.utc),
    )
    latest = AsyncMock(return_value=[row])
    monkeypatch.setattr(reviews, "latest_verifications", latest)
    await reviews.load_verified_requirements(object(), job, [candidate])
    assert (
        evaluate_requirements(contract, candidate, job_id=7)[0]["status"] == "not_met"
    )
    candidate.skills = ["Python", "Java"]
    await reviews.load_verified_requirements(object(), job, [candidate])
    assert (
        evaluate_requirements(contract, candidate, job_id=7)[0]["evidence_basis"]
        == "profile_signal"
    )
    latest.return_value = []
    await reviews.load_verified_requirements(object(), job, [candidate])
    assert not candidate._reviewed_requirements["groups"]
