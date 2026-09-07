"""PostgreSQL integration checks, run by hosted CI after Alembic migrations."""

import asyncio
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactOpportunity,
)
from app.models.client import Client
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.recruitment_allocation import (
    RecruitmentAllocationRequest,
    RecruitmentAllocationState,
)
from app.models.recruitment_priority import (
    PriorityChannel,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityPlanMember,
)
from app.models.user import User, UserRole
from app.services.recruitment_allocation import (
    allocation_lock,
    allocate_pending,
    enqueue_allocation,
    load_workloads,
)
from app.services.workforce_availability import WorkforceContext, Delegation
from tests.test_job_handoff_and_champion_stale import _READY_CHAMPION

pytestmark = pytest.mark.asyncio


async def seed():
    async with AsyncSessionLocal() as db:
        tag = uuid4().hex[:12]
        users = [
            User(
                email=f"allocation-{tag}-{n}@example.com",
                name=f"Allocation {n}",
                hashed_password="not-a-login",
                role=UserRole.recruiter,
                roles=["recruiter"],
                is_active=True,
            )
            for n in range(3)
        ]
        category = CompetenceCategory(
            slug=f"allocation-{tag}",
            name_pl="Allocation test",
            name_en="Allocation test",
            description="CI fixture",
        )
        client = Client(name=f"Allocation {tag}")
        db.add_all([*users, category, client])
        await db.flush()
        for person in users:
            db.add(
                UserCompetenceCategory(
                    user_id=person.id,
                    competence_category_id=category.id,
                    priority=1,
                    is_primary=True,
                )
            )
        jobs = [
            Job(
                title=f"Allocation {tag}/{n}",
                client_id=client.id,
                competence_category_id=category.id,
                champion_profile=_READY_CHAMPION,
                status=JobStatus.published,
                is_open=True,
                needs_sourcing=True,
                headcount=1,
            )
            for n in range(8)
        ]
        db.add_all(jobs)
        await db.commit()
        return [user.id for user in users], [job.id for job in jobs]


async def test_concurrent_requests_recalculate_after_transaction_lock_and_exceed_five():
    users, jobs = await seed()
    context = WorkforceContext(fresh=True, available_ids=set(users[:2]))

    async def handoff_and_allocate(job_id):
        async with AsyncSessionLocal() as db:
            await allocation_lock(db)
            job = await db.get(Job, job_id)
            await enqueue_allocation(
                db, job=job, actor_user_id=users[2], channel=PriorityChannel.linkedin
            )
            result = await allocate_pending(
                db, context, RecruitmentAllocationState(mode="auto")
            )
            await db.commit()
            return result

    await asyncio.gather(*(handoff_and_allocate(job_id) for job_id in jobs[:2]))
    async with AsyncSessionLocal() as db:
        first = list(
            (
                await db.scalars(select(Job.recruiter_id).where(Job.id.in_(jobs[:2])))
            ).all()
        )
        assert set(first) == set(users[:2])
        requests = list(
            (
                await db.scalars(
                    select(RecruitmentAllocationRequest).where(
                        RecruitmentAllocationRequest.job_id.in_(jobs[:2])
                    )
                )
            ).all()
        )
        assert all(
            row.matching_snapshot_id
            and row.decision["workload_before"]["active_searches"] == 0
            for row in requests
        )
    context.available_ids = {users[0]}
    for job_id in jobs[2:]:
        await handoff_and_allocate(job_id)
    async with AsyncSessionLocal() as db:
        assignments = list(
            (
                await db.scalars(
                    select(RecruitmentPriorityAssignment)
                    .join(
                        RecruitmentPriorityPlanMember,
                        RecruitmentPriorityPlanMember.id
                        == RecruitmentPriorityAssignment.plan_member_id,
                    )
                    .where(RecruitmentPriorityPlanMember.user_id == users[0])
                    .order_by(RecruitmentPriorityAssignment.position)
                )
            ).all()
        )
        assert len(assignments) == 7
        assert [row.position for row in assignments] == list(range(1, 8))
        assert assignments[5].rank is None


async def test_shadow_and_stale_snapshots_never_mutate_ownership():
    users, jobs = await seed()
    async with AsyncSessionLocal() as db:
        await allocation_lock(db)
        job = await db.get(Job, jobs[0])
        request = await enqueue_allocation(
            db, job=job, actor_user_id=users[2], channel=PriorityChannel.linkedin
        )
        await allocate_pending(
            db,
            WorkforceContext(fresh=True, available_ids={users[0]}),
            RecruitmentAllocationState(mode="shadow"),
        )
        assert (
            job.recruiter_id is None
            and request.suggested_user_id == users[0]
            and request.status == "queued"
        )
        await allocate_pending(
            db, WorkforceContext(fresh=False), RecruitmentAllocationState(mode="auto")
        )
        assert job.recruiter_id is None and request.reason == "availability_stale"
        await db.rollback()


