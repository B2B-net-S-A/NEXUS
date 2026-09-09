from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.job import JobUpdate
from app.schemas.matching_requirements import MatchingRequirements, SkillRequirement
from app.services.requirement_contract import evaluate_requirements, explicit_contract
from app.services import scoring_service as scoring
from app.services.dealbreaker_filters import (
    gate_eligible_must_skills,
    missing_must_skills,
)


def job(contract):
    return SimpleNamespace(
        matching_requirements=contract.model_dump(),
        must_skills=["old"],
        nice_skills=[],
        requirements_reviewed=True,
    )


def candidate(*skills):
    return SimpleNamespace(skills=list(skills))


@pytest.mark.parametrize(
    "text", ["Python lub Java", "Python or Java", "Python albo Java"]
)
def test_alternative_means_one_required_group_in_score_and_gate(text):
    contract = explicit_contract([text, "SQL"], [], reviewed=True)
    target = job(contract)
    cand = candidate("python", "sql")
    requirements = scoring.job_skill_requirements(target)["must"]
    assert requirements == ["python lub java", "sql"]
    assert gate_eligible_must_skills(requirements) == requirements
    assert missing_must_skills(cand, requirements) == []
    _, matched, missing, _, _ = scoring._score_skills(cand, target)
    assert matched == requirements and missing == []


def test_all_groups_required_and_missing_evidence_is_not_proven_failure():
    contract = explicit_contract(["Python", "Django"], [], reviewed=True)
    result = evaluate_requirements(contract, candidate("Python"))
    assert [r["status"] for r in result] == ["met", "unknown"]
    assert contract.missing_evidence_policy == "review"


def test_reviewed_empty_contract_does_not_restore_old_skills():
    target = job(MatchingRequirements(reviewed=True))
    assert scoring.job_skill_requirements(target)["must"] == []
    assert scoring.job_explicit_must_skills(target) == []
    assert (
        JobUpdate.model_validate(
            {"matching_requirements": {"reviewed": True, "all_of": []}}
        ).model_dump(exclude_unset=True)["matching_requirements"]["all_of"]
        == []
    )


def test_unreviewed_contract_does_not_create_a_hard_gate():
    target = job(explicit_contract(["Python"], []))
    assert scoring.job_explicit_must_skills(target) == []


def test_nice_and_excluded_do_not_become_must():
    contract = MatchingRequirements(
        all_of=[
            SkillRequirement(any_of=["python"], level="must"),
            SkillRequirement(any_of=["java"], level="excluded"),
            SkillRequirement(any_of=["kubernetes"], level="nice"),
        ]
    )
    result = scoring.job_skill_requirements(job(contract))
    assert result["must"] == ["python"]
    assert result["nice"] == ["kubernetes"]
    assert result["excluded"] == ["java"]


def test_malformed_contract_is_rejected_not_silently_ignored():
    with pytest.raises(ValidationError):
        MatchingRequirements(all_of=[{"any_of": []}])


@pytest.mark.parametrize(
    "text", ["Wymagane: Python lub Java", "Required: Python or Java"]
)
def test_prose_alternatives_are_not_two_must_haves(monkeypatch, text):
    import re
    from app.services.requirement_modality import classify_requirements

    result = classify_requirements(
        text,
        re.compile(r"\b(python|java)\b", re.I),
        {"python": "python", "java": "java"},
    )
    assert result["must"] == ["python lub java"]


def test_multiple_alternatives_keep_both_groups():
    import re
    from app.services.requirement_modality import classify_requirements

    aliases = {name: name for name in ("python", "java", "go")}
    result = classify_requirements(
        "Required: Python or Java; Required: Python or Go",
        re.compile(r"\b(python|java|go)\b", re.I),
        aliases,
    )
    assert result["must"] == ["python lub go", "python lub java"]


@pytest.mark.asyncio
@pytest.mark.parametrize("policy,expected_ids", [("review", [1, 2]), ("exclude", [1])])
async def test_shared_gate_respects_review_policy_for_missing_proof(
    monkeypatch, policy, expected_ids
):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from app.api.matching import _gate_and_dealbreakers
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.candidate_job_eligibility import (
        EligibilityInput,
        evaluate_eligibility,
    )
    from tests.test_scoring_service import make_job, make_candidate

    contract = explicit_contract(["Python lub Java"], [], reviewed=True)
    contract.missing_evidence_policy = policy
    target = make_job(
        id=7, matching_requirements=contract.model_dump(), requirements_reviewed=True
    )
    candidates = [
        make_candidate(id=1, skills=["java"]),
        make_candidate(id=2, skills=[]),
    ]
    now = datetime.now(timezone.utc)
    clean = evaluate_eligibility(EligibilityInput(candidate_status="active"), now=now)
    monkeypatch.setattr(
        "app.api.matching.evaluate_candidates_for_job",
        AsyncMock(return_value={1: clean, 2: clean}),
    )
    kept, _, hidden, _, inputs = await _gate_and_dealbreakers(
        None,
        job=target,
        ordered=candidates,
        now=now,
        inputs=search_dealbreaker_inputs(target),
    )
    assert [c.id for c in kept] == expected_ids
    assert inputs.verification_job_id == 7
    assert inputs.verification_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_value", ["absent", "null"])
async def test_shared_gate_rejects_incomplete_eligibility_decisions(
    monkeypatch, missing_value
):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from app.api.matching import _gate_and_dealbreakers
    from app.services.candidate_job_eligibility import (
        EligibilityInput,
        evaluate_eligibility,
    )
    from tests.test_scoring_service import make_job, make_candidate

    now = datetime.now(timezone.utc)
    decisions = {
        1: evaluate_eligibility(EligibilityInput(candidate_status="active"), now=now)
    }
    if missing_value == "null":
        decisions[2] = None
    monkeypatch.setattr(
        "app.api.matching.evaluate_candidates_for_job",
        AsyncMock(return_value=decisions),
    )
    with pytest.raises(
        RuntimeError, match="Incomplete candidate eligibility assessment"
    ):
        await _gate_and_dealbreakers(
            None,
            job=make_job(),
            ordered=[make_candidate(id=1), make_candidate(id=2)],
            now=now,
        )


def test_legacy_query_preserves_request_tail_and_reviewed_alternatives():
    from app.api.matching import _build_job_query
    from tests.test_scoring_service import make_job

    contract = explicit_contract(["Python lub Java"], ["Kubernetes"], reviewed=True)
    target = make_job(
        title="Backend Developer",
        description="Wprowadzenie " * 500 + "Projekt rozliczeń w Django",
        requirements="Informacje " * 500 + "Wymagane doświadczenie z PostgreSQL",
        matching_requirements=contract.model_dump(),
        requirements_reviewed=True,
    )
    query = _build_job_query(target)
    assert "Projekt rozliczeń w Django" in query
    assert "Wymagane doświadczenie z PostgreSQL" in query
    assert "python lub java" in query.lower()
    assert "kubernetes" in query.lower()
    target.description += " Dodatkowo RabbitMQ"
    assert _build_job_query(target) != query
    assert "RabbitMQ" in _build_job_query(target)
