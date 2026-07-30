"""Application service for versioned Recruitment Priority Work plans.

This module owns the transactional plan lifecycle and the read models consumed
by the three role dashboards.  Pipeline admission itself stays in
``priority_work_policy`` so every writer (HTTP, import and automation) applies
the same decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.candidate import Candidate
from app.models.cc_feedback import JobSecondaryCc
from app.models.client import Client
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_priority import (
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityDemandStatus,
    PriorityMemberStatus,
    PriorityPlanStatus,
    PriorityRank,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityAuditEvent,
    RecruitmentPriorityBlocker,
    RecruitmentPriorityDemand,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityState,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.schemas.priority_work import PriorityPlanMemberInput
from app.services.priority_work_policy import assignment_milestone_counts

WARSAW = ZoneInfo(DEFAULT_TZ)
DEFAULT_VERIFICATION_CAPACITY = 12
RANK_ORDER = {
    PriorityRank.A: 1,
    PriorityRank.B: 2,
    PriorityRank.C: 3,
    PriorityRank.D: 4,
    PriorityRank.E: 5,
}
OPERATIONAL_ROLES = {
    UserRole.sourcer,
    UserRole.recruiter,
    UserRole.tac,
}
_DEMAND_STATUS_TRANSITIONS_DL = {
    PriorityDemandStatus.open: {
        PriorityDemandStatus.paused,
        PriorityDemandStatus.cancelled,
    },
    PriorityDemandStatus.covered: {
        PriorityDemandStatus.paused,
        PriorityDemandStatus.cancelled,
    },
    PriorityDemandStatus.paused: {
        PriorityDemandStatus.open,
        PriorityDemandStatus.cancelled,
    },
}
_DEMAND_STATUS_TRANSITIONS_HOR = {
    PriorityDemandStatus.open: {
        PriorityDemandStatus.paused,
        PriorityDemandStatus.fulfilled,
        PriorityDemandStatus.cancelled,
    },
    PriorityDemandStatus.covered: {
        PriorityDemandStatus.paused,
        PriorityDemandStatus.fulfilled,
        PriorityDemandStatus.cancelled,
    },
    PriorityDemandStatus.paused: {
        PriorityDemandStatus.open,
        PriorityDemandStatus.fulfilled,
        PriorityDemandStatus.cancelled,
    },
}
URGENT_CARRY_OVER_STATES = {
    "client_interview_scheduled",
    "client_approved",
    "offer_preparation",
    "contract_preparation",
}
CRITICAL_CARRY_OVER_STATES = {
    "client_approved",
    "offer_preparation",
    "contract_preparation",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def review_due_after_business_days(
    started_at: datetime, business_days: int = 3
) -> datetime:
    """Return the Warsaw wall-clock time after Polish business days."""
    local = started_at.astimezone(WARSAW)
    cursor = local
    remaining = business_days
    while remaining:
        cursor += timedelta(days=1)
        if is_business_day(cursor, DEFAULT_TZ):
            remaining -= 1
    return cursor.astimezone(timezone.utc)


async def ensure_priority_state(
    db: AsyncSession, *, for_update: bool = False
) -> RecruitmentPriorityState:
    """Return the singleton state row, creating it with an idempotent upsert."""
    await db.execute(
        pg_insert(RecruitmentPriorityState)
        .values(id=1, row_version=1, metrics={})
        .on_conflict_do_nothing(index_elements=[RecruitmentPriorityState.id])
    )
    statement = select(RecruitmentPriorityState).where(RecruitmentPriorityState.id == 1)
    if for_update:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if row is None:  # pragma: no cover - guarded by the upsert
        raise RuntimeError("Recruitment Priority state could not be initialized")
    return row


def audit_event(
    db: AsyncSession,
    event_type: str,
    *,
    actor_user_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    subject_user_id: Optional[int] = None,
    job_id: Optional[int] = None,
    assignment_id: Optional[int] = None,
    process_id: Optional[int] = None,
    exception_id: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> RecruitmentPriorityAuditEvent:
    event = RecruitmentPriorityAuditEvent(
        event_type=event_type,
        actor_user_id=actor_user_id,
        plan_id=plan_id,
        subject_user_id=subject_user_id,
        job_id=job_id,
        assignment_id=assignment_id,
        process_id=process_id,
        exception_id=exception_id,
        payload=payload or {},
        occurred_at=utcnow(),
        correlation_id=correlation_id,
    )
    db.add(event)
    return event


def _optimistic_conflict(entity: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "PRIORITY_VERSION_CONFLICT",
            "entity": entity,
            "message": (
                "Dane zostały zmienione w innym oknie. Odśwież widok i spróbuj ponownie."
            ),
        },
    )


def _assert_publish_lineage(
    plan: RecruitmentPriorityPlan,
    state: RecruitmentPriorityState,
) -> None:
    """Reject a stale draft after another plan won the publication race.

    Locking the singleton serializes publishers, but serialization alone would
    let two sibling drafts both return success one after another. The draft's
    frozen predecessor is the compare-and-swap token for the current plan.
    """

    if plan.previous_plan_id != state.current_plan_id:
        raise _optimistic_conflict("plan_state")


def _published_demand_status(
    current: PriorityDemandStatus, *, included_in_plan: bool
) -> PriorityDemandStatus:
    """Keep demand coverage aligned with the newly published plan."""

    if current not in {PriorityDemandStatus.open, PriorityDemandStatus.covered}:
        return current
    return (
        PriorityDemandStatus.covered if included_in_plan else PriorityDemandStatus.open
    )


def assert_demand_status_transition(
    current: PriorityDemandStatus,
    target: PriorityDemandStatus,
    *,
    actor_is_hor: bool,
) -> None:
    """Enforce the manual lifecycle; only plan publication manages `covered`."""

    if target == current:
        return
    transitions = (
        _DEMAND_STATUS_TRANSITIONS_HOR
        if actor_is_hor
        else _DEMAND_STATUS_TRANSITIONS_DL
    )
    if target not in transitions.get(current, set()):
        raise HTTPException(
            422,
            {
                "code": "PRIORITY_DEMAND_TRANSITION_INVALID",
                "from": current.value,
                "to": target.value,
                "message": "Niedozwolona zmiana statusu demandu.",
            },
        )


def _assert_demand_coverage(
    demand: RecruitmentPriorityDemand,
    assignments: list[RecruitmentPriorityAssignment],
) -> None:
    """Require enough recommendations in the DL-requested sourcing channel."""

    if demand.status not in {
        PriorityDemandStatus.open,
        PriorityDemandStatus.covered,
    }:
        raise HTTPException(
            422,
            f"Demand #{demand.id} nie jest aktywny i nie może wejść do planu",
        )
    if demand.expected_recommendations < 3:
        raise HTTPException(
            422,
            f"Demand #{demand.id} musi wymagać minimum 3 rekomendacji",
        )

    required = demand.required_channel
    incompatible = [
        assignment
        for assignment in assignments
        if required is not None
        and not (
            (required == PriorityChannel.mixed and assignment.channel == required)
            or (
                required != PriorityChannel.mixed
                and assignment.channel in {required, PriorityChannel.mixed}
            )
        )
    ]
    if incompatible:
        raise HTTPException(
            422,
            (
                f"Demand #{demand.id} wymaga kanału "
                f"{demand.required_channel.value}; plan zawiera inny kanał"
            ),
        )
    recommendation_coverage = sum(
        assignment.recommendation_target for assignment in assignments
    )
    if recommendation_coverage < demand.expected_recommendations:
        raise HTTPException(
            422,
            (
                f"Demand #{demand.id} wymaga "
                f"{demand.expected_recommendations} rekomendacji, "
                f"a plan pokrywa {recommendation_coverage}"
            ),
        )


def _carry_over_urgency(semantic_state: str) -> str:
    if semantic_state in CRITICAL_CARRY_OVER_STATES:
        return "critical"
    if semantic_state in URGENT_CARRY_OVER_STATES:
        return "urgent"
    return "normal"


async def load_plan(
    db: AsyncSession, plan_id: int, *, for_update: bool = False
) -> Optional[RecruitmentPriorityPlan]:
    statement = (
        select(RecruitmentPriorityPlan)
        .where(RecruitmentPriorityPlan.id == plan_id)
        .options(
            selectinload(RecruitmentPriorityPlan.members).selectinload(
                RecruitmentPriorityPlanMember.assignments
            )
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def current_plan(db: AsyncSession) -> Optional[RecruitmentPriorityPlan]:
    state = await ensure_priority_state(db)
    if state.current_plan_id is None:
        return None
    return await load_plan(db, state.current_plan_id)


async def create_draft_plan(
    db: AsyncSession,
    *,
    actor_user_id: int,
    source_plan_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> RecruitmentPriorityPlan:
    """Create a new version, optionally cloning an existing plan."""
    state = await ensure_priority_state(db, for_update=True)
    clone_source_id = (
        source_plan_id if source_plan_id is not None else state.current_plan_id
    )
    source = await load_plan(db, clone_source_id) if clone_source_id else None
    next_version = (
        int(
            await db.scalar(
                select(func.coalesce(func.max(RecruitmentPriorityPlan.version), 0))
            )
            or 0
        )
        + 1
    )
    draft = RecruitmentPriorityPlan(
        version=next_version,
        status=PriorityPlanStatus.draft,
        # Lineage always points at the published plan observed while holding
        # the state lock. ``source_plan_id`` may select other content to clone,
        # but it is not publication authority.
        previous_plan_id=state.current_plan_id,
        created_by_user_id=actor_user_id,
        notes=notes,
        row_version=1,
    )
    db.add(draft)
    await db.flush()

    if source:
        for old_member in source.members:
            member = RecruitmentPriorityPlanMember(
                plan_id=draft.id,
                user_id=old_member.user_id,
                status=old_member.status,
                verification_capacity=old_member.verification_capacity,
                capacity_reason=old_member.capacity_reason,
                paused_reason=old_member.paused_reason,
            )
            db.add(member)
            await db.flush()
            for old_assignment in old_member.assignments:
                db.add(
                    RecruitmentPriorityAssignment(
                        plan_member_id=member.id,
                        demand_id=old_assignment.demand_id,
                        job_id=old_assignment.job_id,
                        rank=old_assignment.rank,
                        channel=old_assignment.channel,
                        verification_target=old_assignment.verification_target,
                        recommendation_target=old_assignment.recommendation_target,
                        competence_category_id=(old_assignment.competence_category_id),
                        competence_matches=old_assignment.competence_matches,
                        cc_exception_reason=old_assignment.cc_exception_reason,
                        extra_slot_reason=old_assignment.extra_slot_reason,
                        suggestion_source="cloned",
                    )
                )
    audit_event(
        db,
        "plan_draft_created",
        actor_user_id=actor_user_id,
        plan_id=draft.id,
        payload={"source_plan_id": clone_source_id, "version": next_version},
    )
    await db.flush()
    return (await load_plan(db, draft.id)) or draft


def role_values(user: User) -> set[str]:
    values = {user.role.value}
    values.update(str(value) for value in (user.roles or []))
    return values


def allowed_channels(user: User) -> set[PriorityChannel]:
    roles = role_values(user)
    if UserRole.tac.value in roles:
        return {
            PriorityChannel.database,
            PriorityChannel.linkedin,
            PriorityChannel.mixed,
        }
    allowed: set[PriorityChannel] = set()
    if UserRole.sourcer.value in roles:
        allowed.add(PriorityChannel.database)
    if UserRole.recruiter.value in roles:
        allowed.add(PriorityChannel.linkedin)
    return allowed


async def _validate_member_inputs(
    db: AsyncSession,
    members: Iterable[PriorityPlanMemberInput],
    *,
    for_publish: bool,
) -> list[
    tuple[
        PriorityPlanMemberInput,
        User,
        dict[int, Job],
        set[int],
        dict[int, set[int]],
    ]
]:
    """Validate cross-row rules and return loaded users/jobs/CCs."""
    validated: list[
        tuple[
            PriorityPlanMemberInput,
            User,
            dict[int, Job],
            set[int],
            dict[int, set[int]],
        ]
    ] = []
    seen_users: set[int] = set()
    for member in members:
        if member.user_id in seen_users:
            raise HTTPException(422, "Użytkownik występuje w planie więcej niż raz")
        seen_users.add(member.user_id)
        user = await db.scalar(select(User).where(User.id == member.user_id))
        if user is None or not user.is_active:
            raise HTTPException(422, f"Nieaktywny lub brakujący user #{member.user_id}")
        if not (role_values(user) & {role.value for role in OPERATIONAL_ROLES}):
            raise HTTPException(
                422,
                f"User #{member.user_id} nie ma roli recruiter/sourcer/TAC",
            )

        if member.status == PriorityMemberStatus.paused:
            if member.assignments:
                raise HTTPException(
                    422, "Wstrzymany członek nie ma nowych assignmentów"
                )
            validated.append((member, user, {}, set(), {}))
            continue

        assignments = list(member.assignments)
        if len(assignments) > 5 or (for_publish and len(assignments) < 3):
            raise HTTPException(
                422,
                (
                    "Aktywny członek musi mieć 3–5 assignmentów"
                    if for_publish
                    else "Draft może mieć maksymalnie 5 assignmentów na osobę"
                ),
            )
        expected_ranks = list(PriorityRank)[: len(assignments)]
        actual_ranks = sorted((item.rank for item in assignments), key=RANK_ORDER.get)
        if actual_ranks != expected_ranks:
            raise HTTPException(422, "Ranki muszą być unikalne i ciągłe od A")
        if assignments and any(
            item.verification_target <= 0 or item.recommendation_target <= 0
            for item in assignments
        ):
            raise HTTPException(422, "Każdy assignment wymaga dodatniego targetu")
        target_sum = sum(item.verification_target for item in assignments)
        if for_publish and target_sum != member.verification_capacity:
            raise HTTPException(
                422,
                "Suma targetów weryfikacji musi równać się pojemności członka",
            )
        if (
            for_publish
            and member.verification_capacity != DEFAULT_VERIFICATION_CAPACITY
            and not (member.capacity_reason and member.capacity_reason.strip())
        ):
            raise HTTPException(
                422,
                "Zmiana domyślnej pojemności 12 wymaga capacity_reason",
            )

        job_ids = {item.job_id for item in assignments}
        jobs = {
            job.id: job
            for job in (
                (await db.execute(select(Job).where(Job.id.in_(job_ids))))
                .scalars()
                .all()
            )
        }
        if len(jobs) != len(job_ids):
            raise HTTPException(422, "Co najmniej jeden request nie istnieje")

        demand_ids = {item.demand_id for item in assignments}
        demand_rows = (
            (
                await db.execute(
                    select(RecruitmentPriorityDemand).where(
                        RecruitmentPriorityDemand.id.in_(demand_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        demands = {row.id: row for row in demand_rows}
        if len(demands) != len(demand_ids):
            raise HTTPException(422, "Co najmniej jeden demand nie istnieje")

        user_ccs = set(
            (
                await db.execute(
                    select(UserCompetenceCategory.competence_category_id).where(
                        UserCompetenceCategory.user_id == member.user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        job_ccs: dict[int, set[int]] = {
            job.id: (
                {job.competence_category_id}
                if job.competence_category_id is not None
                else set()
            )
            for job in jobs.values()
        }
        secondary_cc_rows = (
            await db.execute(
                select(
                    JobSecondaryCc.job_id,
                    JobSecondaryCc.competence_category_id,
                ).where(JobSecondaryCc.job_id.in_(job_ids))
            )
        ).all()
        for job_id, competence_category_id in secondary_cc_rows:
            job_ccs.setdefault(job_id, set()).add(competence_category_id)
        user_allowed_channels = allowed_channels(user)
        for assignment in assignments:
            job = jobs[assignment.job_id]
            demand = demands[assignment.demand_id]
            if demand.job_id != assignment.job_id:
                raise HTTPException(422, "Demand i assignment wskazują różne requesty")
            if demand.status in {
                PriorityDemandStatus.fulfilled,
                PriorityDemandStatus.cancelled,
            }:
                raise HTTPException(422, "Zamknięty demand nie może wejść do planu")
            if assignment.channel not in user_allowed_channels:
                raise HTTPException(
                    422,
                    f"Kanał {assignment.channel.value} jest niedozwolony dla {user.name}",
                )
            matches = bool(job_ccs.get(job.id, set()) & user_ccs)
            if not matches and not (
                assignment.cc_exception_reason
                and assignment.cc_exception_reason.strip()
            ):
                raise HTTPException(
                    422,
                    f"Brak dopasowania CC dla {user.name} / job #{job.id} wymaga uzasadnienia",
                )
            if assignment.rank in {PriorityRank.D, PriorityRank.E} and not (
                assignment.extra_slot_reason and assignment.extra_slot_reason.strip()
            ):
                raise HTTPException(422, "Slot D/E wymaga uzasadnienia HoR")
        validated.append((member, user, jobs, user_ccs, job_ccs))
    return validated


async def replace_draft_members(
    db: AsyncSession,
    *,
    plan_id: int,
    expected_version: int,
    members: list[PriorityPlanMemberInput],
    actor_user_id: int,
    notes: Optional[str] = None,
) -> RecruitmentPriorityPlan:
    plan = await load_plan(db, plan_id, for_update=True)
    if plan is None:
        raise HTTPException(404, "Plan nie istnieje")
    if plan.status != PriorityPlanStatus.draft:
        raise HTTPException(409, "Opublikowany plan jest niezmienny")
    if plan.row_version != expected_version:
        raise _optimistic_conflict("plan")

    validated = await _validate_member_inputs(db, members, for_publish=False)
    await db.execute(
        delete(RecruitmentPriorityPlanMember).where(
            RecruitmentPriorityPlanMember.plan_id == plan.id
        )
    )
    await db.flush()
    for member_input, _user, jobs, user_ccs, job_ccs in validated:
        member = RecruitmentPriorityPlanMember(
            plan_id=plan.id,
            user_id=member_input.user_id,
            status=member_input.status,
            verification_capacity=member_input.verification_capacity,
            capacity_reason=member_input.capacity_reason,
            paused_reason=member_input.paused_reason,
        )
        db.add(member)
        await db.flush()
        for item in member_input.assignments:
            job = jobs[item.job_id]
            matched_ccs = sorted(job_ccs.get(job.id, set()) & user_ccs)
            assignment_ccs = sorted(job_ccs.get(job.id, set()))
            db.add(
                RecruitmentPriorityAssignment(
                    plan_member_id=member.id,
                    demand_id=item.demand_id,
                    job_id=item.job_id,
                    rank=item.rank,
                    channel=item.channel,
                    verification_target=item.verification_target,
                    recommendation_target=item.recommendation_target,
                    competence_category_id=(
                        matched_ccs[0]
                        if matched_ccs
                        else (
                            job.competence_category_id
                            if job.competence_category_id is not None
                            else (assignment_ccs[0] if assignment_ccs else None)
                        )
                    ),
                    competence_matches=bool(matched_ccs),
                    cc_exception_reason=item.cc_exception_reason,
                    extra_slot_reason=item.extra_slot_reason,
                    suggestion_source=item.suggestion_source,
                )
            )
    if notes is not None:
        plan.notes = notes
    plan.row_version += 1
    audit_event(
        db,
        "plan_draft_updated",
        actor_user_id=actor_user_id,
        plan_id=plan.id,
        payload={"member_count": len(members), "row_version": plan.row_version},
    )
    await db.flush()
    db.expire(plan, ["members"])
    return (await load_plan(db, plan.id)) or plan


async def _validate_persisted_plan(
    db: AsyncSession, plan: RecruitmentPriorityPlan
) -> None:
    inputs = [
        PriorityPlanMemberInput(
            user_id=member.user_id,
            status=member.status,
            verification_capacity=member.verification_capacity,
            capacity_reason=member.capacity_reason,
            paused_reason=member.paused_reason,
            assignments=[
                {
                    "demand_id": assignment.demand_id,
                    "job_id": assignment.job_id,
                    "rank": assignment.rank,
                    "channel": assignment.channel,
                    "verification_target": assignment.verification_target,
                    "recommendation_target": assignment.recommendation_target,
                    "competence_category_id": assignment.competence_category_id,
                    "competence_matches": assignment.competence_matches,
                    "cc_exception_reason": assignment.cc_exception_reason,
                    "extra_slot_reason": assignment.extra_slot_reason,
                    "suggestion_source": assignment.suggestion_source,
                }
                for assignment in member.assignments
            ],
        )
        for member in plan.members
    ]
    if not inputs:
        raise HTTPException(422, "Nie można opublikować pustego planu")
    await _validate_member_inputs(db, inputs, for_publish=True)

    assignments = [
        assignment for member in plan.members for assignment in member.assignments
    ]
    demand_ids = {assignment.demand_id for assignment in assignments}
    job_ids = {assignment.job_id for assignment in assignments}
    demands = {
        demand.id: demand
        for demand in (
            (
                await db.execute(
                    select(RecruitmentPriorityDemand)
                    .where(RecruitmentPriorityDemand.id.in_(demand_ids))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
    }
    jobs = {
        job.id: job
        for job in (
            (await db.execute(select(Job).where(Job.id.in_(job_ids)).with_for_update()))
            .scalars()
            .all()
        )
    }
    for job in jobs.values():
        if job.status != JobStatus.published:
            raise HTTPException(
                422,
                f"Request #{job.id} nie jest opublikowany i nie może wejść do planu",
            )

    assignments_by_demand: dict[int, list[RecruitmentPriorityAssignment]] = {}
    for assignment in assignments:
        assignments_by_demand.setdefault(assignment.demand_id, []).append(assignment)
    for demand_id, demand_assignments in assignments_by_demand.items():
        demand = demands.get(demand_id)
        if demand is None:
            raise HTTPException(422, f"Demand #{demand_id} nie istnieje")
        _assert_demand_coverage(demand, demand_assignments)


async def publish_plan(
    db: AsyncSession,
    *,
    plan_id: int,
    expected_version: int,
    actor_user_id: int,
) -> RecruitmentPriorityPlan:
    """Atomically supersede the old plan and activate this draft."""
    state = await ensure_priority_state(db, for_update=True)
    plan = await load_plan(db, plan_id, for_update=True)
    if plan is None:
        raise HTTPException(404, "Plan nie istnieje")
    if plan.status != PriorityPlanStatus.draft:
        raise HTTPException(409, "Tylko draft można opublikować")
    if plan.row_version != expected_version:
        raise _optimistic_conflict("plan")
    _assert_publish_lineage(plan, state)
    await _validate_persisted_plan(db, plan)

    now = utcnow()
    previous_id = state.current_plan_id
    if previous_id and previous_id != plan.id:
        previous = await db.scalar(
            select(RecruitmentPriorityPlan)
            .where(RecruitmentPriorityPlan.id == previous_id)
            .with_for_update()
        )
        if previous is not None:
            previous.status = PriorityPlanStatus.superseded
            previous.superseded_at = now
            previous.row_version += 1
            # The partial unique index permits exactly one `published` row.
            # Flush the supersede before making the draft published so SQL
            # statement ordering can never cause a transient uniqueness error.
            await db.flush()

    plan.status = PriorityPlanStatus.published
    plan.effective_from = now
    plan.published_at = now
    plan.review_due_at = review_due_after_business_days(now)
    plan.published_by_user_id = actor_user_id
    plan.row_version += 1
    state.current_plan_id = plan.id
    state.row_version += 1
    demand_ids = {
        assignment.demand_id
        for member in plan.members
        for assignment in member.assignments
    }
    demands = (
        (
            await db.execute(
                select(RecruitmentPriorityDemand)
                .where(
                    RecruitmentPriorityDemand.status.in_(
                        [
                            PriorityDemandStatus.open,
                            PriorityDemandStatus.covered,
                        ]
                    )
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for demand in demands:
        next_status = _published_demand_status(
            demand.status,
            included_in_plan=demand.id in demand_ids,
        )
        if demand.status != next_status:
            demand.status = next_status
            demand.row_version += 1
    audit_event(
        db,
        "plan_published",
        actor_user_id=actor_user_id,
        plan_id=plan.id,
        payload={
            "version": plan.version,
            "superseded_plan_id": previous_id,
            "review_due_at": plan.review_due_at.isoformat(),
        },
    )
    await db.flush()
    return (await load_plan(db, plan.id)) or plan


async def assignment_progress(
    db: AsyncSession, assignment_ids: Iterable[int]
) -> dict[int, dict[str, int]]:
    return await assignment_milestone_counts(db, assignment_ids)


async def active_blockers(
    db: AsyncSession, assignment_ids: Iterable[int]
) -> dict[int, list[RecruitmentPriorityBlocker]]:
    ids = list(assignment_ids)
    if not ids:
        return {}
    rows = (
        (
            await db.execute(
                select(RecruitmentPriorityBlocker)
                .where(
                    RecruitmentPriorityBlocker.assignment_id.in_(ids),
                    RecruitmentPriorityBlocker.status.in_(
                        [
                            PriorityBlockerStatus.pending,
                            PriorityBlockerStatus.accepted,
                        ]
                    ),
                    RecruitmentPriorityBlocker.resolved_at.is_(None),
                )
                .order_by(RecruitmentPriorityBlocker.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[int, list[RecruitmentPriorityBlocker]] = {}
    for row in rows:
        grouped.setdefault(row.assignment_id, []).append(row)
    return grouped


def assignment_gate_states(
    member: RecruitmentPriorityPlanMember,
    progress: dict[int, dict[str, int]],
    blockers: dict[int, list[RecruitmentPriorityBlocker]],
) -> dict[int, str]:
    if member.status == PriorityMemberStatus.paused:
        return {assignment.id: "blocked" for assignment in member.assignments}
    ordered = sorted(member.assignments, key=lambda item: RANK_ORDER[item.rank])
    states: dict[int, str] = {}
    for assignment in ordered:
        current = progress.get(
            assignment.id, {"verifications": 0, "recommendations": 0}
        )
        # Sourcing capacity is exhausted by the verification target.  The
        # higher-priority request is considered complete only after both its
        # verification and recommendation targets are met; this mirrors the
        # admission policy used by every pipeline writer.
        own_target_reached = current["verifications"] >= assignment.verification_target
        higher_behind = False
        if own_target_reached:
            for higher in ordered:
                if RANK_ORDER[higher.rank] >= RANK_ORDER[assignment.rank]:
                    break
                higher_progress = progress.get(
                    higher.id, {"verifications": 0, "recommendations": 0}
                )
                higher_complete = (
                    higher_progress["verifications"] >= higher.verification_target
                    and higher_progress["recommendations"]
                    >= higher.recommendation_target
                )
                has_accepted_blocker = any(
                    blocker.status == PriorityBlockerStatus.accepted
                    for blocker in blockers.get(higher.id, [])
                )
                if not higher_complete and not has_accepted_blocker:
                    higher_behind = True
                    break
        if higher_behind:
            states[assignment.id] = "higher_rank_behind"
        elif own_target_reached:
            states[assignment.id] = "target_reached"
        else:
            states[assignment.id] = "open"
    return states


async def carry_over_rows(
    db: AsyncSession,
    *,
    owner_user_id: Optional[int] = None,
    job_id: Optional[int] = None,
    unowned_only: bool = False,
) -> list[dict[str, Any]]:
    conditions = [RecruitmentProcess.status == ProcessStatus.open]
    if unowned_only:
        conditions.append(
            or_(
                RecruitmentProcess.owner_user_id.is_(None),
                User.id.is_(None),
                User.is_active.is_(False),
            )
        )
    elif owner_user_id is not None:
        conditions.append(RecruitmentProcess.owner_user_id == owner_user_id)
    if job_id is not None:
        conditions.append(RecruitmentProcess.job_id == job_id)
    rows = (
        await db.execute(
            select(
                RecruitmentProcess,
                Candidate.name,
                Candidate.lastname,
                Job.title,
                Client.name.label("client_name"),
                CandidateStage.moved_at.label("stage_moved_at"),
                User.name.label("owner_name"),
                User.is_active.label("owner_active"),
            )
            .join(Candidate, Candidate.id == RecruitmentProcess.candidate_id)
            .join(Job, Job.id == RecruitmentProcess.job_id)
            .join(Client, Client.id == Job.client_id)
            .outerjoin(
                CandidateStage,
                CandidateStage.id
                == RecruitmentProcess.legacy_current_candidate_stage_id,
            )
            .outerjoin(User, User.id == RecruitmentProcess.owner_user_id)
            .where(*conditions)
            .order_by(
                RecruitmentProcess.owner_user_id.is_(None).desc(),
                RecruitmentProcess.updated_at.asc(),
            )
        )
    ).all()
    now = utcnow()
    result: list[dict[str, Any]] = []
    for (
        process,
        first_name,
        last_name,
        title,
        client_name,
        moved_at,
        owner_name,
        owner_active,
    ) in rows:
        stage = process.current_semantic_state or "new"
        urgency = _carry_over_urgency(stage)
        reference_time = moved_at or process.updated_at or process.opened_at or now
        days = max(0, (now - reference_time).days)
        result.append(
            {
                "process_id": process.id,
                "candidate": {
                    "id": process.candidate_id,
                    "name": f"{first_name} {last_name}".strip(),
                },
                "job": {
                    "id": process.job_id,
                    "title": title,
                    "client_name": client_name,
                },
                "current_stage": stage,
                "owner_user_id": process.owner_user_id,
                "owner_name": owner_name,
                "owner_active": bool(owner_active),
                "ownership_action_required": not bool(owner_active),
                "credit_user_id": process.credit_user_id,
                "origin_kind": (
                    process.origin_kind.value if process.origin_kind else None
                ),
                "urgency": urgency,
                "urgent": urgency != "normal",
                "days_in_stage": days,
                "opened_at": (
                    process.opened_at.isoformat() if process.opened_at else None
                ),
                "state_version": process.state_version,
            }
        )
    return result


# ── Stały roster (przypisania od Delivery Leada) ──────────────────────────────
#
# Model planowy zakładał rytm, którego w tej firmie nie ma: nowe rekrutacje
# wpadają codziennie, a DL rozdaje je na bieżąco. Bramka wymagająca publikacji
# planu przez HoR odpalałaby się kilka razy dziennie — a jedyne legalne obejście
# (jednorazowy wyjątek) ZERUJE KPI, więc rekruterzy traciliby kredyt za realnie
# wykonaną pracę. Dlatego plan przestaje być wersjonowanym dokumentem i staje
# się stałą listą, do której DL dopisuje przypisania sam.
#
# Zachowany zostaje sufit 5 na osobę — wymuszony przez bazę
# (`UNIQUE (plan_member_id, rank)` + pięciowartościowy enum rang). To jest
# świadomie zostawiony limit WIP, tyle że egzekwowany w MOMENCIE PRZYPISANIA
# (DL od razu widzi „ta osoba ma komplet"), a nie w momencie pracy (rekruter
# dostaje 409 w połowie zadania).


async def ensure_standing_plan(
    db: AsyncSession, *, actor_user_id: Optional[int] = None
) -> RecruitmentPriorityPlan:
    """Zwróć jedyny, nigdy nie zastępowany plan-roster; utwórz gdy nie istnieje.

    Blokada na wierszu stanu serializuje tworzenie, więc dwa równoległe
    przypisania nie zrobią dwóch „stałych" planów.
    """
    state = await ensure_priority_state(db, for_update=True)
    if state.current_plan_id is not None:
        plan = await load_plan(db, state.current_plan_id)
        if plan is not None:
            return plan

    next_version = (
        int(
            await db.scalar(
                select(func.coalesce(func.max(RecruitmentPriorityPlan.version), 0))
            )
            or 0
        )
        + 1
    )
    plan = RecruitmentPriorityPlan(
        version=next_version,
        status=PriorityPlanStatus.published,
        previous_plan_id=None,
        created_by_user_id=actor_user_id,
        published_by_user_id=actor_user_id,
        published_at=utcnow(),
        effective_from=utcnow(),
        notes="Stały roster — przypisania dodaje Delivery Lead na bieżąco.",
        row_version=1,
    )
    db.add(plan)
    await db.flush()
    state.current_plan_id = plan.id
    state.row_version = int(state.row_version or 0) + 1
    await db.flush()
    return plan


async def ensure_plan_member(
    db: AsyncSession, *, plan: RecruitmentPriorityPlan, user_id: int
) -> RecruitmentPriorityPlanMember:
    """Zwróć wiersz członka rosteru dla użytkownika; utwórz gdy brak."""
    member = await db.scalar(
        select(RecruitmentPriorityPlanMember)
        .where(
            RecruitmentPriorityPlanMember.plan_id == plan.id,
            RecruitmentPriorityPlanMember.user_id == user_id,
        )
        .with_for_update()
    )
    if member is not None:
        return member
    member = RecruitmentPriorityPlanMember(
        plan_id=plan.id,
        user_id=user_id,
        status=PriorityMemberStatus.active,
        verification_capacity=DEFAULT_VERIFICATION_CAPACITY,
    )
    db.add(member)
    await db.flush()
    return member


async def next_free_rank(db: AsyncSession, *, member_id: int) -> Optional[PriorityRank]:
    """Najniższa wolna ranga A–E dla członka, albo None gdy komplet."""
    taken = set(
        (
            await db.execute(
                select(RecruitmentPriorityAssignment.rank).where(
                    RecruitmentPriorityAssignment.plan_member_id == member_id
                )
            )
        )
        .scalars()
        .all()
    )
    return next((rank for rank in PriorityRank if rank not in taken), None)
