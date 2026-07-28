"""API contracts and role boundaries for Recruitment Priority Work."""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, literal, select
from unittest.mock import AsyncMock

from app.api import (
    application_submissions,
    invite_links,
    jobs,
    priority_work,
    recruitment_access,
)
from app.models.invite_link import CandidateInviteLink
from app.models.recruitment_priority import (
    PriorityBlockerCategory,
    PriorityMode,
    PriorityPlanStatus,
)
from app.models.skill import Skill  # noqa: F401 - register ORM relation for isolation
from app.models.user import UserRole
from app.schemas.priority_work import (
    MAX_BLOCKER_EVIDENCE_BYTES,
    PriorityBlockerCreate,
    PriorityExceptionCreate,
    PriorityHandoffRequest,
)


class _FakeUser:
    def __init__(self, *roles: UserRole):
        self.id = 41
        self._roles = set(roles)

    def has_any_role(self, *roles: UserRole) -> bool:
        return bool(self._roles & set(roles))

    def has_role(self, role: UserRole) -> bool:
        return role in self._roles


def test_priority_role_helpers_require_the_business_role() -> None:
    assert priority_work._is_hor(_FakeUser(UserRole.head_of_recruitment))
    assert priority_work._is_delivery_lead(_FakeUser(UserRole.delivery_lead))
    assert not priority_work._is_hor(_FakeUser(UserRole.admin))
    assert not priority_work._is_delivery_lead(_FakeUser(UserRole.admin))
    assert not priority_work._is_hor(_FakeUser(UserRole.recruiter))
    assert not priority_work._is_delivery_lead(_FakeUser(UserRole.recruiter))


async def test_plain_recruiter_cannot_list_or_create_delivery_demands() -> None:
    recruiter = _FakeUser(UserRole.recruiter)
    with pytest.raises(HTTPException) as list_error:
        await priority_work.list_priority_demands(recruiter, SimpleNamespace())
    assert list_error.value.status_code == 403

    payload = priority_work.DemandCreateRequest(
        job_id=9,
        channel="linkedin",
        note="Potrzebuję trzech dobrych kandydatów",
    )
    with pytest.raises(HTTPException) as create_error:
        await priority_work.create_priority_demand(
            payload,
            recruiter,
            SimpleNamespace(),
        )
    assert create_error.value.status_code == 403


async def test_plain_recruiter_cannot_update_delivery_demand() -> None:
    recruiter = _FakeUser(UserRole.recruiter)
    payload = priority_work.DemandUpdateRequest(expected_version=1)
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(id=8)))

    with pytest.raises(HTTPException) as update_error:
        await priority_work.update_priority_demand(
            8,
            payload,
            recruiter,
            db,
        )

    assert update_error.value.status_code == 403
    assert db.scalar.await_count == 1


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_team_priority_work",
        "create_priority_plan_draft",
        "update_priority_plan_draft",
        "publish_priority_plan",
        "handoff_priority_process",
        "list_priority_exceptions",
        "create_priority_exception",
        "revoke_priority_exception",
        "update_priority_user_mode",
        "get_priority_status",
        "get_priority_reconciliation_status",
        "run_priority_reconciliation",
        "list_priority_alerts",
        "list_priority_audit",
    ],
)
def test_privileged_endpoints_use_hor_dependency(endpoint_name: str) -> None:
    endpoint = getattr(priority_work, endpoint_name)
    annotation = (
        inspect.signature(endpoint)
        .parameters[
            next(
                name
                for name in inspect.signature(endpoint).parameters
                if name in {"current_user", "_current_user"}
            )
        ]
        .annotation
    )
    assert "HeadOfRecruitmentOnly" in str(annotation)


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_current_priority_work",
        "get_my_priority_work",
        "get_job_priority_context",
        "create_priority_blocker",
        "update_priority_blocker",
    ],
)
def test_operational_endpoints_require_operational_dependency(
    endpoint_name: str,
) -> None:
    endpoint = getattr(priority_work, endpoint_name)
    annotation = inspect.signature(endpoint).parameters["current_user"].annotation
    assert "OperationalUser" in str(annotation)


