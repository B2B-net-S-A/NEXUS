"""Focused unit tests for Priority Lock decisions (no database required)."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.recruitment_priority import (
    PriorityChannel,
    PriorityMemberStatus,
    PriorityMode,
    PriorityOriginKind,
)
from app.services import priority_work_policy as policy


@pytest.mark.parametrize(
    ("global_mode", "user_mode", "expected"),
    [
        ("off", None, PriorityMode.off),
        ("shadow", None, PriorityMode.shadow),
        ("enforce", None, PriorityMode.enforce),
        ("enforce", "shadow", PriorityMode.shadow),
        ("enforce", "off", PriorityMode.off),
        ("shadow", "enforce", PriorityMode.shadow),
    ],
)
def test_effective_mode_never_exceeds_global(
    global_mode: str, user_mode: str | None, expected: PriorityMode
) -> None:
    assert policy.combine_priority_modes(global_mode, user_mode) is expected


def test_policy_assertion_boundary_has_an_explicit_typed_signature() -> None:
    signature = inspect.signature(policy.assert_priority_work_access)
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    assert {
        "candidate_id",
        "job_id",
        "actor_user_id",
        "origin_kind",
        "action",
        "continuation_exists",
        "consume_exception",
        "require_existing",
        "frozen_origin_assignment_id",
        "frozen_priority_compliant",
        "work_channel",
        "job_is_open",
    } <= signature.parameters.keys()


async def test_assignment_progress_requires_verified_before_cv_sent_in_same_attempt() -> (
    None
):
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(assignment_id=77, verifications=2, recommendations=1)
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    counts = await policy.assignment_milestone_counts(db, [77, 77])

    assert counts == {77: {"verifications": 2, "recommendations": 1}}
    statement, params = db.execute.await_args.args
    sql = " ".join(str(statement).lower().split())
    assert "with process_windows as" in sql
    assert "lead(rp.opened_at) over" in sql
    assert "from classified_process cp" in sql
    assert "join classified_mf verified" in sql
    assert "verified.process_id = cp.id" in sql
    assert "verified.stage = 'verified'" in sql
    assert "left join classified_mf recommendation" in sql
    assert "recommendation.process_id = cp.id" in sql
    assert "recommendation.stage = 'cv_sent'" in sql
    assert "recommendation.reached_at >= verified.reached_at" in sql
    assert "cp.kpi_eligible is true" in sql
    assert params == {"assignment_ids": [77]}


async def test_existing_pair_is_always_continuation(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=True,
    )
    assert decision.allowed is True
    assert decision.is_continuation is True
    assert decision.reason is policy.PriorityWorkReason.continuation


async def test_shadow_records_missing_assignment_without_blocking(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.shadow)
    )
    monkeypatch.setattr(
        policy, "_current_assignment", AsyncMock(return_value=(None, None, None))
    )
    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        consume_exception=False,
        work_channel=PriorityChannel.database,
    )
    assert decision.allowed is True
    assert decision.violation is True
    assert decision.priority_compliant is False
    assert decision.kpi_eligible is True
    assert decision.reason is policy.PriorityWorkReason.shadow_no_assignment


async def test_enforce_missing_assignment_returns_structured_lock(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    monkeypatch.setattr(
        policy, "_current_assignment", AsyncMock(return_value=(None, None, None))
    )
    with pytest.raises(policy.PriorityWorkLocked) as caught:
        await policy.assert_priority_work_access(
            AsyncMock(),
            candidate_id=11,
            job_id=22,
            actor_user_id=33,
            continuation_exists=False,
            consume_exception=False,
            work_channel=PriorityChannel.database,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "PRIORITY_WORK_LOCKED"
    assert caught.value.detail["reason"] == "JOB_NOT_ASSIGNED"
    assert caught.value.detail["candidate_id"] == 11
    assert caught.value.detail["job_id"] == 22


async def test_one_shot_exception_allows_work_but_disables_kpi(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    monkeypatch.setattr(
        policy, "_current_assignment", AsyncMock(return_value=(None, None, None))
    )
    monkeypatch.setattr(
        policy,
        "_consume_exception",
        AsyncMock(return_value=SimpleNamespace(id=9, origin_assignment_id=None)),
    )
    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        work_channel=PriorityChannel.database,
    )
    assert decision.allowed is True
    assert decision.exception_id == 9
    assert decision.kpi_eligible is False
    assert decision.reason is policy.PriorityWorkReason.approved_exception


async def test_external_inbound_is_accepted_without_granting_kpi(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    monkeypatch.setattr(
        policy, "_current_assignment", AsyncMock(return_value=(None, None, None))
    )
    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        origin_kind=PriorityOriginKind.external_inbound,
        continuation_exists=False,
    )
    assert decision.allowed is True
    assert decision.kpi_eligible is None
    assert decision.reason is policy.PriorityWorkReason.external_inbound


async def test_enforce_rejects_cross_channel_sourcing(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    assignment = SimpleNamespace(
        id=77,
        channel=PriorityChannel.database,
        verification_target=4,
    )
    member = SimpleNamespace(id=7, user_id=33, status=PriorityMemberStatus.active)
    plan = SimpleNamespace(id=9)
    monkeypatch.setattr(
        policy,
        "_current_assignment",
        AsyncMock(return_value=(assignment, member, plan)),
    )
    monkeypatch.setattr(policy, "_consume_exception", AsyncMock(return_value=None))

    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        work_channel=PriorityChannel.linkedin,
    )

    assert decision.allowed is False
    assert decision.reason is policy.PriorityWorkReason.channel_not_assigned
    assert decision.assignment_id == 77


async def test_mixed_tac_assignment_accepts_database_and_linkedin(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    assignment = SimpleNamespace(
        id=77,
        channel=PriorityChannel.mixed,
        verification_target=4,
    )
    member = SimpleNamespace(id=7, user_id=33, status=PriorityMemberStatus.active)
    plan = SimpleNamespace(id=9)
    monkeypatch.setattr(
        policy,
        "_current_assignment",
        AsyncMock(return_value=(assignment, member, plan)),
    )
    monkeypatch.setattr(
        policy, "_accepted_verification_count", AsyncMock(return_value=0)
    )

    for channel in (PriorityChannel.database, PriorityChannel.linkedin):
        decision = await policy.decide_priority_work_access(
            AsyncMock(),
            candidate_id=11,
            job_id=22,
            actor_user_id=33,
            continuation_exists=False,
            work_channel=channel,
        )
        assert decision.allowed is True
        assert decision.reason is policy.PriorityWorkReason.assigned


async def test_closed_job_blocks_new_work_but_not_carry_over(monkeypatch) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )

    blocked = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        work_channel=PriorityChannel.database,
        job_is_open=False,
        consume_exception=False,
    )
    carry = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=True,
        work_channel=PriorityChannel.database,
        job_is_open=False,
        consume_exception=False,
    )

    assert blocked.allowed is False
    assert blocked.reason is policy.PriorityWorkReason.job_not_open
    assert carry.allowed is True
    assert carry.reason is policy.PriorityWorkReason.continuation


async def test_invite_inbound_preserves_frozen_assignment_after_supersede(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    assignment = SimpleNamespace(id=77)
    member = SimpleNamespace(user_id=33)
    superseded_plan = SimpleNamespace(id=9)
    result = MagicMock()
    result.first.return_value = (assignment, member, superseded_plan)
    db = AsyncMock()
    db.execute.return_value = result

    decision = await policy.decide_priority_work_access(
        db,
        candidate_id=11,
        job_id=22,
        actor_user_id=44,
        origin_kind=PriorityOriginKind.external_inbound,
        continuation_exists=False,
        frozen_origin_assignment_id=77,
    )

    assert decision.allowed is True
    assert decision.assignment_id == 77
    assert decision.assignment_owner_user_id == 33
    assert decision.active_plan_id == 9
    assert decision.priority_compliant is True
    assert decision.kpi_eligible is None


async def test_shadow_invite_violation_cannot_become_compliant_at_apply(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        policy, "effective_priority_mode", AsyncMock(return_value=PriorityMode.enforce)
    )
    current_assignment = AsyncMock()
    monkeypatch.setattr(policy, "_current_assignment", current_assignment)
    assignment = SimpleNamespace(id=77)
    member = SimpleNamespace(user_id=33)
    old_plan = SimpleNamespace(id=9)
    result = MagicMock()
    result.first.return_value = (assignment, member, old_plan)
    db = AsyncMock()
    db.execute.return_value = result

    decision = await policy.decide_priority_work_access(
        db,
        candidate_id=11,
        job_id=22,
        actor_user_id=44,
        origin_kind=PriorityOriginKind.external_inbound,
        continuation_exists=False,
        frozen_origin_assignment_id=77,
        frozen_priority_compliant=False,
    )

    assert decision.allowed is True
    assert decision.assignment_id == 77
    assert decision.assignment_owner_user_id == 33
    assert decision.priority_compliant is False
    assert decision.kpi_eligible is None
    current_assignment.assert_not_awaited()


async def test_lower_rank_is_blocked_when_higher_rank_misses_either_target(
    monkeypatch,
) -> None:
    current = SimpleNamespace(id=2, rank=SimpleNamespace(value="B"))
    higher = SimpleNamespace(
        id=1,
        rank=SimpleNamespace(value="A"),
        verification_target=4,
        recommendation_target=2,
    )
    member = SimpleNamespace(id=7, status=PriorityMemberStatus.active)
    siblings = MagicMock()
    siblings.scalars.return_value.all.return_value = [higher, current]
    blockers = MagicMock()
    blockers.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [siblings, blockers]
    milestone_counts = AsyncMock(
        return_value={1: {"verifications": 4, "recommendations": 1}}
    )
    monkeypatch.setattr(policy, "assignment_milestone_counts", milestone_counts)

    assert (
        await policy._higher_rank_is_behind(db, assignment=current, member=member)
        is True
    )
    milestone_counts.assert_awaited_once_with(db, [1])
    assert db.execute.await_count == 2


async def test_accepted_blocker_releases_lagging_higher_rank(monkeypatch) -> None:
    current = SimpleNamespace(id=2, rank=SimpleNamespace(value="B"))
    higher = SimpleNamespace(
        id=1,
        rank=SimpleNamespace(value="A"),
        verification_target=4,
        recommendation_target=2,
    )
    member = SimpleNamespace(id=7, status=PriorityMemberStatus.active)
    siblings = MagicMock()
    siblings.scalars.return_value.all.return_value = [higher, current]
    blockers = MagicMock()
    blockers.scalars.return_value.all.return_value = [1]
    db = AsyncMock()
    db.execute.side_effect = [siblings, blockers]
    monkeypatch.setattr(
        policy,
        "assignment_milestone_counts",
        AsyncMock(return_value={1: {"verifications": 0, "recommendations": 0}}),
    )

    assert (
        await policy._higher_rank_is_behind(db, assignment=current, member=member)
        is False
    )
    assert db.execute.await_count == 2
