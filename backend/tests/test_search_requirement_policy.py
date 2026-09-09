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


@pytest.mark.parametrize("skills", [[], ["Rust"]])
def test_review_keeps_missing_proof_without_changing_evidence(skills):
    target = job()
    candidate = SimpleNamespace(skills=skills)
    result = apply_dealbreakers([candidate], inputs=search_dealbreaker_inputs(target))
    assert result.kept == [candidate]
    assert result.hidden_missing_must == 0
    assert (
        evaluate_requirements(requirements_for_job(target), candidate)[0]["status"]
        == "unknown"
    )


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