def test_router_exposes_complete_priority_work_surface() -> None:
    methods_by_path: dict[str, set[str]] = {
        route.path: set(route.methods or set()) for route in priority_work.router.routes
    }
    expected = {
        "/current": "GET",
        "/mine": "GET",
        "/team": "GET",
        "/demands": "POST",
        "/plans/draft": "POST",
        "/plans/{plan_id}": "PUT",
        "/plans/{plan_id}/publish": "POST",
        "/jobs/{job_id}": "GET",
        "/assignments/{assignment_id}/blockers": "POST",
        "/processes/{process_id}/handoff": "POST",
        "/exceptions": "POST",
        "/exceptions/{exception_id}/revoke": "POST",
        "/users/{user_id}/mode": "PUT",
        "/status": "GET",
        "/reconciliation/status": "GET",
        "/reconciliation/run": "POST",
        "/alerts": "GET",
        "/audit": "GET",
    }
    for path, method in expected.items():
        assert method in methods_by_path.get(path, set()), f"missing {method} {path}"


def test_job_list_exposes_independent_priority_work_filter_and_context() -> None:
    assert {item.value for item in jobs.PriorityWorkJobFilter} == {
        "assigned",
        "carry_over",
        "either",
    }
    signature = inspect.signature(jobs.list_jobs)
    assert "priority_work" in signature.parameters
    source = inspect.getsource(jobs.list_jobs)
    assert 'd["priority_assignment"]' in source
    assert 'd["priority_carry_over_count"]' in source
    assert "Job.recruiter_id" in source  # legacy `mine` remains separate
    assert "RecruitmentPriorityPlanMember.user_id == current_user.id" in source
    assert "RecruitmentProcess.owner_user_id == current_user.id" in source


def test_priority_assignment_and_carry_over_grant_job_scope_without_policy_bypass() -> (
    None
):
    source = inspect.getsource(recruitment_access.ensure_job_membership)
    assert "effective_priority_mode(db, user.id)" in source
    assert "RecruitmentPriorityPlan.status == PriorityPlanStatus.published" in source
    assert "RecruitmentProcess.owner_user_id == user.id" in source
    assert "RecruitmentProcess.status == ProcessStatus.open" in source
    # Ownership alone is self-grantable — the frozen compliance verdict is what
    # separates a carried process from one opened to grab access. Both the gate
    # and the list-scope builder must carry it, or they drift apart.
    predicate = "RecruitmentProcess.priority_compliant_at_open.is_(True)"
    assert predicate in source
    assert predicate in inspect.getsource(recruitment_access.job_scope_clause)


def _priority_scope_visible(
    monkeypatch,
    *,
    global_mode: PriorityMode,
    user_mode: PriorityMode | None = None,
    assignment_status: str | None = None,
    process_status: str | None = None,
    process_compliant: bool | None = True,
) -> bool:
    """Evaluate the generated list-scope SQL against a minimal real schema."""

    monkeypatch.setattr(
        recruitment_access.settings,
        "RECRUITMENT_PRIORITY_MODE",
        global_mode.value,
    )
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for ddl in (
            "CREATE TABLE jobs ("
            "id INTEGER PRIMARY KEY, recruiter_id INTEGER, "
            "delivery_lead_id INTEGER, tac_id INTEGER)",
            "CREATE TABLE job_collaborators ("
            "job_id INTEGER, user_id INTEGER, removed_from_auto_cc BOOLEAN)",
            "CREATE TABLE recruitment_priority_plans ("
            "id INTEGER PRIMARY KEY, status VARCHAR(20))",
            "CREATE TABLE recruitment_priority_plan_members ("
            "id INTEGER PRIMARY KEY, plan_id INTEGER, user_id INTEGER, "
            "status VARCHAR(20))",
            "CREATE TABLE recruitment_priority_assignments ("
            "id INTEGER PRIMARY KEY, plan_member_id INTEGER, job_id INTEGER)",
            "CREATE TABLE recruitment_priority_user_modes ("
            "user_id INTEGER PRIMARY KEY, mode VARCHAR(20))",
            "CREATE TABLE recruitment_processes ("
            "id INTEGER PRIMARY KEY, job_id INTEGER, owner_user_id INTEGER, "
            "status VARCHAR(20), priority_compliant_at_open BOOLEAN)",
        ):
            connection.exec_driver_sql(ddl)
        connection.exec_driver_sql(
            "INSERT INTO jobs (id, recruiter_id, delivery_lead_id, tac_id) "
            "VALUES (77, NULL, NULL, NULL)"
        )
        if assignment_status is not None:
            connection.exec_driver_sql(
                "INSERT INTO recruitment_priority_plans (id, status) "
                "VALUES (1, 'published')"
            )
            connection.exec_driver_sql(
                "INSERT INTO recruitment_priority_plan_members "
                "(id, plan_id, user_id, status) VALUES (2, 1, 41, ?)",
                (assignment_status,),
            )
            connection.exec_driver_sql(
                "INSERT INTO recruitment_priority_assignments "
                "(id, plan_member_id, job_id) VALUES (3, 2, 77)"
            )
        if process_status is not None:
            connection.exec_driver_sql(
                "INSERT INTO recruitment_processes "
                "(id, job_id, owner_user_id, status, priority_compliant_at_open) "
                "VALUES (4, 77, 41, ?, ?)",
                (process_status, process_compliant),
            )
        if user_mode is not None:
            connection.exec_driver_sql(
                "INSERT INTO recruitment_priority_user_modes (user_id, mode) "
                "VALUES (41, ?)",
                (user_mode.value,),
            )

        clause = recruitment_access.job_scope_clause(
            _FakeUser(UserRole.recruiter),
            literal(77),
        )
        return connection.scalar(select(literal(1)).where(clause)) == 1


