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