async def test_substitute_reads_both_source_queues_past_twenty_and_cannot_act_on_other_queue(
    monkeypatch,
):
    from app.api.candidate_contact import get_my_contact_queue, _caller_may_act_on_case

    monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    users, jobs = await seed()
    cover = Delegation(
        users[0], users[1], date(2026, 9, 7), date(2026, 9, 8), ("ci-leave",)
    )
    context = WorkforceContext(
        fresh=True, available_ids={users[1], users[2]}, delegations={users[0]: cover}
    )
    async with AsyncSessionLocal() as db:
        db.info["workforce_context"] = context
        operator = await db.get(User, users[1])
        job = await db.get(Job, jobs[0])
        job.recruiter_id = users[0]
        for n in range(24):
            candidate = Candidate(
                name="Allocation", lastname=f"Queue {n}", status=CandidateStatus.active
            )
            db.add(candidate)
            await db.flush()
            case = CandidateContactCase(
                candidate_id=candidate.id,
                owner_user_id=users[n // 12],
                queue_slot=n % 12 + 1,
                state="queued",
                primary_job_id=job.id,
            )
            db.add(case)
            await db.flush()
            db.add(
                CandidateContactOpportunity(
                    case_id=case.id, candidate_id=candidate.id, job_id=job.id
                )
            )
        await db.flush()
        page = await get_my_contact_queue(
            current_user=operator, db=db, cursor=None, limit=20
        )
        next_page = await get_my_contact_queue(
            current_user=operator, db=db, cursor=page.next_cursor, limit=20
        )
        assert len(page.items) == 20 and len(next_page.items) == 4
        assert page.utilization.used == 24 and page.utilization.capacity == 40
        assert len({item.id for item in [*page.items, *next_page.items]}) == 24
        assert any(
            item.substitution and item.effective_owner.id == users[1]
            for item in page.items
        )
        loads = await load_workloads(db, context, now=datetime.now(timezone.utc))
        assert loads[users[1]].followups == 24
        own_case = await db.scalar(
            select(CandidateContactCase).where(
                CandidateContactCase.owner_user_id == users[0]
            )
        )
        await _caller_may_act_on_case(db, case=own_case, user=operator)
        outsider = await db.get(User, users[2])
        with pytest.raises(HTTPException) as error:
            await _caller_may_act_on_case(db, case=own_case, user=outsider)
        assert error.value.status_code == 403
        db.info["workforce_context"] = WorkforceContext()  # absence ended / cancelled
        returned = await get_my_contact_queue(
            current_user=operator, db=db, cursor=None, limit=100
        )
        assert len(returned.items) == 12
        await db.rollback()


async def test_open_and_new_calendar_onboarding_and_reminders_follow_cover_with_history_and_scope(
    monkeypatch,
):
    from app.api.calendar import CalendarEventCreate, create_event
    from app.api.calendar_access import (
        personal_event_visibility_filter,
        user_can_mutate_event,
    )
    from app.api.notifications import _notification_owner
    from app.api.recruitment_allocation import (
        my_onboarding,
        complete_onboarding,
        CompleteOnboarding,
    )
    from app.models.activity import Activity
    from app.models.calendar_event import CalendarEvent, EventStatus
    from app.models.contract import Contract
    from app.models.contract_onboarding import (
        ContractOnboardingItem,
        OnboardingItemStatus,
    )
    from app.models.notification import Notification, NotificationType
    from app.services.section_permissions import (
        resolve_effective_section_access_for_users,
    )

    monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", True)
    users, jobs = await seed()
    cover = Delegation(
        users[0], users[1], date(2026, 9, 7), date(2026, 9, 8), ("ci-leave",)
    )
    context = WorkforceContext(
        fresh=True, available_ids={users[1], users[2]}, delegations={users[0]: cover}
    )
    async with AsyncSessionLocal() as db:
        db.info["workforce_context"] = context
        owner, substitute, outsider = [await db.get(User, user_id) for user_id in users]
        await resolve_effective_section_access_for_users(
            db, [owner, substitute, outsider]
        )
        job = await db.get(Job, jobs[0])
        job.recruiter_id = owner.id
        contract = Contract(client_id=job.client_id, job_id=job.id)
        db.add(contract)
        await db.flush()
        tasks = [
            ContractOnboardingItem(
                contract_id=contract.id,
                assigned_to=owner.id,
                label=f"Operational item {n}",
                due_date=date.today(),
            )
            for n in range(2)
        ]
        existing = CalendarEvent(
            title="Existing work",
            job_id=job.id,
            created_by=owner.id,
            start_time=datetime.now(timezone.utc),
            status=EventStatus.scheduled,
        )
        completed = CalendarEvent(
            title="Historical work",
            created_by=owner.id,
            start_time=datetime.now(timezone.utc),
            status=EventStatus.completed,
        )
        reminders = [
            Notification(
                user_id=owner.id,
                title="Work reminder",
                message="Due",
                notification_type=NotificationType.job_deadline_1d,
                is_read=False,
            ),
            Notification(
                user_id=owner.id,
                title="Private security history",
                message="Private",
                notification_type=NotificationType.password_changed_by_admin,
                is_read=False,
            ),
        ]
        db.add_all([*tasks, existing, completed, *reminders])
        await db.flush()
        assert user_can_mutate_event(existing, substitute)
        assert not user_can_mutate_event(completed, substitute)
        assert not user_can_mutate_event(existing, outsider)
        shown = list(
            (
                await db.scalars(
                    select(CalendarEvent.id).where(
                        personal_event_visibility_filter(substitute)
                    )
                )
            ).all()
        )
        assert existing.id in shown and completed.id not in shown
        shown_reminders = list(
            (
                await db.scalars(
                    select(Notification.id).where(_notification_owner(substitute))
                )
            ).all()
        )
        assert (
            reminders[0].id in shown_reminders
            and reminders[1].id not in shown_reminders
        )
        page = await my_onboarding(current_user=substitute, after=0, db=db)
        assert {row["id"] for row in page["items"]} == {row.id for row in tasks}
        assert all(row["effective_user_id"] == substitute.id for row in page["items"])
        with pytest.raises(HTTPException) as error:
            await complete_onboarding(
                tasks[0].id, CompleteOnboarding(status="done"), outsider, db
            )
        assert error.value.status_code == 404
        new_event = await create_event(
            CalendarEventCreate(
                title="Created during cover",
                job_id=job.id,
                start_time=datetime.now(timezone.utc),
            ),
            substitute,
            db,
        )
        persisted = await db.get(CalendarEvent, new_event.id)
        assert (
            persisted.created_by == substitute.id
            and persisted.operational_owner_id == owner.id
        )
        await complete_onboarding(
            tasks[0].id, CompleteOnboarding(status="done"), substitute, db
        )
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract_onboarding_item",
                Activity.entity_id == tasks[0].id,
            )
        )
        assert audit.user_id == substitute.id and tasks[0].assigned_to == owner.id
        tasks[
            1
        ].assigned_to = outsider.id  # explicit manual transfer survives the return
        later_task = ContractOnboardingItem(
            contract_id=contract.id, assigned_to=owner.id, label="New during absence"
        )
        db.add(later_task)
        await db.flush()
        assert later_task.id in {
            row["id"] for row in (await my_onboarding(substitute, 0, db))["items"]
        }
        db.info["workforce_context"] = WorkforceContext()
        assert not user_can_mutate_event(existing, substitute)
        assert user_can_mutate_event(persisted, owner)
        returned = await my_onboarding(owner, 0, db)
        assert {row["id"] for row in returned["items"]} == {later_task.id}
        assert (
            tasks[0].status == OnboardingItemStatus.done
            and tasks[1].assigned_to == outsider.id
        )
        await db.rollback()