def test_global_off_does_not_expand_list_scope_for_assignment_or_carry_over(
    monkeypatch,
) -> None:
    assert not _priority_scope_visible(
        monkeypatch,
        global_mode=PriorityMode.off,
        assignment_status="active",
        process_status="open",
    )


@pytest.mark.parametrize("global_mode", [PriorityMode.shadow, PriorityMode.enforce])
def test_per_user_off_ceiling_does_not_expand_list_scope(
    monkeypatch,
    global_mode: PriorityMode,
) -> None:
    assert not _priority_scope_visible(
        monkeypatch,
        global_mode=global_mode,
        user_mode=PriorityMode.off,
        assignment_status="active",
        process_status="open",
    )


@pytest.mark.parametrize("global_mode", [PriorityMode.shadow, PriorityMode.enforce])
@pytest.mark.parametrize(
    ("assignment_status", "process_status"),
    [("active", None), (None, "open")],
)
def test_non_off_mode_expands_list_scope_only_for_active_priority_work(
    monkeypatch,
    global_mode: PriorityMode,
    assignment_status: str | None,
    process_status: str | None,
) -> None:
    assert _priority_scope_visible(
        monkeypatch,
        global_mode=global_mode,
        assignment_status=assignment_status,
        process_status=process_status,
    )


@pytest.mark.parametrize(
    ("assignment_status", "process_status"),
    [("paused", None), (None, "closed"), (None, "voided")],
)
def test_inactive_assignment_or_finished_process_does_not_expand_list_scope(
    monkeypatch,
    assignment_status: str | None,
    process_status: str | None,
) -> None:
    assert not _priority_scope_visible(
        monkeypatch,
        global_mode=PriorityMode.enforce,
        assignment_status=assignment_status,
        process_status=process_status,
    )


@pytest.mark.parametrize("process_compliant", [False, None])
def test_self_opened_carry_over_does_not_expand_list_scope(
    monkeypatch,
    process_compliant: bool | None,
) -> None:
    """Ownership of an OPEN process is self-grantable, so it is not enough.

    A shadow-mode violation freezes ``priority_compliant_at_open=False`` and
    legacy/backfilled rows leave it NULL; the list scope must fail closed on
    both, matching ``ensure_job_membership``.
    """
    assert not _priority_scope_visible(
        monkeypatch,
        global_mode=PriorityMode.shadow,
        process_status="open",
        process_compliant=process_compliant,
    )


