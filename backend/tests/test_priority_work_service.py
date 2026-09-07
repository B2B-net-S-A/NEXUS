"""Focused domain tests for Priority Lock planning and carry-over gates."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.recruitment_priority import (
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityDemandStatus,
    PriorityMemberStatus,
    PriorityRank,
)
from app.models.user import UserRole
from app.schemas.priority_work import (
    PriorityAssignmentInput,
    PriorityPlanMemberInput,
)
from app.services import priority_work_service as priority_service
from app.services.priority_work_service import (
    _assert_demand_coverage,
    _assert_publish_lineage,
    _carry_over_urgency,
    _published_demand_status,
    _validate_member_inputs,
    allowed_channels,
    assert_demand_status_transition,
    assignment_gate_states,
    review_due_after_business_days,
)


TARGETS_BY_COUNT = {
    2: [8, 4],
    3: [6, 4, 2],
    4: [5, 4, 2, 1],
    5: [4, 3, 2, 2, 1],
}


def _assignment(index: int, count: int) -> PriorityAssignmentInput:
    rank = list(PriorityRank)[index]
    return PriorityAssignmentInput(
        demand_id=100 + index,
        job_id=200 + index,
        rank=rank,
        channel=PriorityChannel.linkedin,
        verification_target=TARGETS_BY_COUNT[count][index],
        recommendation_target=1,
        competence_matches=True,
        extra_slot_reason=(
            "HoR zwiększył liczbę requestów"
            if rank in {PriorityRank.D, PriorityRank.E}
            else None
        ),
    )


def _member(count: int) -> PriorityPlanMemberInput:
    return PriorityPlanMemberInput(
        user_id=7,
        verification_capacity=12,
        assignments=[_assignment(index, count) for index in range(count)],
    )


class _Rows:
    def __init__(self, values: list[object]):
        self._values = values

    def scalars(self) -> "_Rows":
        return self

    def all(self) -> list[object]:
        return self._values


def _validation_db(member: PriorityPlanMemberInput) -> SimpleNamespace:
    user = SimpleNamespace(
        id=member.user_id,
        name="Recruiter",
        role=UserRole.recruiter,
        roles=[],
        is_active=True,
    )
    jobs = [
        SimpleNamespace(id=item.job_id, competence_category_id=55)
        for item in member.assignments
    ]
    demands = [
        SimpleNamespace(
            id=item.demand_id,
            job_id=item.job_id,
            status=PriorityDemandStatus.open,
        )
        for item in member.assignments
    ]
    return SimpleNamespace(
        scalar=AsyncMock(return_value=user),
        execute=AsyncMock(
            side_effect=[
                _Rows(jobs),
                _Rows(demands),
                _Rows([55]),
                _Rows([]),
            ]
        ),
    )


def test_review_due_skips_weekend_and_preserves_warsaw_wall_clock() -> None:
    # Friday 10:30 Warsaw (CET) -> Wednesday 10:30 Warsaw (CEST).
    started = datetime(2026, 3, 27, 9, 30, tzinfo=timezone.utc)
    assert review_due_after_business_days(started) == datetime(
        2026, 4, 1, 8, 30, tzinfo=timezone.utc
    )


def test_review_due_skips_polish_weekday_holiday() -> None:
    # Wednesday 10:30 Warsaw + 3 business days skips 1 May and the weekend.
    started = datetime(2026, 4, 29, 8, 30, tzinfo=timezone.utc)
    assert review_due_after_business_days(started) == datetime(
        2026, 5, 5, 8, 30, tzinfo=timezone.utc
    )


def test_zero_business_days_keeps_the_same_instant() -> None:
    started = datetime(2026, 7, 27, 8, 15, tzinfo=timezone.utc)
    assert review_due_after_business_days(started, business_days=0) == started


def test_published_plan_reopens_demands_that_lost_coverage() -> None:
    assert (
        _published_demand_status(
            PriorityDemandStatus.covered,
            included_in_plan=False,
        )
        == PriorityDemandStatus.open
    )
    assert (
        _published_demand_status(
            PriorityDemandStatus.open,
            included_in_plan=True,
        )
        == PriorityDemandStatus.covered
    )
    assert (
        _published_demand_status(
            PriorityDemandStatus.paused,
            included_in_plan=False,
        )
        == PriorityDemandStatus.paused
    )


@pytest.mark.parametrize(
    ("current", "target", "actor_is_hor"),
    [
        (PriorityDemandStatus.open, PriorityDemandStatus.paused, False),
        (PriorityDemandStatus.covered, PriorityDemandStatus.cancelled, False),
        (PriorityDemandStatus.paused, PriorityDemandStatus.open, False),
        (PriorityDemandStatus.open, PriorityDemandStatus.fulfilled, True),
        (PriorityDemandStatus.covered, PriorityDemandStatus.fulfilled, True),
    ],
)
def test_manual_demand_status_transition_matrix_allows_defined_paths(
    current: PriorityDemandStatus,
    target: PriorityDemandStatus,
    actor_is_hor: bool,
) -> None:
    assert_demand_status_transition(
        current,
        target,
        actor_is_hor=actor_is_hor,
    )


@pytest.mark.parametrize(
    ("current", "target", "actor_is_hor"),
    [
        (PriorityDemandStatus.open, PriorityDemandStatus.covered, True),
        (PriorityDemandStatus.open, PriorityDemandStatus.fulfilled, False),
        (PriorityDemandStatus.cancelled, PriorityDemandStatus.open, True),
        (PriorityDemandStatus.fulfilled, PriorityDemandStatus.open, True),
    ],
)
def test_manual_demand_status_transition_matrix_rejects_bypasses(
    current: PriorityDemandStatus,
    target: PriorityDemandStatus,
    actor_is_hor: bool,
) -> None:
    with pytest.raises(HTTPException) as caught:
        assert_demand_status_transition(
            current,
            target,
            actor_is_hor=actor_is_hor,
        )
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "PRIORITY_DEMAND_TRANSITION_INVALID"


def test_publish_lineage_rejects_second_sibling_draft() -> None:
    first = SimpleNamespace(previous_plan_id=10)
    state_before = SimpleNamespace(current_plan_id=10)
    _assert_publish_lineage(first, state_before)

    sibling = SimpleNamespace(previous_plan_id=10)
    state_after_first_publish = SimpleNamespace(current_plan_id=11)
    with pytest.raises(HTTPException) as caught:
        _assert_publish_lineage(sibling, state_after_first_publish)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "PRIORITY_VERSION_CONFLICT"
    assert caught.value.detail["entity"] == "plan_state"


def test_demand_requires_minimum_three_recommendations_and_full_coverage() -> None:
    demand = SimpleNamespace(
        id=10,
        status=PriorityDemandStatus.open,
        expected_recommendations=3,
        required_channel=PriorityChannel.linkedin,
    )
    assignments = [
        SimpleNamespace(
            channel=PriorityChannel.linkedin,
            recommendation_target=2,
        )
    ]
    with pytest.raises(HTTPException, match="plan pokrywa 2"):
        _assert_demand_coverage(demand, assignments)

    assignments.append(
        SimpleNamespace(
            channel=PriorityChannel.mixed,
            recommendation_target=1,
        )
    )
    _assert_demand_coverage(demand, assignments)


def test_demand_rejects_wrong_channel_and_legacy_below_minimum() -> None:
    wrong_channel = SimpleNamespace(
        id=10,
        status=PriorityDemandStatus.open,
        expected_recommendations=3,
        required_channel=PriorityChannel.database,
    )
    with pytest.raises(HTTPException, match="wymaga kanału database"):
        _assert_demand_coverage(
            wrong_channel,
            [
                SimpleNamespace(
                    channel=PriorityChannel.linkedin,
                    recommendation_target=3,
                )
            ],
        )

    below_minimum = SimpleNamespace(
        id=11,
        status=PriorityDemandStatus.open,
        expected_recommendations=2,
        required_channel=PriorityChannel.database,
    )
    with pytest.raises(HTTPException, match="minimum 3"):
        _assert_demand_coverage(below_minimum, [])


@pytest.mark.parametrize(
    ("semantic_state", "expected"),
    [
        ("client_interview_scheduled", "urgent"),
        ("client_approved", "critical"),
        ("offer_preparation", "critical"),
        ("contract_preparation", "critical"),
        ("submitted_to_client", "normal"),
    ],
)
def test_carry_over_urgency_uses_canonical_semantic_states(
    semantic_state: str, expected: str
) -> None:
    assert _carry_over_urgency(semantic_state) == expected


def test_unowned_queue_includes_inactive_or_missing_owner() -> None:
    from app.services.priority_work_service import carry_over_rows

    source = inspect.getsource(carry_over_rows)
    assert "User.is_active.is_(False)" in source
    assert '"ownership_action_required": not bool(owner_active)' in source


def test_two_assignments_are_allowed_in_draft_shape() -> None:
    assert len(_member(2).assignments) == 2


@pytest.mark.parametrize("count", [3, 4, 5])
async def test_publish_validation_accepts_three_to_five_assignments(
    count: int,
) -> None:
    member = _member(count)
    validated = await _validate_member_inputs(
        _validation_db(member),
        [member],
        for_publish=True,
    )
    assert validated[0][0] is member


async def test_publish_validation_accepts_two_assignments() -> None:
    member = _member(2)
    result = await _validate_member_inputs(
        _validation_db(member), [member], for_publish=True
    )
    assert result[0][0] is member


async def test_secondary_job_cc_satisfies_competence_match() -> None:
    member = _member(3)
    user = SimpleNamespace(
        id=member.user_id,
        name="Secondary CC recruiter",
        role=UserRole.recruiter,
        roles=[],
        is_active=True,
    )
    jobs = [
        SimpleNamespace(id=item.job_id, competence_category_id=999)
        for item in member.assignments
    ]
    demands = [
        SimpleNamespace(
            id=item.demand_id,
            job_id=item.job_id,
            status=PriorityDemandStatus.open,
        )
        for item in member.assignments
    ]
    secondary_rows = [(item.job_id, 55) for item in member.assignments]
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=user),
        execute=AsyncMock(
            side_effect=[
                _Rows(jobs),
                _Rows(demands),
                _Rows([55]),
                _Rows(secondary_rows),
            ]
        ),
    )

    validated = await _validate_member_inputs(db, [member], for_publish=True)

    assert validated[0][4] == {item.job_id: {55, 999} for item in member.assignments}


def test_schema_accepts_six_positions_but_rejects_duplicates() -> None:
    assignments = [
        dict(
            demand_id=n,
            job_id=n,
            position=n,
            channel="linkedin",
            verification_target=1,
            recommendation_target=1,
        )
        for n in range(1, 7)
    ]
    assert (
        len(PriorityPlanMemberInput(user_id=7, assignments=assignments).assignments)
        == 6
    )
    with pytest.raises(ValidationError, match="positions must be unique"):
        PriorityPlanMemberInput(
            user_id=7, assignments=[*assignments, {**assignments[-1], "job_id": 99}]
        )


def test_extra_positions_need_no_reason_but_cc_mismatch_does() -> None:
    assert (
        PriorityAssignmentInput(
            demand_id=1, job_id=1, rank=PriorityRank.D, channel=PriorityChannel.linkedin
        ).position
        == 4
    )
    with pytest.raises(ValidationError, match="cc_exception_reason"):
        PriorityAssignmentInput(
            demand_id=1,
            job_id=1,
            rank=PriorityRank.A,
            channel=PriorityChannel.linkedin,
            competence_matches=False,
        )


def test_paused_member_requires_reason_and_cannot_receive_new_work() -> None:
    with pytest.raises(ValidationError, match="paused_reason"):
        PriorityPlanMemberInput(
            user_id=7,
            status=PriorityMemberStatus.paused,
        )
    with pytest.raises(ValidationError, match="cannot have new assignments"):
        PriorityPlanMemberInput(
            user_id=7,
            status=PriorityMemberStatus.paused,
            paused_reason="Urlop",
            assignments=[_assignment(0, 3)],
        )


@pytest.mark.parametrize(
    ("role", "roles", "expected"),
    [
        (UserRole.sourcer, [], {PriorityChannel.database}),
        (UserRole.recruiter, [], {PriorityChannel.linkedin}),
        (
            UserRole.recruiter,
            [UserRole.sourcer.value],
            {PriorityChannel.database, PriorityChannel.linkedin},
        ),
        (
            UserRole.tac,
            [],
            {
                PriorityChannel.database,
                PriorityChannel.linkedin,
                PriorityChannel.mixed,
            },
        ),
    ],
)
def test_channels_follow_operational_specialisation(
    role: UserRole,
    roles: list[str],
    expected: set[PriorityChannel],
) -> None:
    user = SimpleNamespace(role=role, roles=roles)
    assert allowed_channels(user) == expected


def _gate_member() -> SimpleNamespace:
    return SimpleNamespace(
        status=PriorityMemberStatus.active,
        assignments=[
            SimpleNamespace(
                id=1,
                rank=PriorityRank.A,
                verification_target=6,
                recommendation_target=3,
            ),
            SimpleNamespace(
                id=2,
                rank=PriorityRank.B,
                verification_target=4,
                recommendation_target=2,
            ),
        ],
    )


async def test_assignment_progress_uses_attempt_aware_milestone_counter(
    monkeypatch,
) -> None:
    expected = {1: {"verifications": 6, "recommendations": 3}}
    counter = AsyncMock(return_value=expected)
    monkeypatch.setattr(priority_service, "assignment_milestone_counts", counter)
    db = AsyncMock()

    progress = await priority_service.assignment_progress(db, [1, 2])

    assert progress == expected
    counter.assert_awaited_once_with(db, [1, 2])
    source = inspect.getsource(priority_service.assignment_progress)
    assert "assignment_milestone_counts" in source
    assert "candidate_stages" not in source


def test_completed_lower_rank_is_gated_while_higher_rank_is_behind() -> None:
    states = assignment_gate_states(
        _gate_member(),
        {
            1: {"verifications": 5, "recommendations": 3},
            2: {"verifications": 4, "recommendations": 2},
        },
        {},
    )
    assert states == {1: "open", 2: "higher_rank_behind"}


def test_accepted_blocker_releases_completed_lower_rank() -> None:
    accepted = SimpleNamespace(status=PriorityBlockerStatus.accepted)
    states = assignment_gate_states(
        _gate_member(),
        {
            1: {"verifications": 5, "recommendations": 3},
            2: {"verifications": 4, "recommendations": 2},
        },
        {1: [accepted]},
    )
    assert states[2] == "target_reached"


def test_lower_rank_below_its_own_target_stays_open() -> None:
    states = assignment_gate_states(
        _gate_member(),
        {
            1: {"verifications": 0, "recommendations": 0},
            2: {"verifications": 2, "recommendations": 1},
        },
        {},
    )
    assert states[2] == "open"


def test_paused_member_blocks_every_assignment() -> None:
    member = _gate_member()
    member.status = PriorityMemberStatus.paused
    assert assignment_gate_states(member, {}, {}) == {1: "blocked", 2: "blocked"}