async def test_outbox_is_atomic_and_failed_sweep_is_retryable(monkeypatch):
    from sqlalchemy import event, func
    from sqlalchemy.orm import Session
    from unittest.mock import AsyncMock
    from app.models.recruitment_allocation import RecruitmentAllocationEvent
    from app.services.recruitment_allocation_events import (
        _after_flush,
        register_allocation_events,
    )
    from app.tasks import recruitment_allocation as worker

    users, jobs = await seed()
    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", True)
    already_registered = event.contains(Session, "after_flush", _after_flush)
    register_allocation_events()
    try:
        async with AsyncSessionLocal() as db:
            before = (
                await db.scalar(select(func.max(RecruitmentAllocationEvent.id))) or 0
            )
            job = await db.get(Job, jobs[0])
            job.needs_sourcing = False
            await db.flush()
            assert await db.scalar(
                select(RecruitmentAllocationEvent.id).where(
                    RecruitmentAllocationEvent.id > before
                )
            )
            await db.rollback()
            assert (
                await db.scalar(
                    select(RecruitmentAllocationEvent.id).where(
                        RecruitmentAllocationEvent.id > before
                    )
                )
                is None
            )
            job = await db.get(Job, jobs[0])
            job.needs_sourcing = False
            await db.commit()
            pending = await db.scalar(
                select(RecruitmentAllocationEvent.id).where(
                    RecruitmentAllocationEvent.id > before
                )
            )
            monkeypatch.setattr(
                worker,
                "reconcile_favorite_work",
                AsyncMock(side_effect=RuntimeError("retryable")),
            )
            with pytest.raises(RuntimeError, match="retryable"):
                await worker.run_allocation_sweep(db)
            await db.rollback()
            assert (
                await db.get(RecruitmentAllocationEvent, pending)
            ).processed_at is None
            monkeypatch.setattr(worker, "reconcile_favorite_work", AsyncMock())
            monkeypatch.setattr(
                worker, "workforce_context", AsyncMock(return_value=WorkforceContext())
            )
            monkeypatch.setattr(worker, "allocation_issues", AsyncMock(return_value=[]))
            monkeypatch.setattr(
                worker, "allocate_pending", AsyncMock(return_value={"assigned": 0})
            )
            await worker.run_allocation_sweep(db)
            record = await db.get(
                RecruitmentAllocationEvent, pending, populate_existing=True
            )
            assert (
                record.processed_at
                and record.attempts == 1
                and record.last_error is None
            )
    finally:
        if not already_registered:
            event.remove(Session, "after_flush", _after_flush)