def test_job_delete_cannot_cascade_any_process_audit() -> None:
    source = inspect.getsource(jobs.delete_job)
    assert "select(Job).where(Job.id == job_id)" in source
    assert ".with_for_update()" in source
    assert "RecruitmentProcess.status == ProcessStatus.open" not in source
    assert "CandidateStage.job_id == job_id" in source
    assert '"code": "PRIORITY_CARRY_OVER_EXISTS"' in source


def test_invite_links_freeze_priority_origin_and_gate_creation() -> None:
    source = inspect.getsource(invite_links.create_invite_link)
    assert "assert_priority_work_access" in source
    assert 'action="create_invite_link"' in source
    assert "consume_exception=False" in source
    assert "origin_assignment_id=origin_assignment_id" in source
    assert hasattr(CandidateInviteLink, "origin_assignment_id")
    assert hasattr(CandidateInviteLink, "priority_compliant_at_create")


def test_duplicate_application_resolution_enters_canonical_pipeline() -> None:
    endpoint_source = inspect.getsource(
        application_submissions.resolve_application_submission
    )
    helper_source = inspect.getsource(
        application_submissions._ensure_submission_process
    )
    assert endpoint_source.count("_ensure_submission_process(") == 2
    assert "open_process(" in helper_source
    assert "frozen_origin_assignment_id=_origin_assignment_id(submission)" in (
        helper_source
    )
    assert (
        "frozen_priority_compliant=_priority_compliant_at_create(submission)"
        in helper_source
    )


def test_date_deadline_is_end_of_business_day_in_warsaw() -> None:
    assert priority_work._deadline(date(2026, 1, 15)) == datetime(
        2026, 1, 15, 16, 0, tzinfo=timezone.utc
    )
    assert priority_work._deadline(date(2026, 7, 15)) == datetime(
        2026, 7, 15, 15, 0, tzinfo=timezone.utc
    )


def test_plan_serializer_keeps_rollout_mode_and_overdue_state() -> None:
    plan = SimpleNamespace(
        id=5,
        version=3,
        row_version=8,
        status=PriorityPlanStatus.published,
        previous_plan_id=4,
        effective_from=None,
        review_due_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        published_at=None,
        superseded_at=None,
        notes="Plan",
        members=[],
    )
    payload = priority_work._serialize_plan(
        plan,
        mode=PriorityMode.shadow,
        include_members=True,
    )
    assert payload is not None
    assert payload["mode"] == "shadow"
    assert payload["overdue"] is True
    assert payload["row_version"] == 8
    assert payload["members"] == []


async def test_current_response_keeps_effective_mode_without_a_plan(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        priority_work,
        "effective_priority_mode",
        AsyncMock(return_value=PriorityMode.enforce),
    )
    monkeypatch.setattr(
        priority_work,
        "current_plan",
        AsyncMock(return_value=None),
    )
    user = SimpleNamespace(id=41)

    payload = await priority_work.get_current_priority_work(
        user,
        SimpleNamespace(),
    )

    assert payload == {"mode": "enforce", "plan": None}


def test_team_and_demand_read_models_expose_server_validated_context() -> None:
    team_source = inspect.getsource(priority_work.get_team_priority_work)
    demand_source = inspect.getsource(priority_work._serialize_demand)
    assert "JobSecondaryCc.competence_category_id" in demand_source
    assert '"competence_category_ids": sorted(' in demand_source
    assignment_source = inspect.getsource(priority_work._assignment_payloads)
    job_source = inspect.getsource(priority_work.get_job_priority_context)

    assert '"roles": sorted(role_values(user))' in team_source
    assert '"allowed_channels": sorted(' in team_source
    assert '"competence_category_ids": sorted(' in team_source
    assert "all_carry_over = await carry_over_rows(db)" in team_source
    assert "await carry_over_rows(db, owner_user_id=user.id)" not in team_source
    assert '"competence_category_id": (' in demand_source
    assert '"assignments": demand_assignments' in demand_source
    assert '"cc_exception_required": not assignment.competence_matches' in (
        assignment_source
    )
    assert '"mode": mode.value' in job_source


