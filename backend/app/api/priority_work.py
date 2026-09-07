"""HTTP API for Recruitment Priority Lock and carry-over duty."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    HeadOfRecruitmentOnly,
    OperationalUser,
    PriorityDemandCreator,
    PriorityDemandReader,
)
from app.api.recruitment_access import ensure_job_membership
from app.core.config import settings
from app.services.workforce_availability import effective_owner_ids
from app.services.operational_tasks import ownership_payload
from app.services.recruitment_allocation import allocation_lock, assign_operator
from app.core.database import get_db
from app.models.cc_feedback import JobSecondaryCc
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.recruitment_priority import (
    PriorityBlockerCategory,
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityDemandStatus,
    PriorityExceptionStatus,
    PriorityMemberStatus,
    PriorityMode,
    PriorityPlanStatus,
    PriorityRank,
    assignment_position,
    RecruitmentPriorityAlert,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityAuditEvent,
    RecruitmentPriorityBlocker,
    RecruitmentPriorityDemand,
    RecruitmentPriorityException,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityUserMode,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.schemas.priority_work import (
    PriorityAssignmentInput,
    PriorityExceptionCreate,
    PriorityExceptionRevoke,
    PriorityHandoffRequest,
    PriorityPlanMemberInput,
    PriorityUserModeUpdate,
    validate_blocker_evidence,
)
from app.services.priority_work_policy import effective_priority_mode
from app.services.process_backfill import (
    backfill_recruitment_processes,
    compare_shadow_state,
)
from app.services.recruitment_process_commands import handoff_process
from app.services.priority_work_service import (
    OPERATIONAL_ROLES,
    allowed_channels,
    assert_demand_status_transition,
    assignment_gate_states,
    assignment_progress,
    audit_event,
    active_blockers,
    carry_over_rows,
    create_draft_plan,
    current_plan,
    ensure_priority_state,
    load_plan,
    publish_plan,
    replace_draft_members,
    role_values,
    utcnow,
)

router = APIRouter()
WARSAW = ZoneInfo("Europe/Warsaw")


class DemandCreateRequest(BaseModel):
    job_id: int = Field(gt=0)
    urgency: Literal["normal", "urgent", "critical"] = "normal"
    expected_recommendations: int = Field(default=3, ge=3)
    deadline: Optional[date | datetime] = None
    channel: PriorityChannel
    brief_ready: bool = False
    note: str = Field(min_length=1, max_length=4000)


class AssignmentCreateRequest(BaseModel):
    """Bezpośrednie przypisanie rekrutacji przez Delivery Leada.

    `rank` jest opcjonalna i wyłącznie informacyjna — porządkuje listę
    rekrutera, nie blokuje niczego. Gdy pominięta, bierzemy najniższą wolną.
    """

    job_id: int = Field(gt=0)
    assignee_user_id: int = Field(gt=0)
    channel: PriorityChannel
    rank: Optional[PriorityRank] = None
    position: Optional[int] = Field(default=None, gt=0)
    verification_target: int = Field(default=0, ge=0)
    recommendation_target: int = Field(default=0, ge=0)
    note: Optional[str] = Field(default=None, max_length=4000)


class DemandUpdateRequest(BaseModel):
    expected_version: int = Field(gt=0)
    urgency: Optional[Literal["normal", "urgent", "critical"]] = None
    expected_recommendations: Optional[int] = Field(default=None, ge=3)
    deadline: Optional[date | datetime] = None
    channel: Optional[PriorityChannel] = None
    brief_ready: Optional[bool] = None
    note: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    status: Optional[PriorityDemandStatus] = None


class DraftCreateRequest(BaseModel):
    source_plan_id: Optional[int] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=10000)


class AssignmentUpdateRequest(BaseModel):
    job_id: int = Field(gt=0)
    demand_id: Optional[int] = Field(default=None, gt=0)
    rank: Optional[PriorityRank] = None
    position: Optional[int] = Field(default=None, gt=0)
    channel: PriorityChannel
    verification_target: int = Field(gt=0)
    recommendation_target: int = Field(gt=0)
    cc_match: bool = True
    cc_exception_reason: Optional[str] = Field(default=None, max_length=4000)
    extra_slot_reason: Optional[str] = Field(default=None, max_length=4000)


class PlanMemberUpdateRequest(BaseModel):
    user_id: int = Field(gt=0)
    status: PriorityMemberStatus = PriorityMemberStatus.active
    verification_capacity: Optional[int] = Field(default=None, ge=0)
    capacity_reason: Optional[str] = Field(default=None, max_length=4000)
    paused_reason: Optional[str] = Field(default=None, max_length=4000)
    extra_slots_reason: Optional[str] = Field(default=None, max_length=4000)
    assignments: list[AssignmentUpdateRequest] = Field(default_factory=list)


class PlanUpdateRequest(BaseModel):
    expected_version: int = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=10000)
    members: list[PlanMemberUpdateRequest]


class PublishRequest(BaseModel):
    expected_version: int = Field(gt=0)


class BlockerCreateRequest(BaseModel):
    category: PriorityBlockerCategory
    note: str = Field(min_length=1, max_length=4000)
    evidence: Optional[dict[str, Any]] = None

    @field_validator("evidence")
    @classmethod
    def validate_evidence(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        return validate_blocker_evidence(value)


class BlockerUpdateRequest(BaseModel):
    status: PriorityBlockerStatus
    decision_note: Optional[str] = Field(default=None, max_length=4000)


def _is_hor(user: User) -> bool:
    return user.has_role(UserRole.head_of_recruitment)


def _is_delivery_lead(user: User) -> bool:
    return user.has_role(UserRole.delivery_lead)


def _deadline(value: Optional[date | datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=WARSAW).astimezone(timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.combine(value, time(hour=17), tzinfo=WARSAW).astimezone(
        timezone.utc
    )


def _rank_from_urgency(value: str) -> PriorityRank:
    return {
        "critical": PriorityRank.A,
        "urgent": PriorityRank.B,
        "normal": PriorityRank.C,
    }[value]


def _urgency_from_rank(value: Optional[PriorityRank]) -> str:
    if value == PriorityRank.A:
        return "critical"
    if value == PriorityRank.B:
        return "urgent"
    return "normal"


def _mode_value(value: PriorityMode | str) -> str:
    return value.value if isinstance(value, PriorityMode) else str(value)


def _serialize_plan(
    plan: Optional[RecruitmentPriorityPlan],
    *,
    mode: Optional[PriorityMode] = None,
    include_members: bool = False,
) -> Optional[dict[str, Any]]:
    if plan is None:
        return None
    now = utcnow()
    payload: dict[str, Any] = {
        "id": plan.id,
        "version": plan.version,
        "row_version": plan.row_version,
        "status": plan.status.value,
        "previous_plan_id": plan.previous_plan_id,
        "effective_from": plan.effective_from,
        "review_due_at": plan.review_due_at,
        "published_at": plan.published_at,
        "superseded_at": plan.superseded_at,
        "note": plan.notes,
        "notes": plan.notes,
        "overdue": bool(plan.review_due_at and plan.review_due_at < now),
    }
    if mode is not None:
        payload["mode"] = mode.value
    if include_members:
        payload["members"] = [
            {
                "id": member.id,
                "user_id": member.user_id,
                "status": member.status.value,
                "verification_capacity": member.verification_capacity,
                "capacity_reason": member.capacity_reason,
                "paused_reason": member.paused_reason,
                "assignments": [
                    {
                        "id": assignment.id,
                        "demand_id": assignment.demand_id,
                        "job_id": assignment.job_id,
                        "rank": assignment.rank.value if assignment.rank else None,
                        "position": assignment_position(assignment),
                        "channel": assignment.channel.value,
                        "verification_target": assignment.verification_target,
                        "recommendation_target": assignment.recommendation_target,
                        "competence_category_id": (assignment.competence_category_id),
                        "competence_matches": assignment.competence_matches,
                        "cc_exception_reason": assignment.cc_exception_reason,
                        "extra_slot_reason": assignment.extra_slot_reason,
                    }
                    for assignment in member.assignments
                ],
            }
            for member in plan.members
        ]
    return payload


def _serialize_blocker(row: RecruitmentPriorityBlocker) -> dict[str, Any]:
    return {
        "id": row.id,
        "assignment_id": row.assignment_id,
        "category": row.category.value,
        "note": row.description,
        "description": row.description,
        "evidence": row.evidence,
        "status": row.status.value,
        "decision_note": row.decision_reason,
        "decision_reason": row.decision_reason,
        "reported_by_user_id": row.reported_by_user_id,
        "decided_by_user_id": row.decided_by_user_id,
        "resolved_by_user_id": row.resolved_by_user_id,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "resolved_at": row.resolved_at,
    }


async def _serialize_demand(
    db: AsyncSession,
    row: RecruitmentPriorityDemand,
    *,
    current_assignments: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    job = await db.scalar(
        select(Job).where(Job.id == row.job_id).options(selectinload(Job.client))
    )
    requester = (
        await db.scalar(select(User).where(User.id == row.requested_by_user_id))
        if row.requested_by_user_id
        else None
    )
    job_competence_category_ids = (
        {job.competence_category_id}
        if job and job.competence_category_id is not None
        else set()
    )
    job_competence_category_ids.update(
        (
            await db.execute(
                select(JobSecondaryCc.competence_category_id).where(
                    JobSecondaryCc.job_id == row.job_id
                )
            )
        )
        .scalars()
        .all()
    )
    if current_assignments is None:
        plan = await current_plan(db)
        current_assignments = (
            await _assignment_payloads(db, plan.members) if plan else []
        )
    demand_assignments = [
        assignment
        for assignment in current_assignments
        if assignment["demand_id"] == row.id
    ]
    covered = sum(int(item["recommendation_target"]) for item in demand_assignments)
    return {
        "id": row.id,
        "job": {
            "id": row.job_id,
            "title": job.title if job else f"Request #{row.job_id}",
            "client_name": (
                getattr(getattr(job, "client", None), "name", None) if job else None
            ),
            "competence_category_id": (job.competence_category_id if job else None),
            "competence_category_ids": sorted(job_competence_category_ids),
        },
        "job_id": row.job_id,
        "requested_by_id": row.requested_by_user_id,
        "requested_by_name": requester.name if requester else None,
        "status": row.status.value,
        "urgency": _urgency_from_rank(row.proposed_rank),
        "proposed_rank": row.proposed_rank.value if row.proposed_rank else None,
        "expected_recommendations": row.expected_recommendations,
        "deadline": row.due_at,
        "due_at": row.due_at,
        "channel": (
            row.required_channel.value
            if row.required_channel
            else PriorityChannel.mixed.value
        ),
        "required_channel": (
            row.required_channel.value if row.required_channel else None
        ),
        "brief_ready": row.brief_ready,
        "note": row.rationale,
        "rationale": row.rationale,
        "covered_recommendations": covered,
        "assignments_count": len(demand_assignments),
        "assignments": demand_assignments,
        "row_version": row.row_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _assignment_payloads(
    db: AsyncSession,
    members: list[RecruitmentPriorityPlanMember],
    *,
    only_user_id: Optional[int] = None,
    only_job_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    members = [
        member
        for member in members
        if (only_user_id is None or member.user_id == only_user_id)
        and (
            only_job_id is None
            or any(item.job_id == only_job_id for item in member.assignments)
        )
    ]
    all_assignments = [item for member in members for item in member.assignments]
    assignments = [
        item
        for item in all_assignments
        if only_job_id is None or item.job_id == only_job_id
    ]
    # A single-job panel must evaluate its higher priorities using their real
    # progress and sourcing pause, exactly as the command admission policy does.
    progress = await assignment_progress(db, (item.id for item in all_assignments))
    blockers = await active_blockers(db, (item.id for item in all_assignments))
    member_by_id = {member.id: member for member in members}
    job_ids = {item.job_id for item in all_assignments}
    jobs = {
        row.id: row
        for row in (
            (
                await db.execute(
                    select(Job)
                    .where(Job.id.in_(job_ids))
                    .options(selectinload(Job.client))
                )
            )
            .scalars()
            .all()
            if job_ids
            else []
        )
    }
    paused = (
        {job.id for job in jobs.values() if not job.needs_sourcing}
        if settings.RECRUITMENT_ALLOCATION_ENABLED
        else set()
    )
    gate_states: dict[int, str] = {}
    for member in members:
        gate_states.update(
            assignment_gate_states(member, progress, blockers, paused_job_ids=paused)
        )
    user_ids = {member_by_id[item.plan_member_id].user_id for item in assignments}
    users = {
        row.id: row
        for row in (
            (await db.execute(select(User).where(User.id.in_(user_ids))))
            .scalars()
            .all()
            if user_ids
            else []
        )
    }
    payloads: list[dict[str, Any]] = []
    for assignment in assignments:
        member = member_by_id[assignment.plan_member_id]
        job = jobs.get(assignment.job_id)
        user = users.get(member.user_id)
        current = progress.get(
            assignment.id, {"verifications": 0, "recommendations": 0}
        )
        active = blockers.get(assignment.id, [])
        payloads.append(
            {
                "id": assignment.id,
                "user_id": member.user_id,
                "user_name": user.name if user else None,
                **await ownership_payload(
                    db,
                    member.user_id,
                    open_task=bool(
                        job and job.is_open and job.status != JobStatus.closed
                    ),
                ),
                "sourcing_pause_reason": (
                    "favorite" if job.favorite_sourcing_paused else "manual"
                )
                if job and job.id in paused
                else None,
                "rank": assignment.rank.value if assignment.rank else None,
                "position": assignment_position(assignment),
                "channel": assignment.channel.value,
                "job": {
                    "id": assignment.job_id,
                    "title": job.title if job else f"Request #{assignment.job_id}",
                    "client_name": (
                        getattr(getattr(job, "client", None), "name", None)
                        if job
                        else None
                    ),
                },
                "demand_id": assignment.demand_id,
                "verification_target": assignment.verification_target,
                "recommendation_target": assignment.recommendation_target,
                "progress": current,
                "gate_state": gate_states.get(assignment.id, "open"),
                "cc_match": assignment.competence_matches,
                "cc_exception_required": not assignment.competence_matches,
                "cc_exception_reason": assignment.cc_exception_reason,
                "extra_slot_reason": assignment.extra_slot_reason,
                "blocker": _serialize_blocker(active[0]) if active else None,
            }
        )
    return payloads


@router.get("/current")
async def get_current_priority_work(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    mode = await effective_priority_mode(db, current_user.id)
    plan = await current_plan(db)
    return {"mode": mode.value, "plan": _serialize_plan(plan, mode=mode)}


@router.get("/mine")
async def get_my_priority_work(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    mode = await effective_priority_mode(db, current_user.id)
    plan = await current_plan(db)
    owners = await effective_owner_ids(db, current_user.id)
    assignments = (
        await _assignment_payloads(
            db, [member for member in plan.members if member.user_id in owners]
        )
        if plan
        else []
    )
    assignments = [
        item
        for item in assignments
        if item["user_id"] == current_user.id or item.get("substitution")
    ]
    return {
        "mode": mode.value,
        "plan": _serialize_plan(plan, mode=mode),
        "assignments": assignments,
        "carry_over": await carry_over_rows(db, owner_user_id=current_user.id),
    }


@router.get("/team")
async def get_team_priority_work(
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    mode = PriorityMode(settings.RECRUITMENT_PRIORITY_MODE)
    plan = await current_plan(db)
    members_payload: list[dict[str, Any]] = []
    active_users = (
        (
            await db.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        )
        .scalars()
        .all()
    )
    operational_users = [
        user
        for user in active_users
        if user.has_any_role(UserRole.sourcer, UserRole.recruiter, UserRole.tac)
    ]
    plan_members = {member.user_id: member for member in (plan.members if plan else [])}
    all_assignments = await _assignment_payloads(db, plan.members) if plan else []
    competence_rows = (
        await db.execute(
            select(
                UserCompetenceCategory.user_id,
                UserCompetenceCategory.competence_category_id,
            ).where(
                UserCompetenceCategory.user_id.in_(
                    [user.id for user in operational_users]
                )
            )
        )
    ).all()
    competence_by_user: dict[int, list[int]] = {}
    for user_id, competence_category_id in competence_rows:
        competence_by_user.setdefault(user_id, []).append(competence_category_id)
    by_user: dict[int, list[dict[str, Any]]] = {}
    for assignment in all_assignments:
        by_user.setdefault(assignment["user_id"], []).append(assignment)
    all_carry_over = await carry_over_rows(db)
    carry_by_owner: dict[int, list[dict[str, Any]]] = {}
    for item in all_carry_over:
        owner_user_id = item["owner_user_id"]
        if owner_user_id is not None:
            carry_by_owner.setdefault(owner_user_id, []).append(item)
    for user in operational_users:
        member = plan_members.get(user.id)
        carry = carry_by_owner.get(user.id, [])
        members_payload.append(
            {
                "user_id": user.id,
                "user_name": user.name,
                "role": user.role.value,
                "roles": sorted(role_values(user)),
                "allowed_channels": sorted(
                    channel.value for channel in allowed_channels(user)
                ),
                "competence_category_ids": sorted(competence_by_user.get(user.id, [])),
                "status": (
                    member.status.value if member else PriorityMemberStatus.active.value
                ),
                "verification_capacity": (
                    member.verification_capacity if member else 12
                ),
                "paused_reason": member.paused_reason if member else None,
                "capacity_reason": member.capacity_reason if member else None,
                "assignments": by_user.get(user.id, []),
                "carry_over": carry,
                "carry_over_count": len(carry),
                "urgent_carry_over_count": sum(1 for item in carry if item["urgent"]),
            }
        )
    demands = (
        (
            await db.execute(
                select(RecruitmentPriorityDemand).order_by(
                    RecruitmentPriorityDemand.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    unowned_rows = [
        item for item in all_carry_over if item["ownership_action_required"]
    ]
    return {
        "mode": mode.value,
        "plan": _serialize_plan(plan, mode=mode),
        "members": members_payload,
        "demands": [
            await _serialize_demand(
                db,
                row,
                current_assignments=all_assignments,
            )
            for row in demands
        ],
        "unowned_carry_over": unowned_rows,
        "unowned_carry_over_count": len(unowned_rows),
        "overdue": bool(plan and plan.review_due_at and plan.review_due_at < utcnow()),
    }


@router.get("/demands")
async def list_priority_demands(
    current_user: PriorityDemandReader,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    if not (_is_hor(current_user) or _is_delivery_lead(current_user)):
        raise HTTPException(403, "Brak uprawnień do demandów")
    statement = select(RecruitmentPriorityDemand).order_by(
        RecruitmentPriorityDemand.created_at.desc()
    )
    if not _is_hor(current_user):
        statement = statement.join(
            Job,
            Job.id == RecruitmentPriorityDemand.job_id,
        ).where(Job.delivery_lead_id == current_user.id)
    rows = (await db.execute(statement)).scalars().all()
    plan = await current_plan(db)
    assignments = await _assignment_payloads(db, plan.members) if plan else []
    return [
        await _serialize_demand(
            db,
            row,
            current_assignments=assignments,
        )
        for row in rows
    ]


@router.post("/demands", status_code=201)
async def create_priority_demand(
    payload: DemandCreateRequest,
    current_user: PriorityDemandCreator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not _is_delivery_lead(current_user):
        raise HTTPException(403, "Demand może zgłosić Delivery Lead")
    job = await db.scalar(select(Job).where(Job.id == payload.job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Request nie istnieje")
    if job.delivery_lead_id != current_user.id:
        raise HTTPException(403, "Możesz zgłaszać demand tylko dla własnego requestu")
    if not job.is_open:
        raise HTTPException(
            422, "Demand można zgłosić tylko dla requestu przekazanego do searchu"
        )
    existing = await db.scalar(
        select(RecruitmentPriorityDemand.id).where(
            RecruitmentPriorityDemand.job_id == payload.job_id,
            RecruitmentPriorityDemand.status.in_(
                [
                    PriorityDemandStatus.open,
                    PriorityDemandStatus.covered,
                    PriorityDemandStatus.paused,
                ]
            ),
        )
    )
    if existing is not None:
        raise HTTPException(409, "Ten request ma już aktywny demand")
    row = RecruitmentPriorityDemand(
        job_id=payload.job_id,
        requested_by_user_id=current_user.id,
        proposed_rank=_rank_from_urgency(payload.urgency),
        expected_recommendations=payload.expected_recommendations,
        due_at=_deadline(payload.deadline),
        required_channel=payload.channel,
        rationale=payload.note,
        brief_ready=payload.brief_ready,
        row_version=1,
    )
    db.add(row)
    await db.flush()
    audit_event(
        db,
        "demand_created",
        actor_user_id=current_user.id,
        job_id=row.job_id,
        payload={"demand_id": row.id},
    )
    await db.commit()
    await db.refresh(row)
    return await _serialize_demand(db, row)


@router.patch("/demands/{demand_id}")
async def update_priority_demand(
    demand_id: int,
    payload: DemandUpdateRequest,
    current_user: PriorityDemandReader,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(RecruitmentPriorityDemand)
        .where(RecruitmentPriorityDemand.id == demand_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Demand nie istnieje")
    if not (_is_hor(current_user) or _is_delivery_lead(current_user)):
        raise HTTPException(403, "Demand może zmieniać Delivery Lead lub HoR")
    if not _is_hor(current_user):
        current_delivery_lead_id = await db.scalar(
            select(Job.delivery_lead_id).where(Job.id == row.job_id).with_for_update()
        )
        if current_delivery_lead_id != current_user.id:
            raise HTTPException(
                403,
                "Demand może zmieniać aktualny Delivery Lead requestu.",
            )
    if row.row_version != payload.expected_version:
        raise HTTPException(
            409,
            {
                "code": "PRIORITY_VERSION_CONFLICT",
                "entity": "demand",
                "message": "Demand został zmieniony. Odśwież widok.",
            },
        )
    changes = payload.model_fields_set
    if "urgency" in changes and payload.urgency:
        row.proposed_rank = _rank_from_urgency(payload.urgency)
    if "expected_recommendations" in changes:
        # `Optional[int]` w schemacie koduje „pole nieobecne", nie „wyczyść
        # wartość" — kolumna jest NOT NULL z CHECK >= 3, więc jawny null
        # kończył się IntegrityError na commicie i wychodził jako 500.
        # Sąsiednie pola null ignorują po cichu; tu mówimy głośno, bo ciche
        # 200 znaczyłoby dla UI „zapisano", a nic nie zostałoby zapisane.
        if payload.expected_recommendations is None:
            raise HTTPException(
                422, "expected_recommendations nie może być puste (minimum 3)"
            )
        row.expected_recommendations = payload.expected_recommendations
    if "deadline" in changes:
        row.due_at = _deadline(payload.deadline)
    if "channel" in changes:
        row.required_channel = payload.channel
    if "brief_ready" in changes:
        row.brief_ready = bool(payload.brief_ready)
    if "note" in changes and payload.note:
        row.rationale = payload.note
    if "status" in changes and payload.status:
        assert_demand_status_transition(
            row.status,
            payload.status,
            actor_is_hor=_is_hor(current_user),
        )
        row.status = payload.status
    row.row_version += 1
    audit_event(
        db,
        "demand_updated",
        actor_user_id=current_user.id,
        job_id=row.job_id,
        payload={"demand_id": row.id, "fields": sorted(changes)},
    )
    await db.commit()
    await db.refresh(row)
    return await _serialize_demand(db, row)


@router.post("/assignments", status_code=201)
async def create_priority_assignment(
    payload: AssignmentCreateRequest,
    current_user: PriorityDemandReader,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delivery Lead przypisuje własną rekrutację konkretnej osobie.

    Bez publikacji planu i bez udziału HoR — plan jest stałym rosterem, do
    którego DL dopisuje na bieżąco. HoR widzi całość w `GET /team` i reaguje,
    gdy ktoś jest przeciążony.
    """
    is_hor = _is_hor(current_user)
    if not (is_hor or _is_delivery_lead(current_user)):
        raise HTTPException(
            403, "Przypisać może Delivery Lead albo Head of Recruitment"
        )

    await allocation_lock(db)
    job = await db.scalar(select(Job).where(Job.id == payload.job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Request nie istnieje")
    if not is_hor and job.delivery_lead_id != current_user.id:
        raise HTTPException(403, "Możesz przypisywać tylko własne requesty")
    if not job.is_open:
        raise HTTPException(422, "Przypisać można tylko request przekazany do searchu")

    assignee = await db.scalar(select(User).where(User.id == payload.assignee_user_id))
    if assignee is None or not assignee.is_active:
        raise HTTPException(404, "Nieaktywny lub brakujący użytkownik")
    if not (role_values(assignee) & {role.value for role in OPERATIONAL_ROLES}):
        raise HTTPException(422, "Przypisać można tylko rekruterowi / sourcerowi / TAC")
    if payload.channel not in allowed_channels(assignee):
        raise HTTPException(
            422,
            f"Kanał {payload.channel.value} jest poza rolą tej osoby",
        )

    position = payload.position
    if payload.rank is not None:
        legacy_position = ord(payload.rank.value) - 64
        if position is not None and position != legacy_position:
            raise HTTPException(422, "Pozycja i ranga wskazują różne miejsca")
        position = legacy_position
    assignment = await assign_operator(
        db,
        job=job,
        assignee=assignee,
        channel=payload.channel,
        actor_user_id=current_user.id,
        source="delivery_lead",
        as_owner=False,
        position=position,
        verification_target=payload.verification_target,
        recommendation_target=payload.recommendation_target,
    )
    await db.commit()
    return {
        "id": assignment.id,
        "job_id": job.id,
        "assignee_user_id": assignee.id,
        "rank": assignment.rank.value if assignment.rank else None,
        "position": assignment.position,
        "channel": assignment.channel.value,
    }


@router.delete("/assignments/{assignment_id}", status_code=204)
async def delete_priority_assignment(
    assignment_id: int,
    current_user: PriorityDemandReader,
    db: AsyncSession = Depends(get_db),
):
    """Zdejmij przypisanie. Praca w toku (carry-over) trwa dalej."""
    is_hor = _is_hor(current_user)
    if not (is_hor or _is_delivery_lead(current_user)):
        raise HTTPException(403, "Zdjąć może Delivery Lead albo Head of Recruitment")

    await allocation_lock(db)
    assignment = await db.scalar(
        select(RecruitmentPriorityAssignment)
        .where(RecruitmentPriorityAssignment.id == assignment_id)
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(404, "Przypisanie nie istnieje")

    job = await db.scalar(select(Job).where(Job.id == assignment.job_id))
    if job is None:
        raise HTTPException(404, "Request nie istnieje")
    if not is_hor and job.delivery_lead_id != current_user.id:
        raise HTTPException(403, "Możesz zdejmować tylko z własnych requestów")

    member_row = (
        await db.execute(
            select(
                RecruitmentPriorityPlanMember.user_id,
                RecruitmentPriorityPlanMember.plan_id,
            ).where(RecruitmentPriorityPlanMember.id == assignment.plan_member_id)
        )
    ).first()
    member_user_id = member_row.user_id if member_row else None
    member_plan_id = member_row.plan_id if member_row else None

    audit_event(
        db,
        "assignment_removed",
        actor_user_id=current_user.id,
        plan_id=member_plan_id,
        subject_user_id=member_user_id,
        job_id=assignment.job_id,
        assignment_id=assignment.id,
        payload={
            "rank": assignment.rank.value if assignment.rank else None,
            "position": assignment_position(assignment),
            "by_delivery_lead": not is_hor,
        },
    )
    if job.recruiter_id == member_user_id:
        published = await db.scalar(
            select(RecruitmentPriorityPlan.id).where(
                RecruitmentPriorityPlan.id == member_plan_id,
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            )
        )
        if published is not None:
            job.recruiter_id = None
    await db.delete(assignment)
    await db.commit()


@router.post("/plans/draft", status_code=201)
async def create_priority_plan_draft(
    payload: DraftCreateRequest,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    plan = await create_draft_plan(
        db,
        actor_user_id=current_user.id,
        source_plan_id=payload.source_plan_id,
        notes=payload.note,
    )
    await db.commit()
    plan = (await load_plan(db, plan.id)) or plan
    return _serialize_plan(plan, include_members=True) or {}


def _plan_draft_invalid(exc: PydanticValidationError) -> HTTPException:
    """Zamienia ValidationError z modelu domenowego na 422 z polami.

    Walidatory `mode="after"` w `PriorityAssignmentInput` /
    `PriorityPlanMemberInput` rzucają `ValidationError`, a FastAPI konwertuje
    tylko `RequestValidationError` (parsowanie żądania) i
    `ResponseValidationError`. Modele budowane RĘCZNIE w handlerze wychodziły
    więc jako nieobsłużony 500 z pustą treścią i komunikat nigdy nie docierał
    do UI. Reguła „pauza wymaga uzasadnienia" nie ma odpowiednika w serwisie,
    więc pydantic jest jej JEDYNYM miejscem egzekwowania.
    """
    return HTTPException(
        422,
        {
            "code": "PRIORITY_PLAN_INVALID",
            "errors": exc.errors(include_url=False),
        },
    )


async def _resolve_member_inputs(
    db: AsyncSession, members: list[PlanMemberUpdateRequest]
) -> list[PriorityPlanMemberInput]:
    resolved: list[PriorityPlanMemberInput] = []
    for member in members:
        assignments: list[PriorityAssignmentInput] = []
        for item in member.assignments:
            demand_id = item.demand_id
            if demand_id is None:
                demand_id = await db.scalar(
                    select(RecruitmentPriorityDemand.id)
                    .where(
                        RecruitmentPriorityDemand.job_id == item.job_id,
                        RecruitmentPriorityDemand.status.in_(
                            [
                                PriorityDemandStatus.open,
                                PriorityDemandStatus.covered,
                                PriorityDemandStatus.paused,
                            ]
                        ),
                    )
                    .order_by(RecruitmentPriorityDemand.id.desc())
                    .limit(1)
                )
            if demand_id is None:
                raise HTTPException(
                    422, f"Request #{item.job_id} nie ma aktywnego demandu"
                )
            extra_reason = item.extra_slot_reason or member.extra_slots_reason
            try:
                assignment_input = PriorityAssignmentInput(
                    demand_id=demand_id,
                    job_id=item.job_id,
                    rank=item.rank,
                    position=item.position,
                    channel=item.channel,
                    verification_target=item.verification_target,
                    recommendation_target=item.recommendation_target,
                    competence_matches=item.cc_match,
                    cc_exception_reason=item.cc_exception_reason,
                    extra_slot_reason=extra_reason,
                )
            except PydanticValidationError as exc:
                raise _plan_draft_invalid(exc) from exc
            assignments.append(assignment_input)
        capacity = member.verification_capacity
        if capacity is None:
            capacity = sum(item.verification_target for item in assignments)
        try:
            member_input = PriorityPlanMemberInput(
                user_id=member.user_id,
                status=member.status,
                verification_capacity=capacity,
                capacity_reason=(member.capacity_reason or member.extra_slots_reason),
                paused_reason=member.paused_reason,
                assignments=assignments,
            )
        except PydanticValidationError as exc:
            raise _plan_draft_invalid(exc) from exc
        resolved.append(member_input)
    return resolved


@router.put("/plans/{plan_id}")
async def update_priority_plan_draft(
    plan_id: int,
    payload: PlanUpdateRequest,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    members = await _resolve_member_inputs(db, payload.members)
    plan = await replace_draft_members(
        db,
        plan_id=plan_id,
        expected_version=payload.expected_version,
        members=members,
        actor_user_id=current_user.id,
        notes=payload.note,
    )
    await db.commit()
    plan = (await load_plan(db, plan.id)) or plan
    return _serialize_plan(plan, include_members=True) or {}


@router.post("/plans/{plan_id}/publish")
async def publish_priority_plan(
    plan_id: int,
    payload: PublishRequest,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await allocation_lock(db)
    plan = await publish_plan(
        db,
        plan_id=plan_id,
        expected_version=payload.expected_version,
        actor_user_id=current_user.id,
    )
    await db.commit()
    plan = (await load_plan(db, plan.id)) or plan
    return _serialize_plan(plan, include_members=True) or {}


@router.get("/jobs/{job_id}")
async def get_job_priority_context(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = await db.scalar(select(Job.id).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, "Request nie istnieje")
    # Zakres zasobu, nie tylko rola: odpowiedź niesie nazwiska przypisanych,
    # treść blockerów i surowe `evidence`. Bez tej bramki był to JEDYNY
    # osiągalny dla ról operacyjnych sposób odczytu alokacji per-osoba w CUDZEJ
    # ofercie — `/mine` zawęża do siebie, `/team` jest HoR-only, a `/current`
    # nie zwraca danych per-osoba. Wspólny helper, nie własna kopia reguły.
    await ensure_job_membership(db, current_user, job_id)
    mode = await effective_priority_mode(db, current_user.id)
    plan = await current_plan(db)
    assignments = (
        await _assignment_payloads(db, plan.members, only_job_id=job_id) if plan else []
    )
    blockers = (
        (
            await db.execute(
                select(RecruitmentPriorityBlocker)
                .join(
                    RecruitmentPriorityAssignment,
                    RecruitmentPriorityAssignment.id
                    == RecruitmentPriorityBlocker.assignment_id,
                )
                .where(
                    RecruitmentPriorityAssignment.job_id == job_id,
                    RecruitmentPriorityBlocker.status.in_(
                        [
                            PriorityBlockerStatus.pending,
                            PriorityBlockerStatus.accepted,
                        ]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    carry_count = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id)).where(
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.status == ProcessStatus.open,
            )
        )
        or 0
    )
    return {
        "mode": mode.value,
        "plan": _serialize_plan(plan, mode=mode),
        "assignments": assignments,
        "carry_over_count": carry_count,
        "blockers": [_serialize_blocker(row) for row in blockers],
    }


@router.post("/assignments/{assignment_id}/blockers", status_code=201)
async def create_priority_blocker(
    assignment_id: int,
    payload: BlockerCreateRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assignment = await db.scalar(
        select(RecruitmentPriorityAssignment)
        .join(
            RecruitmentPriorityPlanMember,
            RecruitmentPriorityPlanMember.id
            == RecruitmentPriorityAssignment.plan_member_id,
        )
        .join(
            RecruitmentPriorityPlan,
            RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
        )
        .where(RecruitmentPriorityAssignment.id == assignment_id)
        .where(RecruitmentPriorityPlan.status == PriorityPlanStatus.published)
        .options(selectinload(RecruitmentPriorityAssignment.plan_member))
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(404, "Aktywny opublikowany assignment nie istnieje")
    if not _is_hor(
        current_user
    ) and assignment.plan_member.user_id not in await effective_owner_ids(
        db, current_user.id
    ):
        raise HTTPException(403, "Blocker może zgłosić właściciel assignmentu")
    active = await db.scalar(
        select(RecruitmentPriorityBlocker.id).where(
            RecruitmentPriorityBlocker.assignment_id == assignment_id,
            RecruitmentPriorityBlocker.status.in_(
                [PriorityBlockerStatus.pending, PriorityBlockerStatus.accepted]
            ),
            RecruitmentPriorityBlocker.resolved_at.is_(None),
        )
    )
    if active is not None:
        raise HTTPException(409, "Assignment ma już aktywny blocker")
    row = RecruitmentPriorityBlocker(
        assignment_id=assignment_id,
        reported_by_user_id=current_user.id,
        category=payload.category,
        description=payload.note,
        evidence=payload.evidence,
        status=PriorityBlockerStatus.pending,
    )
    db.add(row)
    await db.flush()
    audit_event(
        db,
        "blocker_reported",
        actor_user_id=current_user.id,
        assignment_id=assignment_id,
        job_id=assignment.job_id,
        payload={"blocker_id": row.id, "category": row.category.value},
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_blocker(row)


@router.patch("/blockers/{blocker_id}")
async def update_priority_blocker(
    blocker_id: int,
    payload: BlockerUpdateRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(RecruitmentPriorityBlocker)
        .where(RecruitmentPriorityBlocker.id == blocker_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Blocker nie istnieje")
    now = utcnow()
    if payload.status in {
        PriorityBlockerStatus.accepted,
        PriorityBlockerStatus.rejected,
    }:
        if not _is_hor(current_user):
            raise HTTPException(403, "Decyzję o blockerze podejmuje HoR")
        if row.status != PriorityBlockerStatus.pending:
            raise HTTPException(409, "Blocker nie czeka już na decyzję")
        row.status = payload.status
        row.decided_by_user_id = current_user.id
        row.decided_at = now
        row.decision_reason = payload.decision_note
        event_type = "blocker_decided"
    elif payload.status == PriorityBlockerStatus.resolved:
        # Warunek wstępny na stanie ŹRÓDŁOWYM, lustrzany do 409 z gałęzi
        # decyzji wyżej. Bez niego blocker `rejected` dawało się „domknąć"
        # ponownie, a `decision_note` nadpisywało `decision_reason` —
        # uzasadnienie odrzucenia od HoR-a przepadało, bo audit event zapisuje
        # tylko id i nowy status, więc poprzedniej treści nie da się odtworzyć.
        if row.status not in {
            PriorityBlockerStatus.pending,
            PriorityBlockerStatus.accepted,
        }:
            raise HTTPException(409, "Blocker jest już zamknięty")
        assignment = await db.scalar(
            select(RecruitmentPriorityAssignment)
            .where(RecruitmentPriorityAssignment.id == row.assignment_id)
            .options(selectinload(RecruitmentPriorityAssignment.plan_member))
            .with_for_update()
        )
        if not _is_hor(current_user) and (
            assignment is None
            or assignment.plan_member.user_id
            not in await effective_owner_ids(db, current_user.id)
        ):
            raise HTTPException(403, "Brak uprawnień do zamknięcia blockera")
        row.status = PriorityBlockerStatus.resolved
        row.resolved_by_user_id = current_user.id
        row.resolved_at = now
        if payload.decision_note:
            row.decision_reason = payload.decision_note
        event_type = "blocker_resolved"
    else:
        raise HTTPException(422, "Nieobsługiwany status blockera")
    audit_event(
        db,
        event_type,
        actor_user_id=current_user.id,
        assignment_id=row.assignment_id,
        payload={"blocker_id": row.id, "status": row.status.value},
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_blocker(row)


@router.post("/processes/{process_id}/handoff")
async def handoff_priority_process(
    process_id: int,
    payload: PriorityHandoffRequest,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if payload.process_id != process_id:
        raise HTTPException(422, "process_id w ścieżce i body muszą być zgodne")
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(RecruitmentProcess.id == process_id)
        .with_for_update()
    )
    if process is None or process.status != ProcessStatus.open:
        raise HTTPException(404, "Aktywny proces nie istnieje")
    if process.state_version != payload.expected_process_version:
        raise HTTPException(
            409,
            {
                "code": "PRIORITY_VERSION_CONFLICT",
                "entity": "process",
                "message": "Proces został zmieniony. Odśwież kolejkę.",
            },
        )
    new_owner = await db.scalar(
        select(User).where(
            User.id == payload.new_owner_user_id,
            User.is_active.is_(True),
        )
    )
    if new_owner is None or not new_owner.has_any_role(
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
    ):
        raise HTTPException(422, "Nowy owner nie jest aktywnym rekruterem")
    previous_owner = process.owner_user_id
    process = await handoff_process(
        db,
        candidate_id=process.candidate_id,
        job_id=process.job_id,
        new_owner_user_id=new_owner.id,
        actor_user=current_user,
    )
    audit_event(
        db,
        "process_handoff",
        actor_user_id=current_user.id,
        subject_user_id=new_owner.id,
        job_id=process.job_id,
        process_id=process.id,
        payload={
            "previous_owner_user_id": previous_owner,
            "new_owner_user_id": new_owner.id,
            "reason": payload.reason,
            "credit_user_id": process.credit_user_id,
        },
    )
    await db.commit()
    rows = await carry_over_rows(db, owner_user_id=new_owner.id)
    return next(row for row in rows if row["process_id"] == process.id)


@router.get("/exceptions")
async def list_priority_exceptions(
    _current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[PriorityExceptionStatus] = Query(
        default=None, alias="status"
    ),
) -> list[dict[str, Any]]:
    statement = select(RecruitmentPriorityException).order_by(
        RecruitmentPriorityException.created_at.desc()
    )
    if status_filter:
        statement = statement.where(
            RecruitmentPriorityException.status == status_filter
        )
    rows = (await db.execute(statement)).scalars().all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "job_id": row.job_id,
            "status": row.status.value,
            "reason": row.reason,
            "valid_from": row.valid_from,
            "expires_at": row.expires_at,
            "consumed_at": row.consumed_at,
            "consumed_candidate_id": row.consumed_candidate_id,
            "consumed_process_id": row.consumed_process_id,
            "origin_assignment_id": row.origin_assignment_id,
        }
        for row in rows
    ]


@router.post("/exceptions", status_code=201)
async def create_priority_exception(
    payload: PriorityExceptionCreate,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if payload.expires_at - payload.valid_from > timedelta(days=7):
        raise HTTPException(422, "Jednorazowy wyjątek może być ważny maks. 7 dni")
    target_user = await db.scalar(
        select(User.id)
        .where(User.id == payload.user_id, User.is_active.is_(True))
        .with_for_update()
    )
    target_job = await db.scalar(
        select(Job.id).where(Job.id == payload.job_id).with_for_update()
    )
    if target_user is None or target_job is None:
        raise HTTPException(422, "Użytkownik lub request nie istnieje")
    if payload.origin_assignment_id is not None:
        origin = (
            await db.execute(
                select(
                    RecruitmentPriorityAssignment.job_id,
                    RecruitmentPriorityPlanMember.user_id,
                )
                .join(
                    RecruitmentPriorityPlanMember,
                    RecruitmentPriorityPlanMember.id
                    == RecruitmentPriorityAssignment.plan_member_id,
                )
                .where(RecruitmentPriorityAssignment.id == payload.origin_assignment_id)
            )
        ).first()
        if (
            origin is None
            or origin.job_id != payload.job_id
            or origin.user_id != payload.user_id
        ):
            raise HTTPException(
                422,
                (
                    "origin_assignment_id musi należeć do wskazanego "
                    "użytkownika i requestu."
                ),
            )
    existing = await db.scalar(
        select(RecruitmentPriorityException.id).where(
            RecruitmentPriorityException.user_id == payload.user_id,
            RecruitmentPriorityException.job_id == payload.job_id,
            RecruitmentPriorityException.status == PriorityExceptionStatus.approved,
        )
    )
    if existing is not None:
        raise HTTPException(
            409,
            {
                "code": "PRIORITY_EXCEPTION_EXISTS",
                "message": "Dla tej osoby i requestu istnieje już aktywny wyjątek.",
            },
        )
    row = RecruitmentPriorityException(
        user_id=payload.user_id,
        job_id=payload.job_id,
        granted_by_user_id=current_user.id,
        origin_assignment_id=payload.origin_assignment_id,
        status=PriorityExceptionStatus.approved,
        reason=payload.reason,
        valid_from=payload.valid_from,
        expires_at=payload.expires_at,
    )
    db.add(row)
    await db.flush()
    audit_event(
        db,
        "exception_granted",
        actor_user_id=current_user.id,
        subject_user_id=payload.user_id,
        job_id=payload.job_id,
        exception_id=row.id,
        payload={
            "reason": payload.reason,
            "expires_at": payload.expires_at.isoformat(),
        },
    )
    await db.commit()
    return {
        "id": row.id,
        "user_id": row.user_id,
        "job_id": row.job_id,
        "status": row.status.value,
        "reason": row.reason,
        "valid_from": row.valid_from,
        "expires_at": row.expires_at,
    }


@router.post("/exceptions/{exception_id}/revoke")
async def revoke_priority_exception(
    exception_id: int,
    payload: PriorityExceptionRevoke,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(RecruitmentPriorityException)
        .where(RecruitmentPriorityException.id == exception_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Wyjątek nie istnieje")
    if row.status != PriorityExceptionStatus.approved:
        raise HTTPException(409, "Tylko niewykorzystany wyjątek można odwołać")
    row.status = PriorityExceptionStatus.revoked
    audit_event(
        db,
        "exception_revoked",
        actor_user_id=current_user.id,
        subject_user_id=row.user_id,
        job_id=row.job_id,
        exception_id=row.id,
        payload={"reason": payload.reason},
    )
    await db.commit()
    return {"ok": True, "id": row.id, "status": row.status.value}


@router.put("/users/{user_id}/mode")
async def update_priority_user_mode(
    user_id: int,
    payload: PriorityUserModeUpdate,
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None or not target.is_active:
        raise HTTPException(404, "User nie istnieje lub jest nieaktywny")
    if not target.has_any_role(
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
    ):
        raise HTTPException(
            422,
            "Tryb Priority Work dotyczy wyłącznie rekrutera, sourcera lub TAC.",
        )
    if payload.mode == PriorityMode.enforce:
        plan = await current_plan(db)
        member = (
            next(
                (
                    item
                    for item in (plan.members if plan else [])
                    if item.user_id == user_id
                    and item.status == PriorityMemberStatus.active
                    and bool(item.assignments)
                ),
                None,
            )
            if plan
            else None
        )
        if member is None:
            raise HTTPException(
                409,
                {
                    "code": "PRIORITY_ENFORCE_REQUIRES_PLAN",
                    "message": "Nie można włączyć enforce bez poprawnego aktywnego planu.",
                },
            )
    row = await db.scalar(
        select(RecruitmentPriorityUserMode)
        .where(RecruitmentPriorityUserMode.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        row = RecruitmentPriorityUserMode(
            user_id=user_id,
            mode=payload.mode,
            set_by_user_id=current_user.id,
            reason=payload.reason,
            effective_at=utcnow(),
        )
        db.add(row)
    else:
        row.mode = payload.mode
        row.set_by_user_id = current_user.id
        row.reason = payload.reason
        row.effective_at = utcnow()
    audit_event(
        db,
        "user_mode_updated",
        actor_user_id=current_user.id,
        subject_user_id=user_id,
        payload={"mode": payload.mode.value, "reason": payload.reason},
    )
    await db.commit()
    return {
        "user_id": row.user_id,
        "mode": row.mode.value,
        "set_by_user_id": row.set_by_user_id,
        "reason": row.reason,
        "effective_at": row.effective_at,
    }


@router.get("/status")
async def get_priority_status(
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    state = await ensure_priority_state(db)
    plan = await current_plan(db)
    mode = PriorityMode(settings.RECRUITMENT_PRIORITY_MODE)
    metrics = state.metrics or {}
    return {
        "mode": mode.value,
        "current_plan_id": state.current_plan_id,
        "plan_overdue": bool(
            plan and plan.review_due_at and plan.review_due_at < utcnow()
        ),
        "users_without_coverage": int(metrics.get("users_without_coverage", 0)),
        "unowned_carry_over": int(metrics.get("unowned_carry_over", 0)),
        "eligibility_coverage_percent": float(
            metrics.get("eligibility_coverage_percent", 0)
        ),
        "shadow_violation_count": int(metrics.get("shadow_violation_count", 0)),
        "worker_heartbeat_at": state.worker_heartbeat_at,
        "last_reconciled_at": state.last_reconciled_at,
        "last_alert_sweep_at": state.last_alert_sweep_at,
        "last_error": state.last_error,
        "metrics": metrics,
    }


@router.get("/reconciliation/status")
async def get_priority_reconciliation_status(
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    health = await get_priority_status(current_user, db)
    shadow = await compare_shadow_state(db, sample_limit=20)
    return {**health, "shadow_compare": shadow}


@router.post("/reconciliation/run")
async def run_priority_reconciliation(
    current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
    limit_pairs: int = Query(500, ge=1, le=5000),
    resync_stale: bool = False,
) -> dict[str, Any]:
    result = await backfill_recruitment_processes(
        db,
        limit_pairs=limit_pairs,
        resync_stale=resync_stale,
    )
    audit_event(
        db,
        "legacy_reconciliation_run",
        actor_user_id=current_user.id,
        payload={
            "limit_pairs": limit_pairs,
            "resync_stale": resync_stale,
            "result": result,
        },
    )
    await db.commit()
    return {
        "result": result,
        "shadow_compare": await compare_shadow_state(db, sample_limit=20),
    }


@router.get("/alerts")
async def list_priority_alerts(
    _current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    statement = select(RecruitmentPriorityAlert).order_by(
        RecruitmentPriorityAlert.resolved_at.is_(None).desc(),
        RecruitmentPriorityAlert.last_seen_at.desc(),
    )
    if not include_resolved:
        statement = statement.where(RecruitmentPriorityAlert.resolved_at.is_(None))
    rows = (await db.execute(statement)).scalars().all()
    return [
        {
            "id": row.id,
            "dedupe_key": row.dedupe_key,
            "kind": row.kind,
            "severity": row.severity.value,
            "user_id": row.user_id,
            "job_id": row.job_id,
            "assignment_id": row.assignment_id,
            "payload": row.payload,
            "occurrence_count": row.occurrence_count,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "resolved_at": row.resolved_at,
        }
        for row in rows
    ]


@router.get("/audit")
async def list_priority_audit(
    _current_user: HeadOfRecruitmentOnly,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(RecruitmentPriorityAuditEvent)
                .order_by(RecruitmentPriorityAuditEvent.occurred_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "actor_user_id": row.actor_user_id,
            "plan_id": row.plan_id,
            "subject_user_id": row.subject_user_id,
            "job_id": row.job_id,
            "assignment_id": row.assignment_id,
            "process_id": row.process_id,
            "exception_id": row.exception_id,
            "payload": row.payload,
            "occurred_at": row.occurred_at,
            "correlation_id": row.correlation_id,
        }
        for row in rows
    ]
