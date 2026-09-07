"""Deterministic allocation: current work first, competencies as eligibility/tie-breaker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.candidate_contact import CandidateContactCase
from app.models.cc_feedback import JobSecondaryCc
from app.models.competence_category import UserCompetenceCategory
from app.models.contract_onboarding import ContractOnboardingItem, OnboardingItemStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_allocation import (
    RecruitmentAllocationRequest,
    RecruitmentAllocationState,
)
from app.models.recruitment_allocation import RecruitmentAllocationEvent
from app.models.recruitment_priority import (
    PriorityChannel,
    PriorityDemandStatus,
    PriorityMemberStatus,
    PriorityPlanStatus,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityDemand,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    legacy_priority_rank,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.models.proposal_snapshot import (
    ProposalSnapshot,
    SOURCE_HANDOFF,
    STATUS_PENDING,
)
from app.core.config import settings
from app.services.job_readiness import job_readiness_blockers
from app.services.priority_work_service import (
    OPERATIONAL_ROLES,
    allowed_channels,
    audit_event,
    ensure_plan_member,
    ensure_standing_plan,
    next_free_position,
    role_values,
)
from app.services.workforce_availability import WARSAW, WorkforceContext

ALLOCATION_LOCK = 734092771
CONTACT_OPEN_STATES = (
    "queued",
    "callback_due",
    "cooldown",
    "handoff_pending",
    "blocked_no_phone",
    "awaiting_capacity",
)


@dataclass
class Workload:
    searches: set[int] = field(default_factory=set)
    favorites: set[int] = field(default_factory=set)
    own_jobs: set[int] = field(default_factory=set)
    inherited_jobs: set[int] = field(default_factory=set)
    overdue: set[tuple[str, int]] = field(default_factory=set)
    today: set[tuple[str, int]] = field(default_factory=set)
    inherited_tasks: set[tuple[str, int]] = field(default_factory=set)
    candidate_processes: set[tuple[int, int]] = field(default_factory=set)
    contacts: set[int] = field(default_factory=set)

    @property
    def followups(self) -> int:
        process_candidates = {candidate for candidate, _ in self.candidate_processes}
        return len(self.candidate_processes) + len(self.contacts - process_candidates)

    @property
    def comparison(self) -> tuple[int, int, int, int]:
        return len(self.searches), len(self.overdue), len(self.today), self.followups

    def as_payload(self) -> dict:
        return {
            "active_searches": len(self.searches),
            "with_favorite": len(self.favorites),
            "overdue_tasks": len(self.overdue),
            "tasks_today": len(self.today),
            "candidate_followups": self.followups,
            "inherited_recruitments": len(self.inherited_jobs - self.own_jobs),
            "inherited_tasks": len(self.inherited_tasks),
        }

    def add_task(
        self,
        kind: str,
        task_id: int,
        due: datetime | date | None,
        *,
        now: datetime,
        inherited: bool,
    ):
        key = (kind, task_id)
        if inherited:
            self.inherited_tasks.add(key)
        if due is None:
            return
        if not isinstance(due, datetime):
            due = datetime.combine(due, time.max, tzinfo=WARSAW)
        elif due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due < now:
            self.overdue.add(key)
        elif due.astimezone(WARSAW).date() == now.astimezone(WARSAW).date():
            self.today.add(key)


async def allocation_lock(db: AsyncSession) -> None:
    """All automatic and manual ownership commands acquire this BEFORE job locks."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": ALLOCATION_LOCK}
    )


async def enqueue_allocation(db, *, job, actor_user_id, channel):
    request = await db.scalar(
        select(RecruitmentAllocationRequest)
        .where(RecruitmentAllocationRequest.job_id == job.id)
        .with_for_update()
    )
    if request is None:
        request = RecruitmentAllocationRequest(
            job_id=job.id, requested_by_user_id=actor_user_id, channel=channel.value
        )
        db.add(request)
    elif request.status == "queued":
        return request
    else:
        request.status = "queued"
        request.channel = channel.value
        request.created_at = datetime.now(timezone.utc)
        request.assigned_user_id = None
        request.suggested_user_id = None
    db.add(RecruitmentAllocationEvent(topic="request_handed_off"))
    await db.flush()
    return request


