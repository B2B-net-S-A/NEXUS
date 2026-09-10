from types import SimpleNamespace

import pytest

from app.services.dealbreaker_filters import apply_dealbreakers
from app.services.requirement_contract import (
    evaluate_requirements,
    requirements_for_job,
    search_dealbreaker_inputs,
)


def job(policy="review"):
    return SimpleNamespace(
        matching_requirements={
            "reviewed": True,
            "missing_evidence_policy": policy,
            "all_of": [{"any_of": ["Python", "Java"], "level": "must"}],
        },
        requirements_reviewed=True,
        rate_budget_hourly=100,
    )


def test_review_keeps_missing_proof_without_changing_evidence():
    """No skill data is not proof of inability: it stays for review."""
    target = job()
    candidate = SimpleNamespace(skills=[])
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(target))
    assert result.kept == [candidate]
    assert result.hidden_missing_must == 0
    assert (
        evaluate_requirements(requirements_for_job(target), candidate)[0]["status"]
        == "unknown"
    )


def test_review_hides_a_known_technology_gap_by_default():
    """Decision 10.09: known skills without the must-have technology hide."""
    candidate = SimpleNamespace(skills=["Rust"])
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(job()))
    assert result.kept == []
    assert result.hidden_missing_must == 1


def test_default_job_without_saved_contract_gates_on_its_technology_column():
    """The pre-#1428 default: the plain `must_skills` column gates again."""
    target = SimpleNamespace(must_skills=[{"name": "Python"}])
    inputs = search_dealbreaker_inputs(target)
    assert inputs.must_skills and not inputs.exclude_unknown_skill_evidence
    known_gap = SimpleNamespace(id=1, skills=["Java"])
    no_data = SimpleNamespace(id=2, skills=[])
    fits = SimpleNamespace(id=3, skills=["Python"])
    result = apply_dealbreakers([known_gap, no_data, fits], inputs=inputs)
    assert [c.id for c in result.kept] == [2, 3]


@pytest.mark.parametrize("policy", ["review", "exclude"])
def test_prose_must_have_never_hides_anyone(policy):
    """Prose requirements are signals, never a gate (regression of 08.09)."""
    target = SimpleNamespace(
        matching_requirements={
            "reviewed": True,
            "missing_evidence_policy": policy,
            "all_of": [
                {
                    "any_of": ["apache kafka – minimum 4 lata doświadczenia"],
                    "level": "must",
                }
            ],
        },
        requirements_reviewed=True,
    )
    inputs = search_dealbreaker_inputs(target)
    assert inputs.must_skills == ()
    assert inputs.must_skills_ignored
    candidates = [SimpleNamespace(skills=["Rust"]), SimpleNamespace(skills=[])]
    assert apply_dealbreakers(candidates, inputs=inputs).kept == candidates


def test_kill_switch_disables_the_default_must_gate(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUBRIC_DEALBREAKERS_ENABLED", False)
    candidate = SimpleNamespace(skills=["Rust"])
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(job()))
    assert result.kept == [candidate]
    assert result.hidden_missing_must == 0


def test_policy_semantics_are_part_of_every_request_fingerprint(monkeypatch):
    """A ranking stored under an older gate policy never reads as current."""
    from app.services import requirement_contract
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import DEFAULT_PROFILE
    from tests.test_scoring_service import make_job

    before = build_request_context(make_job(must_skills=["Python"]), DEFAULT_PROFILE)
    assert (
        before.versions["must_gate_policy"]
        == requirement_contract.MUST_GATE_POLICY_VERSION
    )
    monkeypatch.setattr(requirement_contract, "MUST_GATE_POLICY_VERSION", "next")
    after = build_request_context(make_job(must_skills=["Python"]), DEFAULT_PROFILE)
    assert after.fingerprint != before.fingerprint


@pytest.mark.parametrize(
    "skills, kept", [([], False), (["Rust"], False), (["Java"], True)]
)
def test_explicit_exclusion_includes_empty_evidence_and_respects_or(skills, kept):
    target = job("exclude")
    candidate = SimpleNamespace(skills=skills)
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(target))
    assert bool(result.kept) is kept
    assert result.hidden_missing_must == int(not kept)


@pytest.mark.parametrize(
    "policy, override, kept", [("exclude", False, True), ("review", True, False)]
)
def test_explicit_per_request_filter_overrides_saved_default(policy, override, kept):
    result = apply_dealbreakers(
        [SimpleNamespace(skills=[])],
        inputs=search_dealbreaker_inputs(job(policy), exclude_missing_must=override),
    )
    assert bool(result.kept) is kept


def test_review_does_not_disable_known_budget_exclusion():
    candidate = SimpleNamespace(
        skills=[], expected_rate_hourly=120, expected_rate_currency="PLN"
    )
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(job()))
    assert not result.kept
    assert result.hidden_over_budget == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exclude_over_budget", [True, False])
async def test_shared_visibility_preserves_block_reason_and_filter_override(
    monkeypatch, exclude_over_budget
):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from app.api import matching
    from app.services.candidate_job_eligibility import (
        EligibilityInput,
        evaluate_eligibility,
    )

    now = datetime.now(timezone.utc)
    candidates = [
        SimpleNamespace(
            id=i,
            skills=["Python"],
            expected_rate_hourly=150,
            expected_rate_currency="PLN",
        )
        for i in [1, 2, 3]
    ]
    decisions = {
        1: evaluate_eligibility(
            EligibilityInput(
                candidate_status="active", rejected_by_hiring_manager=True
            ),
            now=now,
        ),
        2: evaluate_eligibility(
            EligibilityInput(candidate_status="blacklisted"), now=now
        ),
        3: evaluate_eligibility(EligibilityInput(candidate_status="active"), now=now),
    }
    monkeypatch.setattr(
        matching, "evaluate_candidates_for_job", AsyncMock(return_value=decisions)
    )
    (
        kept,
        annotations,
        hidden,
        eligibility_filtered,
        _,
    ) = await matching._gate_and_dealbreakers(
        None,
        job=job(),
        ordered=candidates,
        now=now,
        inputs=search_dealbreaker_inputs(job()),
        exclude_over_budget=exclude_over_budget,
    )
    assert [c.id for c in kept] == ([1] if exclude_over_budget else [1, 3])
    assert annotations[1]["assignment_allowed"] is False
    assert annotations[1]["reason"] == decisions[1].reason
    assert eligibility_filtered == 1
    assert hidden["over_budget"] == int(exclude_over_budget)


def test_profile_update_and_extracted_gap_are_not_verified_competence_evidence():
    candidate = SimpleNamespace(
        skills=["Python"],
        updated_at="2026-09-09",
        cv_extracted_data={
            "_notes_insights": {
                "skills_gaps_observed": [{"name": "Java", "evidence": "AI paraphrase"}],
                "_extracted_at": "2026-09-09",
            }
        },
    )
    target = job()
    target.matching_requirements["all_of"] = [
        {"any_of": ["Python"], "level": "must"},
        {"any_of": ["Java"], "level": "must"},
    ]
    evidence = evaluate_requirements(requirements_for_job(target), candidate)
    assert [item["status"] for item in evidence] == ["met", "unknown"]
    assert [item["evidence_basis"] for item in evidence] == [
        "profile_signal",
        "no_evidence",
    ]
    assert all(
        item["verified_at"] is None and item["usage_context"] is None
        for item in evidence
    )