def test_api_write_models_reject_zero_targets_and_versions() -> None:
    with pytest.raises(ValidationError):
        priority_work.AssignmentUpdateRequest(
            job_id=1,
            rank="A",
            channel="linkedin",
            verification_target=0,
            recommendation_target=1,
        )
    with pytest.raises(ValidationError):
        PriorityHandoffRequest(
            process_id=1,
            new_owner_user_id=2,
            reason="Zmiana ownera",
            expected_process_version=0,
        )
    with pytest.raises(ValidationError):
        priority_work.DemandCreateRequest(
            job_id=1,
            expected_recommendations=2,
            channel="linkedin",
            note="Za mały demand",
        )


def test_blocker_evidence_is_json_safe_and_bounded() -> None:
    evidence = {"blob": "x" * MAX_BLOCKER_EVIDENCE_BYTES}
    with pytest.raises(ValidationError, match="at most"):
        priority_work.BlockerCreateRequest(
            category=PriorityBlockerCategory.other,
            note="Za duży dowód",
            evidence=evidence,
        )
    with pytest.raises(ValidationError, match="at most"):
        PriorityBlockerCreate(
            assignment_id=1,
            category=PriorityBlockerCategory.other,
            description="Za duży dowód",
            evidence=evidence,
        )
    with pytest.raises(ValidationError, match="JSON-serializable"):
        priority_work.BlockerCreateRequest(
            category=PriorityBlockerCategory.other,
            note="Niepoprawny dowód",
            evidence={"bad": object()},
        )


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
def test_blocker_evidence_rejects_non_finite_numbers(
    invalid_number: float,
) -> None:
    with pytest.raises(ValidationError, match="JSON-serializable"):
        priority_work.BlockerCreateRequest(
            category=PriorityBlockerCategory.other,
            note="Niepoprawny dowód",
            evidence={"value": invalid_number},
        )
    with pytest.raises(ValidationError, match="JSON-serializable"):
        PriorityBlockerCreate(
            assignment_id=1,
            category=PriorityBlockerCategory.other,
            description="Niepoprawny dowód",
            evidence={"value": invalid_number},
        )


def test_blocker_resolution_locks_blocker_and_assignment_ownership() -> None:
    source = inspect.getsource(priority_work.update_priority_blocker)
    assert source.count(".with_for_update()") >= 2
    create_source = inspect.getsource(priority_work.create_priority_blocker)
    assert "PriorityPlanStatus.published" in create_source


def test_demand_scope_tracks_current_delivery_lead_not_historical_author() -> None:
    list_source = inspect.getsource(priority_work.list_priority_demands)
    update_source = inspect.getsource(priority_work.update_priority_demand)
    assert "Job.delivery_lead_id == current_user.id" in list_source
    assert "select(Job.delivery_lead_id)" in update_source
    assert "_is_delivery_lead(current_user)" in update_source
    assert "row.requested_by_user_id != current_user.id" not in update_source
    assert "assert_demand_status_transition(" in update_source


def test_exception_origin_must_match_user_and_job() -> None:
    source = inspect.getsource(priority_work.create_priority_exception)
    assert "RecruitmentPriorityAssignment.job_id" in source
    assert "RecruitmentPriorityPlanMember.user_id" in source
    assert "origin.job_id != payload.job_id" in source
    assert "origin.user_id != payload.user_id" in source


def test_one_shot_exception_requires_forward_time_window() -> None:
    now = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="later than valid_from"):
        PriorityExceptionCreate(
            user_id=1,
            job_id=2,
            reason="Jednorazowa zgoda HoR",
            valid_from=now,
            expires_at=now,
        )


def test_one_shot_exception_rejects_expired_and_naive_windows() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="future"):
        PriorityExceptionCreate(
            user_id=1,
            job_id=2,
            reason="Okno już wygasło",
            valid_from=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        PriorityExceptionCreate(
            user_id=1,
            job_id=2,
            reason="Brak strefy czasowej",
            valid_from=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=1),
        )


def test_one_shot_exception_accepts_a_future_window() -> None:
    now = datetime.now(timezone.utc)
    payload = PriorityExceptionCreate(
        user_id=1,
        job_id=2,
        reason="Jednorazowa zgoda HoR",
        valid_from=now,
        expires_at=now + timedelta(hours=1),
    )
    assert payload.expires_at > payload.valid_from