async def load_workloads(
    db: AsyncSession, workforce: WorkforceContext, *, now: datetime
) -> dict[int, Workload]:
    loads: dict[int, Workload] = {}

    def target(owner_id):
        if owner_id is None:
            return None, False
        performer = workforce.performer(owner_id)
        return loads.setdefault(performer, Workload()), performer != owner_id

    jobs = list(
        (
            await db.scalars(
                select(Job)
                .where(Job.is_open.is_(True), Job.status != JobStatus.closed)
                .options(
                    load_only(
                        Job.id,
                        Job.recruiter_id,
                        Job.needs_sourcing,
                        Job.favorite_candidate_id,
                    )
                )
            )
        ).all()
    )
    by_id = {job.id: job for job in jobs}
    favorite_stages = (
        dict(
            (
                await db.execute(
                    select(CandidateStage.job_id, CandidateStage.stage)
                    .join(Job, Job.id == CandidateStage.job_id)
                    .where(
                        Job.id.in_(by_id),
                        CandidateStage.candidate_id == Job.favorite_candidate_id,
                    )
                    .distinct(CandidateStage.job_id)
                    .order_by(
                        CandidateStage.job_id,
                        CandidateStage.moved_at.desc(),
                        CandidateStage.id.desc(),
                    )
                )
            ).all()
        )
        if by_id
        else {}
    )
    commitments = set(
        (job.recruiter_id, job.id) for job in jobs if job.recruiter_id is not None
    )
    commitments.update(
        (
            await db.execute(
                select(
                    RecruitmentPriorityPlanMember.user_id,
                    RecruitmentPriorityAssignment.job_id,
                )
                .join(
                    RecruitmentPriorityAssignment,
                    RecruitmentPriorityAssignment.plan_member_id
                    == RecruitmentPriorityPlanMember.id,
                )
                .join(
                    RecruitmentPriorityPlan,
                    RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
                )
                .where(
                    RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                    RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                    RecruitmentPriorityAssignment.job_id.in_(by_id),
                )
            )
        ).all()
    )
    for owner, job_id in commitments:
        load, inherited = target(owner)
        if load is None:
            continue
        job = by_id[job_id]
        (load.inherited_jobs if inherited else load.own_jobs).add(job_id)
        if job.needs_sourcing:
            load.searches.add(job_id)
        if job.favorite_candidate_id and getattr(
            favorite_stages.get(job_id), "value", favorite_stages.get(job_id)
        ) not in {None, "hired", "rejected", "withdrawn"}:
            load.favorites.add(job_id)

    processes = (
        await db.execute(
            select(
                RecruitmentProcess.owner_user_id,
                RecruitmentProcess.candidate_id,
                RecruitmentProcess.job_id,
            ).where(RecruitmentProcess.status == ProcessStatus.open)
        )
    ).all()
    for owner, candidate, job in processes:
        load, _ = target(owner)
        if load is not None:
            load.candidate_processes.add((candidate, job))

    events = (
        await db.execute(
            select(
                CalendarEvent.id,
                func.coalesce(
                    CalendarEvent.operational_owner_id, CalendarEvent.created_by
                ),
                CalendarEvent.start_time,
                CalendarEvent.all_day,
            ).where(CalendarEvent.status == EventStatus.scheduled)
        )
    ).all()
    for event_id, owner, starts, all_day in events:
        load, inherited = target(owner)
        if load is not None:
            due = starts.astimezone(WARSAW).date() if all_day else starts
            load.add_task("calendar", event_id, due, now=now, inherited=inherited)

    contacts = (
        await db.execute(
            select(
                CandidateContactCase.id,
                CandidateContactCase.owner_user_id,
                CandidateContactCase.candidate_id,
                CandidateContactCase.due_at,
            ).where(CandidateContactCase.state.in_(CONTACT_OPEN_STATES))
        )
    ).all()
    for case_id, owner, candidate, due in contacts:
        load, inherited = target(owner)
        if load is not None:
            load.contacts.add(candidate)
            load.add_task("contact", case_id, due, now=now, inherited=inherited)

    onboarding = (
        await db.execute(
            select(
                ContractOnboardingItem.id,
                ContractOnboardingItem.assigned_to,
                ContractOnboardingItem.due_date,
            ).where(ContractOnboardingItem.status == OnboardingItemStatus.pending)
        )
    ).all()
    for item_id, owner, due in onboarding:
        load, inherited = target(owner)
        if load is not None:
            load.add_task("onboarding", item_id, due, now=now, inherited=inherited)
    return loads


