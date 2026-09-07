"""Minute availability refresh and durable, serialized operational reconciliation."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification import NotificationType
from app.models.proposal_snapshot import ProposalSnapshot
from app.models.recruitment_allocation import (
    RecruitmentAllocationEvent,
    RecruitmentAllocationRequest,
    RecruitmentAllocationState,
)
from app.models.user import User, UserRole
from app.services.recruitment_allocation import (
    allocation_lock,
    allocate_pending,
    load_workloads,
    Workload,
)
from app.services.recruitment_favorite_work import reconcile_favorite_work
from app.services.workforce_availability import sync_availability, workforce_context

logger = logging.getLogger(__name__)


async def availability_loop():
    if not settings.COMPASS_AVAILABILITY_ENABLED:
        return
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Multiple API workers must not overwrite a newer snapshot.
                await db.execute(text("SELECT pg_advisory_xact_lock(734092772)"))
                await sync_availability(db)
        except Exception:
            logger.exception("Availability refresh failed")
        await asyncio.sleep(60)


async def allocation_issues(db, context, loads):
    from app.models.competence_category import UserCompetenceCategory
    from app.models.job import Job
    from app.models.cc_feedback import JobSecondaryCc
    from app.models.recruitment_priority import (
        PriorityChannel,
        PriorityMemberStatus,
        PriorityPlanStatus,
        RecruitmentPriorityPlan,
        RecruitmentPriorityPlanMember,
        RecruitmentPriorityAssignment,
    )
    from app.services.recruitment_allocation import choose_assignee
    from app.services.section_permissions import (
        resolve_effective_section_access_for_users,
        section_access_for_user,
        ProductSection,
        SectionAccess,
    )

    issues = list(context.issues)
    if not context.fresh and not any(
        item.get("code") == "availability_stale" for item in issues
    ):
        issues.append({"reason": "availability_stale"})
    competencies = {}
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
    secondary = {}
    for job_id, category in (
        await db.execute(
            select(JobSecondaryCc.job_id, JobSecondaryCc.competence_category_id)
        )
    ).all():
        secondary.setdefault(job_id, set()).add(category)
    users = list(
        (await db.scalars(select(User).where(User.id.in_(context.available_ids)))).all()
    )
    await resolve_effective_section_access_for_users(db, users)
    users = [
        user
        for user in users
        if section_access_for_user(user, ProductSection.pipeline) >= SectionAccess.write
        and section_access_for_user(user, ProductSection.sourcing)
        >= SectionAccess.write
    ]
    members = (
        await db.execute(
            select(
                RecruitmentPriorityPlanMember.user_id,
                RecruitmentPriorityPlanMember.status,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(RecruitmentPriorityPlan.status == PriorityPlanStatus.published)
        )
    ).all()
    paused = {
        user_id for user_id, status in members if status == PriorityMemberStatus.paused
    }
    job_ids = {job for load in loads.values() for job in load.inherited_jobs}
    jobs = (
        list((await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all())
        if job_ids
        else []
    )
    commitments = (
        (
            await db.execute(
                select(
                    RecruitmentPriorityAssignment.job_id,
                    RecruitmentPriorityPlanMember.user_id,
                    RecruitmentPriorityAssignment.channel,
                )
                .join(
                    RecruitmentPriorityPlanMember,
                    RecruitmentPriorityPlanMember.id
                    == RecruitmentPriorityAssignment.plan_member_id,
                )
                .join(
                    RecruitmentPriorityPlan,
                    RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
                )
                .where(
                    RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                    RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                    RecruitmentPriorityAssignment.job_id.in_(job_ids),
                )
            )
        ).all()
        if job_ids
        else []
    )
    by_job = {}
    for job_id, owner, channel in commitments:
        by_job.setdefault(job_id, {})[owner] = channel
    for job in jobs:
        ownership = by_job.setdefault(job.id, {})
        if job.recruiter_id:
            ownership.setdefault(job.recruiter_id, PriorityChannel.linkedin)
        categories = secondary.get(job.id, set()) | (
            {job.competence_category_id} if job.competence_category_id else set()
        )
        for owner, channel in ownership.items():
            performer = context.performer(owner)
            if performer == owner:
                continue
            alternative = choose_assignee(
                [user for user in users if user.id != performer],
                channel=channel,
                job_categories=categories,
                competencies=competencies,
                workforce=context,
                loads=loads,
                last_assigned={},
                paused_users=paused,
            )
            if (
                alternative
                and loads.get(alternative.id, Workload()).comparison
                < loads.get(performer, Workload()).comparison
            ):
                issues.append(
                    {
                        "reason": "substitute_overloaded",
                        "owner_id": owner,
                        "performer_id": performer,
                        "job_id": job.id,
                        "alternatives": [alternative.id],
                    }
                )
    return sorted(issues, key=lambda item: str(sorted(item.items())))


async def run_allocation_sweep(db):
    await allocation_lock(db)
    await db.execute(
        insert(RecruitmentAllocationState).values(id=1).on_conflict_do_nothing()
    )
    state = await db.get(RecruitmentAllocationState, 1, populate_existing=True)
    cutoff = await db.scalar(select(func.max(RecruitmentAllocationEvent.id)))
    now = datetime.now(timezone.utc)
    await reconcile_favorite_work(db)
    context = await workforce_context(db, refresh=True)
    counts = await allocate_pending(db, context, state)
    loads = await load_workloads(db, context, now=now)
    issues = await allocation_issues(db, context, loads)
    # Fingerprint contents, not tick time: unchanged issues do not keep notifying.
    import hashlib
    import json

    fingerprint = hashlib.sha256(
        json.dumps(issues, sort_keys=True).encode()
    ).hexdigest()
    previous = state.stats or {}
    if issues and previous.get("issues_fingerprint") != fingerprint:
        from app.api.notifications import create_notification
        from app.services.notification_access import notification_recipient_has_access

        users = list(
            (
                await db.scalars(
                    select(User)
                    .where(User.is_active.is_(True))
                    .options(load_only(User.id, User.is_active, User.role, User.roles))
                )
            ).all()
        )
        for user in users:
            if user.has_role(
                UserRole.head_of_recruitment
            ) and await notification_recipient_has_access(
                db,
                user.id,
                NotificationType.recruitment_allocation_alert,
                link="/dashboard?preset=head-of-recruitment",
            ):
                await create_notification(
                    db,
                    user.id,
                    "Przydziały wymagają uwagi",
                    f"Wyjątki dostępności lub zastępstw: {len(issues)}. Sprawdź ekran zespołu.",
                    NotificationType.recruitment_allocation_alert,
                    link="/dashboard?preset=head-of-recruitment",
                    related_entity_type="allocation",
                    related_entity_id=1,
                    dedupe_resurface=True,
                )
    state.stats = {
        **counts,
        "issues": issues,
        "issues_fingerprint": fingerprint,
        "snapshot_version": context.snapshot_version,
    }
    state.last_run_at = now
    state.last_error = None
    if cutoff is not None:
        await db.execute(
            update(RecruitmentAllocationEvent)
            .where(
                RecruitmentAllocationEvent.id <= cutoff,
                RecruitmentAllocationEvent.processed_at.is_(None),
            )
            .values(
                processed_at=now,
                attempts=RecruitmentAllocationEvent.attempts + 1,
                last_error=None,
            )
        )
    await db.commit()


async def allocation_loop():
    if not settings.RECRUITMENT_ALLOCATION_ENABLED:
        return
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await run_allocation_sweep(db)
        except Exception as exc:
            logger.exception(
                "Allocation reconciliation failed; queued events will retry"
            )
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(RecruitmentAllocationState)
                        .where(RecruitmentAllocationState.id == 1)
                        .values(last_error=type(exc).__name__)
                    )
                    await db.execute(
                        update(RecruitmentAllocationEvent)
                        .where(RecruitmentAllocationEvent.processed_at.is_(None))
                        .values(
                            attempts=RecruitmentAllocationEvent.attempts + 1,
                            last_error=type(exc).__name__,
                        )
                    )
                    await db.commit()
            except Exception:
                # A database outage must not kill the retry loop while recording
                # the original error. The uncommitted outbox remains pending.
                logger.exception(
                    "Could not persist allocation failure; retry remains scheduled"
                )
        await asyncio.sleep(30)


async def allocation_matching_loop():
    if not settings.RECRUITMENT_ALLOCATION_ENABLED:
        return
    from app.tasks.compute_proposals import compute_proposal_for_job

    while True:
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        select(RecruitmentAllocationRequest, ProposalSnapshot)
                        .join(
                            ProposalSnapshot,
                            ProposalSnapshot.id
                            == RecruitmentAllocationRequest.matching_snapshot_id,
                        )
                        .where(
                            ProposalSnapshot.status.in_(["pending", "failed"]),
                            RecruitmentAllocationRequest.matching_attempts < 3,
                            or_(
                                RecruitmentAllocationRequest.matching_claimed_at.is_(
                                    None
                                ),
                                RecruitmentAllocationRequest.matching_claimed_at
                                < datetime.now(timezone.utc) - timedelta(minutes=10),
                            ),
                        )
                        .order_by(RecruitmentAllocationRequest.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                ).first()
                if row:
                    request, snapshot = row
                    request.matching_attempts += 1
                    request.matching_claimed_at = datetime.now(timezone.utc)
                    snapshot.status = "pending"
                    snapshot_id, job_id, top_k = (
                        snapshot.id,
                        snapshot.job_id,
                        snapshot.top_k,
                    )
                    await db.commit()
            if row:
                await compute_proposal_for_job(snapshot_id, job_id, top_k=top_k)
        except Exception:
            logger.exception("Allocation matching failed; durable request will retry")
        await asyncio.sleep(30)