def choose_assignee(
    users: list[User],
    *,
    channel: PriorityChannel,
    job_categories: set[int],
    competencies: dict[int, dict[int, int]],
    workforce: WorkforceContext,
    loads: dict[int, Workload],
    last_assigned: dict[int, datetime],
    paused_users: set[int],
) -> User | None:
    if not workforce.fresh or not job_categories:
        return None
    eligible = [
        user
        for user in users
        if user.is_active
        and user.id in workforce.available_ids
        and user.id not in paused_users
        and bool(role_values(user) & {role.value for role in OPERATIONAL_ROLES})
        and channel in allowed_channels(user)
        and bool(job_categories & competencies.get(user.id, {}).keys())
    ]
    oldest = datetime.min.replace(tzinfo=timezone.utc)

    def order(user):
        competence = min(
            competencies[user.id][category]
            for category in job_categories
            if category in competencies[user.id]
        )
        return (
            *loads.get(user.id, Workload()).comparison,
            competence,
            last_assigned.get(user.id, oldest),
            user.id,
        )

    return min(eligible, key=order) if eligible else None


async def release_operator(db: AsyncSession, *, job: Job) -> None:
    """Retire the current owner's published work, preserving completed history."""
    if job.recruiter_id is not None:
        old_members = (
            select(RecruitmentPriorityPlanMember.id)
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                RecruitmentPriorityPlanMember.user_id == job.recruiter_id,
            )
        )
        await db.execute(
            delete(RecruitmentPriorityAssignment).where(
                RecruitmentPriorityAssignment.plan_member_id.in_(old_members),
                RecruitmentPriorityAssignment.job_id == job.id,
            )
        )
    job.recruiter_id = None


async def assign_operator(
    db: AsyncSession,
    *,
    job: Job,
    assignee: User,
    channel: PriorityChannel,
    actor_user_id: int | None,
    source: str,
    as_owner: bool,
    position: int | None = None,
    verification_target: int = 0,
    recommendation_target: int = 0,
) -> RecruitmentPriorityAssignment:
    """Shared owner/commitment command. Caller holds the allocation and job locks."""
    if not assignee.is_active or not (
        role_values(assignee) & {role.value for role in OPERATIONAL_ROLES}
    ):
        raise HTTPException(422, "Osoba nie może prowadzić tej pracy")
    if channel not in allowed_channels(assignee):
        raise HTTPException(422, "Kanał pracy nie pasuje do roli")
    demand = await db.scalar(
        select(RecruitmentPriorityDemand)
        .where(
            RecruitmentPriorityDemand.job_id == job.id,
            RecruitmentPriorityDemand.status.in_(
                [
                    PriorityDemandStatus.open,
                    PriorityDemandStatus.covered,
                    PriorityDemandStatus.paused,
                ]
            ),
        )
        .with_for_update()
    )
    if demand is None:
        demand = RecruitmentPriorityDemand(
            job_id=job.id,
            requested_by_user_id=actor_user_id,
            status=PriorityDemandStatus.open,
            expected_recommendations=3,
            required_channel=channel,
            rationale="Przekazanie rekrutacji do pracy.",
            brief_ready=True,
        )
        db.add(demand)
        await db.flush()
    plan = await ensure_standing_plan(db, actor_user_id=actor_user_id)
    member = await ensure_plan_member(db, plan=plan, user_id=assignee.id)
    if member.status != PriorityMemberStatus.active:
        raise HTTPException(422, "Ta osoba jest wstrzymana w rosterze")
    assignment = await db.scalar(
        select(RecruitmentPriorityAssignment).where(
            RecruitmentPriorityAssignment.plan_member_id == member.id,
            RecruitmentPriorityAssignment.job_id == job.id,
        )
    )
    if assignment is None:
        position = position or await next_free_position(db, member_id=member.id)
        taken = await db.scalar(
            select(RecruitmentPriorityAssignment.id).where(
                RecruitmentPriorityAssignment.plan_member_id == member.id,
                RecruitmentPriorityAssignment.position == position,
            )
        )
        if taken is not None:
            raise HTTPException(409, "Pozycja jest już zajęta u tej osoby")
        assignment = RecruitmentPriorityAssignment(
            plan_member_id=member.id,
            demand_id=demand.id,
            job_id=job.id,
            position=position,
            rank=legacy_priority_rank(position),
            channel=channel,
            verification_target=verification_target,
            recommendation_target=recommendation_target,
            competence_category_id=job.competence_category_id,
            suggestion_source=source,
        )
        db.add(assignment)
        await db.flush()
    previous_owner = job.recruiter_id
    if as_owner or previous_owner is None:
        if previous_owner is not None and previous_owner != assignee.id:
            await release_operator(db, job=job)
        job.recruiter_id = assignee.id
    audit_event(
        db,
        "allocation_assigned",
        actor_user_id=actor_user_id,
        job_id=job.id,
        plan_id=plan.id,
        assignment_id=assignment.id,
        subject_user_id=assignee.id,
        payload={
            "source": source,
            "position": assignment.position,
            "previous_owner_id": previous_owner,
            "owner_id": job.recruiter_id,
            "channel": channel.value,
        },
    )
    await db.flush()
    return assignment


async def allocate_pending(
    db: AsyncSession, workforce: WorkforceContext, state: RecruitmentAllocationState
) -> dict:
    """Run under the shared lock. Shadow simulates each previous choice in the batch."""
    now = datetime.now(timezone.utc)
    loads = await load_workloads(db, workforce, now=now)
    users = list((await db.scalars(select(User).where(User.is_active.is_(True)))).all())
    from app.services.section_permissions import (
        resolve_effective_section_access_for_users,
        section_access_for_user,
        ProductSection,
        SectionAccess,
    )

    await resolve_effective_section_access_for_users(db, users)
    users = [
        user
        for user in users
        if section_access_for_user(user, ProductSection.pipeline) >= SectionAccess.write
        and section_access_for_user(user, ProductSection.sourcing)
        >= SectionAccess.write
    ]
    competencies: dict[int, dict[int, int]] = {}
    for user_id, category, priority in (
        await db.execute(
            select(
                UserCompetenceCategory.user_id,
                UserCompetenceCategory.competence_category_id,
                UserCompetenceCategory.priority,
            )
        )
    ).all():
        competencies.setdefault(user_id, {})[category] = priority
    secondary: dict[int, set[int]] = {}
    for job_id, category in (
        await db.execute(
            select(JobSecondaryCc.job_id, JobSecondaryCc.competence_category_id)
        )
    ).all():
        secondary.setdefault(job_id, set()).add(category)
    paused = set(
        (
            await db.scalars(
                select(RecruitmentPriorityPlanMember.user_id)
                .join(
                    RecruitmentPriorityPlan,
                    RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
                )
                .where(
                    RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                    RecruitmentPriorityPlanMember.status == PriorityMemberStatus.paused,
                )
            )
        ).all()
    )
    last_assigned = dict(
        (
            await db.execute(
                select(
                    RecruitmentAllocationRequest.assigned_user_id,
                    func.max(RecruitmentAllocationRequest.evaluated_at),
                )
                .where(
                    RecruitmentAllocationRequest.status == "assigned",
                    RecruitmentAllocationRequest.assigned_user_id.is_not(None),
                )
                .group_by(RecruitmentAllocationRequest.assigned_user_id)
            )
        ).all()
    )
    requests = (
        await db.execute(
            select(RecruitmentAllocationRequest, Job)
            .join(Job, Job.id == RecruitmentAllocationRequest.job_id)
            .where(RecruitmentAllocationRequest.status == "queued")
            .order_by(
                case(
                    (Job.priority == "urgent", 0),
                    (Job.priority == "high", 1),
                    (Job.priority == "medium", 2),
                    else_=3,
                ),
                func.coalesce(RecruitmentAllocationRequest.due_at, Job.deadline)
                .asc()
                .nulls_last(),
                RecruitmentAllocationRequest.created_at,
                RecruitmentAllocationRequest.id,
            )
            .with_for_update(of=[RecruitmentAllocationRequest, Job])
        )
    ).all()
    assigned = previewed = waiting = 0
    for request, job in requests:
        request.evaluated_at = now
        request.suggested_user_id = None
        if (
            job.recruiter_id is not None
            or not job.is_open
            or job.status == JobStatus.closed
        ):
            request.status = "cancelled"
            request.reason = "already_owned_or_closed"
            continue
        if job_readiness_blockers(job):
            request.reason = "brief_not_ready"
            request.decision = None
            waiting += 1
            continue
        categories = secondary.get(job.id, set()) | (
            {job.competence_category_id} if job.competence_category_id else set()
        )
        reason = (
            "sourcing_paused"
            if not job.needs_sourcing
            else (
                "allocation_off"
                if state.mode == "off"
                else (
                    "availability_stale"
                    if not workforce.fresh
                    else ("competence_missing" if not categories else None)
                )
            )
        )
        chosen = (
            None
            if reason
            else choose_assignee(
                users,
                channel=PriorityChannel(request.channel),
                job_categories=categories,
                competencies=competencies,
                workforce=workforce,
                loads=loads,
                last_assigned=last_assigned,
                paused_users=paused,
            )
        )
        if chosen is None:
            request.reason = reason or "no_eligible_person"
            waiting += 1
            continue
        load = loads.setdefault(chosen.id, Workload())
        request.reason = "least_workload"
        request.suggested_user_id = chosen.id
        request.decision = {
            "mode": state.mode,
            "snapshot_version": workforce.snapshot_version,
            "chosen_user_id": chosen.id,
            "workload_before": load.as_payload(),
            "competence_priority": min(
                competencies[chosen.id][category]
                for category in categories
                if category in competencies[chosen.id]
            ),
            "order": [
                "active_searches",
                "overdue_tasks",
                "tasks_today",
                "candidate_followups",
                "competence",
                "last_assignment",
                "user_id",
            ],
        }
        if state.mode == "auto":
            await assign_operator(
                db,
                job=job,
                assignee=chosen,
                channel=PriorityChannel(request.channel),
                actor_user_id=request.requested_by_user_id,
                source="automatic",
                as_owner=True,
            )
            request.status = "assigned"
            request.assigned_user_id = chosen.id
            snapshot = ProposalSnapshot(
                job_id=job.id,
                source=SOURCE_HANDOFF,
                status=STATUS_PENDING,
                top_k=settings.MATCH_MAX_RESULTS,
                profile_id=0,
                created_by=request.requested_by_user_id,
                run_id=uuid4().hex,
            )
            db.add(snapshot)
            await db.flush()
            request.matching_snapshot_id = snapshot.id
            request.matching_attempts = 0
            request.matching_claimed_at = None
            audit_event(
                db,
                "automatic_allocation_decision",
                job_id=job.id,
                subject_user_id=chosen.id,
                payload=request.decision,
            )
            assigned += 1
        else:
            previewed += 1
        # The next request sees the preceding assignment in BOTH modes.
        load.searches.add(job.id)
        load.own_jobs.add(job.id)
        last_assigned[chosen.id] = now
        await db.flush()
    return {"assigned": assigned, "previewed": previewed, "waiting": waiting}
