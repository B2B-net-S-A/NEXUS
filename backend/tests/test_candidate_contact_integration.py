"""PostgreSQL integration coverage for candidate-global contact coordination.

These tests intentionally use ``AsyncSessionLocal`` and committed rows.  The
capacity/idempotency/worker cases need independent database connections to
exercise PostgreSQL row locks, ``SKIP LOCKED`` and the partial unique index;
an in-memory repository or mocked session cannot prove those invariants.

CI applies Alembic migrations before collecting this module.  A local run
therefore requires the same migrated PostgreSQL test database as the backend
CI job; it does not require a locally running Nexus HTTP server.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.call import Call
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactEvent,
    CandidateContactOpportunity,
    CandidateContactState,
    CandidateContactTraffitCursor,
    CandidateContactTraffitLedger,
)
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_shortlist import JobShortlistEntry
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.candidate_contact import (
    ContactCaseVersionConflict,
    ContactIdempotencyConflict,
    close_contact_opportunity,
    close_job_contact_opportunities,
    ensure_contact_opportunity,
    process_contact_cases,
    reassign_contact_case,
    record_contact_attempt,
    sync_calendar_handoff,
)
from app.services.candidate_contact_hooks import (
    has_active_contact_trigger,
    maybe_ensure_contact_opportunity,
)
from app.tasks.candidate_contact_queue import run_candidate_contact_queue_once
from app.tasks import candidate_contact_traffit as contact_traffit_task
from app.tasks.candidate_contact_traffit import run_traffit_contact_intake_once

pytestmark = pytest.mark.asyncio

BASE_TIME = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


@dataclass
class ContactDb:
    """Small committed-data factory with deterministic, scoped cleanup."""

    db: AsyncSession
    prefix: str = field(default_factory=lambda: f"cc-{uuid.uuid4().hex[:12]}")
    user_ids: set[int] = field(default_factory=set)
    candidate_ids: set[int] = field(default_factory=set)
    job_ids: set[int] = field(default_factory=set)
    client_ids: set[int] = field(default_factory=set)
    calendar_event_ids: set[int] = field(default_factory=set)
    _client_id: int | None = None

    async def add_user(
        self,
        role: UserRole,
        *,
        label: str,
        active: bool = True,
    ) -> User:
        user = User(
            email=f"{self.prefix}-{label}@example.com",
            name=f"Contact {label}",
            role=role,
            roles=[role.value],
            is_active=active,
            email_verified=True,
            profile_completed=True,
        )
        self.db.add(user)
        await self.db.flush()
        self.user_ids.add(user.id)
        return user

    async def client(self) -> Client:
        if self._client_id is not None:
            client = await self.db.get(Client, self._client_id)
            assert client is not None
            return client
        client = Client(
            name=f"Contact client {self.prefix}",
            status=ClientStatus.active,
        )
        self.db.add(client)
        await self.db.flush()
        self._client_id = client.id
        self.client_ids.add(client.id)
        return client

    async def add_candidate(
        self,
        *,
        label: str,
        phone: str | None = "+48 500 600 700",
    ) -> Candidate:
        candidate = Candidate(
            name="Candidate",
            lastname=label,
            email=f"{self.prefix}-candidate-{label}@example.com",
            phone=phone,
            status=CandidateStatus.active,
        )
        self.db.add(candidate)
        await self.db.flush()
        self.candidate_ids.add(candidate.id)
        return candidate

    async def add_job(
        self,
        *,
        label: str,
        recruiter: User | None,
        priority: JobPriority = JobPriority.medium,
        tac: User | None = None,
        delivery_lead: User | None = None,
    ) -> Job:
        client = await self.client()
        job = Job(
            title=f"Contact role {self.prefix} {label}",
            client_id=client.id,
            recruiter_id=recruiter.id if recruiter else None,
            tac_id=tac.id if tac else None,
            delivery_lead_id=delivery_lead.id if delivery_lead else None,
            status=JobStatus.published,
            priority=priority,
        )
        self.db.add(job)
        await self.db.flush()
        self.job_ids.add(job.id)
        return job

    async def add_collaborator(self, *, job: Job, user: User) -> JobCollaborator:
        collaborator = JobCollaborator(
            job_id=job.id,
            user_id=user.id,
            source=JobCollaboratorSource.manual,
            removed_from_auto_cc=False,
        )
        self.db.add(collaborator)
        await self.db.flush()
        return collaborator

    async def add_calendar_event(
        self,
        *,
        candidate: Candidate,
        job: Job,
        creator: User,
        label: str,
    ) -> CalendarEvent:
        event = CalendarEvent(
            title=f"Screening {self.prefix} {label}",
            event_type=EventType.screening,
            status=EventStatus.scheduled,
            start_time=BASE_TIME + timedelta(days=3),
            end_time=BASE_TIME + timedelta(days=3, hours=1),
            candidate_id=candidate.id,
            job_id=job.id,
            client_id=job.client_id,
            created_by=creator.id,
        )
        self.db.add(event)
        await self.db.flush()
        self.calendar_event_ids.add(event.id)
        return event

    async def commit(self) -> None:
        await self.db.commit()

    async def cleanup(self) -> None:
        """Delete only this test's rows, in FK order, even after assertion errors."""

        async with AsyncSessionLocal() as cleanup_db:
            if self.calendar_event_ids:
                await cleanup_db.execute(
                    delete(CalendarEvent).where(
                        CalendarEvent.id.in_(self.calendar_event_ids)
                    )
                )
            if self.candidate_ids:
                candidate_filter = CandidateContactCase.candidate_id.in_(
                    self.candidate_ids
                )
                # candidate_contact_events is DB-enforced append-only and has
                # denormalized IDs specifically so parent cleanup cannot erase
                # audit evidence. CI's database is ephemeral; keep these rows.
                await cleanup_db.execute(
                    delete(Call).where(Call.candidate_id.in_(self.candidate_ids))
                )
                await cleanup_db.execute(
                    delete(JobShortlistEntry).where(
                        JobShortlistEntry.candidate_id.in_(self.candidate_ids)
                    )
                )
                await cleanup_db.execute(
                    delete(CandidateStage).where(
                        CandidateStage.candidate_id.in_(self.candidate_ids)
                    )
                )
                await cleanup_db.execute(
                    delete(CandidateContactOpportunity).where(
                        CandidateContactOpportunity.candidate_id.in_(self.candidate_ids)
                    )
                )
                await cleanup_db.execute(
                    delete(CandidateContactCase).where(candidate_filter)
                )
                await cleanup_db.execute(
                    delete(Candidate).where(Candidate.id.in_(self.candidate_ids))
                )
            if self.job_ids:
                await cleanup_db.execute(delete(Job).where(Job.id.in_(self.job_ids)))
            if self.client_ids:
                await cleanup_db.execute(
                    delete(Client).where(Client.id.in_(self.client_ids))
                )
            if self.user_ids:
                await cleanup_db.execute(delete(User).where(User.id.in_(self.user_ids)))
            await cleanup_db.commit()


@pytest_asyncio.fixture
async def contact_db() -> ContactDb:
    async with AsyncSessionLocal() as db:
        context = ContactDb(db=db)
        try:
            yield context
        finally:
            await db.rollback()
    await context.cleanup()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(
        user.id,
        user.role.value,
        roles=list(user.roles or [user.role.value]),
    )
    return {"Authorization": f"Bearer {token}"}


async def _case_snapshot(case_id: int) -> CandidateContactCase:
    async with AsyncSessionLocal() as db:
        case = await db.get(CandidateContactCase, case_id)
        assert case is not None
        return case


async def _case_for_candidate(candidate_id: int) -> CandidateContactCase:
    async with AsyncSessionLocal() as db:
        case = await db.scalar(
            select(CandidateContactCase).where(
                CandidateContactCase.candidate_id == candidate_id
            )
        )
        assert case is not None
        return case


async def test_multi_job_intake_creates_one_case_and_keeps_current_owner(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="first-owner")
    second_owner = await contact_db.add_user(UserRole.recruiter, label="second-owner")
    candidate = await contact_db.add_candidate(label="multi-job")
    first_job = await contact_db.add_job(
        label="first",
        recruiter=first_owner,
        priority=JobPriority.low,
    )
    later_urgent_job = await contact_db.add_job(
        label="later-urgent",
        recruiter=second_owner,
        priority=JobPriority.urgent,
    )

    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    first_owner_id = case.owner_user_id
    first_slot = case.queue_slot
    same_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=later_urgent_job.id,
        source="shortlist",
        occurred_at=BASE_TIME + timedelta(minutes=5),
    )
    await contact_db.commit()

    assert same_case.id == case.id
    assert first_owner_id == first_owner.id
    assert same_case.owner_user_id == first_owner_id
    assert same_case.queue_slot == first_slot
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactCase.id)).where(
                CandidateContactCase.candidate_id == candidate.id
            )
        )
        == 1
    )
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactOpportunity.id)).where(
                CandidateContactOpportunity.case_id == case.id,
                CandidateContactOpportunity.closed_at.is_(None),
            )
        )
        == 2
    )


async def test_stale_intake_cannot_reopen_a_newer_closed_opportunity(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="stale-replay-owner")
    candidate = await contact_db.add_candidate(label="stale-replay")
    job = await contact_db.add_job(label="stale-replay", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="100",
        occurred_at=BASE_TIME,
    )
    await contact_db.commit()

    closed = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        reason="terminal_source_event",
        occurred_at=BASE_TIME + timedelta(hours=2),
        source="traffit",
        source_external_ref="200",
    )
    await contact_db.commit()
    assert closed is not None
    closed_version = closed.version
    assert closed.state == CandidateContactState.completed.value

    stale = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="150",
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()
    assert stale.id == case.id
    assert stale.state == CandidateContactState.completed.value
    assert stale.version == closed_version

    newer = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="300",
        occurred_at=BASE_TIME + timedelta(hours=3),
    )
    await contact_db.commit()
    assert newer.id == case.id
    assert newer.state == CandidateContactState.queued.value
    assert newer.version > closed_version
    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == case.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.linked_at == BASE_TIME + timedelta(hours=3)
    assert opportunity.source_cursor_external_id == "300"
    reopened_version = newer.version

    delayed_terminal = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        reason="equal_second_lower_id_terminal",
        occurred_at=BASE_TIME + timedelta(hours=3),
        source="traffit",
        source_external_ref="250",
    )
    await contact_db.commit()
    assert delayed_terminal is not None
    assert delayed_terminal.state == CandidateContactState.queued.value
    assert delayed_terminal.version == reopened_version
    assert opportunity.source_cursor_external_id == "300"

    current_terminal = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        reason="equal_second_higher_id_terminal",
        occurred_at=BASE_TIME + timedelta(hours=3),
        source="traffit",
        source_external_ref="350",
    )
    await contact_db.commit()
    assert current_terminal is not None
    assert current_terminal.state == CandidateContactState.completed.value
    assert current_terminal.version > reopened_version
    assert opportunity.source_cursor_external_id == "350"

    same_second_reopen = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="400",
        occurred_at=BASE_TIME + timedelta(hours=3),
    )
    await contact_db.commit()
    assert same_second_reopen is not None
    assert same_second_reopen.state == CandidateContactState.queued.value
    assert opportunity.closed_at is None
    assert opportunity.source_cursor_external_id == "400"


async def test_nexus_close_fences_delayed_traffit_start_until_strictly_newer(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="cross-source-owner")
    candidate = await contact_db.add_candidate(label="cross-source")
    job = await contact_db.add_job(label="cross-source", recruiter=owner)
    source_start = BASE_TIME + timedelta(hours=3)
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="100",
        occurred_at=source_start,
    )
    assert contact_case is not None
    local_close_at = BASE_TIME + timedelta(hours=5)
    locally_closed = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        reason="nexus_pipeline_removed",
        occurred_at=local_close_at,
    )
    await contact_db.commit()
    assert locally_closed is not None
    assert locally_closed.state == CandidateContactState.completed.value
    closed_version = locally_closed.version

    delayed = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="200",
        occurred_at=local_close_at - timedelta(minutes=30),
    )
    equal_time = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="999",
        occurred_at=local_close_at,
    )
    await contact_db.commit()
    assert delayed is not None
    assert equal_time is not None
    assert delayed.state == CandidateContactState.completed.value
    assert equal_time.state == CandidateContactState.completed.value
    assert equal_time.version == closed_version

    newer = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="1",
        occurred_at=local_close_at + timedelta(seconds=1),
    )
    await contact_db.commit()
    assert newer is not None
    assert newer.state == CandidateContactState.queued.value
    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == contact_case.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.closed_at is None
    assert opportunity.source_cursor_created_at == local_close_at + timedelta(seconds=1)
    assert opportunity.source_cursor_external_id == "1"


async def test_not_interested_call_fences_stale_traffit_reopen(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="call-fence-owner")
    candidate = await contact_db.add_candidate(label="call-fence")
    job = await contact_db.add_job(label="call-fence", recruiter=owner)
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="100",
        occurred_at=BASE_TIME,
    )
    assert contact_case is not None
    call_at = BASE_TIME + timedelta(hours=5)
    completed = await record_contact_attempt(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=owner.id,
        outcome="connected",
        opportunity_outcomes={job.id: "not_interested"},
        expected_version=contact_case.version,
        idempotency_key=f"{contact_db.prefix}-call-fence",
        occurred_at=call_at,
    )
    await contact_db.commit()
    assert completed.case.state == CandidateContactState.completed.value
    completed_version = completed.case.version

    stale = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="999",
        occurred_at=call_at - timedelta(hours=1),
    )
    await contact_db.commit()
    assert stale is not None
    assert stale.state == CandidateContactState.completed.value
    assert stale.version == completed_version

    newer = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="traffit",
        source_external_ref="1",
        occurred_at=call_at + timedelta(hours=1),
    )
    await contact_db.commit()
    assert newer is not None
    assert newer.state == CandidateContactState.queued.value
    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == contact_case.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.closed_at is None
    assert opportunity.source_cursor_created_at == call_at + timedelta(hours=1)
    assert opportunity.source_cursor_external_id == "1"


async def test_unassigned_owner_selection_uses_priority_then_linked_at(
    contact_db: ContactDb,
) -> None:
    older_owner = await contact_db.add_user(UserRole.recruiter, label="older-owner")
    newer_owner = await contact_db.add_user(UserRole.recruiter, label="newer-owner")
    high_owner = await contact_db.add_user(UserRole.recruiter, label="high-owner")
    low_job = await contact_db.add_job(
        label="low",
        recruiter=older_owner,
        priority=JobPriority.low,
    )
    high_job = await contact_db.add_job(
        label="high",
        recruiter=high_owner,
        priority=JobPriority.high,
    )
    tied_newer_job = await contact_db.add_job(
        label="tied-newer",
        recruiter=newer_owner,
        priority=JobPriority.high,
    )
    tied_older_job = await contact_db.add_job(
        label="tied-older",
        recruiter=older_owner,
        priority=JobPriority.high,
    )
    priority_candidate = await contact_db.add_candidate(label="priority")
    age_candidate = await contact_db.add_candidate(label="linked-age")

    priority_case = CandidateContactCase(
        candidate_id=priority_candidate.id,
        state=CandidateContactState.unassigned.value,
        due_at=BASE_TIME + timedelta(hours=7),
    )
    age_case = CandidateContactCase(
        candidate_id=age_candidate.id,
        state=CandidateContactState.unassigned.value,
        due_at=BASE_TIME + timedelta(hours=7),
    )
    contact_db.db.add_all([priority_case, age_case])
    await contact_db.db.flush()
    contact_db.db.add_all(
        [
            CandidateContactOpportunity(
                case_id=priority_case.id,
                candidate_id=priority_candidate.id,
                job_id=low_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
            CandidateContactOpportunity(
                case_id=priority_case.id,
                candidate_id=priority_candidate.id,
                job_id=high_job.id,
                source="pipeline",
                linked_at=BASE_TIME + timedelta(hours=1),
            ),
            CandidateContactOpportunity(
                case_id=age_case.id,
                candidate_id=age_candidate.id,
                job_id=tied_newer_job.id,
                source="pipeline",
                linked_at=BASE_TIME + timedelta(hours=2),
            ),
            CandidateContactOpportunity(
                case_id=age_case.id,
                candidate_id=age_candidate.id,
                job_id=tied_older_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
        ]
    )
    await contact_db.commit()

    async with AsyncSessionLocal() as worker_db:
        stats = await process_contact_cases(
            worker_db,
            now=BASE_TIME + timedelta(hours=1),
        )
        await worker_db.commit()

    assert stats.assigned_from_waiting == 2
    priority_result = await _case_snapshot(priority_case.id)
    age_result = await _case_snapshot(age_case.id)
    assert priority_result.owner_user_id == high_owner.id
    assert priority_result.primary_job_id == high_job.id
    assert age_result.owner_user_id == older_owner.id
    assert age_result.primary_job_id == tied_older_job.id


async def test_concurrent_fallback_selection_observes_latest_load(
    contact_db: ContactDb,
) -> None:
    first_fallback = await contact_db.add_user(
        UserRole.sourcer, label="balanced-fallback-a"
    )
    second_fallback = await contact_db.add_user(
        UserRole.tac, label="balanced-fallback-b"
    )
    job = await contact_db.add_job(
        label="balanced-fallback",
        recruiter=None,
        priority=JobPriority.high,
    )
    await contact_db.add_collaborator(job=job, user=first_fallback)
    await contact_db.add_collaborator(job=job, user=second_fallback)

    cases: list[CandidateContactCase] = []
    for index in range(2):
        candidate = await contact_db.add_candidate(label=f"balanced-{index}")
        case = CandidateContactCase(
            candidate_id=candidate.id,
            state=CandidateContactState.unassigned.value,
            due_at=BASE_TIME + timedelta(hours=7),
        )
        contact_db.db.add(case)
        await contact_db.db.flush()
        contact_db.db.add(
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            )
        )
        cases.append(case)
    await contact_db.commit()

    async def run_worker() -> None:
        async with AsyncSessionLocal() as worker_db:
            await process_contact_cases(
                worker_db,
                now=BASE_TIME + timedelta(hours=1),
                limit=1,
            )
            await worker_db.commit()

    await asyncio.gather(run_worker(), run_worker())

    async with AsyncSessionLocal() as verification_db:
        owners = set(
            (
                await verification_db.execute(
                    select(CandidateContactCase.owner_user_id).where(
                        CandidateContactCase.id.in_([case.id for case in cases])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert owners == {first_fallback.id, second_fallback.id}


async def test_parallel_workers_never_allocate_twenty_first_slot(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="capacity-owner")
    job = await contact_db.add_job(
        label="capacity",
        recruiter=owner,
        priority=JobPriority.urgent,
    )
    cases: list[CandidateContactCase] = []
    for index in range(21):
        candidate = await contact_db.add_candidate(label=f"capacity-{index}")
        case = CandidateContactCase(
            candidate_id=candidate.id,
            state=CandidateContactState.unassigned.value,
            due_at=BASE_TIME + timedelta(hours=7),
        )
        contact_db.db.add(case)
        await contact_db.db.flush()
        contact_db.db.add(
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            )
        )
        cases.append(case)
    await contact_db.commit()

    async def run_worker() -> Any:
        async with AsyncSessionLocal() as worker_db:
            result = await process_contact_cases(
                worker_db,
                now=BASE_TIME + timedelta(hours=1),
                limit=11,
            )
            await worker_db.commit()
            return result

    await asyncio.gather(run_worker(), run_worker())

    async with AsyncSessionLocal() as verification_db:
        rows = (
            await verification_db.execute(
                select(
                    CandidateContactCase.state,
                    CandidateContactCase.queue_slot,
                ).where(CandidateContactCase.id.in_([case.id for case in cases]))
            )
        ).all()
        queued_slots = [
            slot for state, slot in rows if state == CandidateContactState.queued.value
        ]
        assert len(queued_slots) == 20
        assert len(set(queued_slots)) == 20
        assert set(queued_slots) == set(range(1, 21))
        assert (
            sum(
                state == CandidateContactState.awaiting_capacity.value
                for state, _ in rows
            )
            == 1
        )

        # The database fence must reject a duplicate active owner/slot even if
        # an application bug bypasses the allocator.
        waiting_case = await verification_db.scalar(
            select(CandidateContactCase).where(
                CandidateContactCase.id.in_([case.id for case in cases]),
                CandidateContactCase.state
                == CandidateContactState.awaiting_capacity.value,
            )
        )
        assert waiting_case is not None
        waiting_case.owner_user_id = owner.id
        waiting_case.queue_slot = 20
        waiting_case.state = CandidateContactState.queued.value
        with pytest.raises(IntegrityError):
            await verification_db.flush()
        await verification_db.rollback()


async def test_retry_states_rotate_past_a_blocked_first_batch(
    contact_db: ContactDb,
) -> None:
    old_retry_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    cases: list[CandidateContactCase] = []
    for index in range(3):
        candidate = await contact_db.add_candidate(
            label=f"fair-retry-{index}",
            phone=None,
        )
        case = CandidateContactCase(
            candidate_id=candidate.id,
            state=CandidateContactState.blocked_no_phone.value,
            blocked_phone_value=None,
            due_at=None,
            updated_at=old_retry_at,
        )
        contact_db.db.add(case)
        cases.append(case)
    await contact_db.commit()

    async with AsyncSessionLocal() as first_worker:
        first = await process_contact_cases(
            first_worker,
            now=BASE_TIME,
            limit=2,
        )
        await first_worker.commit()
    assert first.scanned == 2

    untouched_after_first = await _case_snapshot(cases[2].id)
    assert untouched_after_first.updated_at == old_retry_at

    async with AsyncSessionLocal() as second_worker:
        second = await process_contact_cases(
            second_worker,
            now=BASE_TIME + timedelta(minutes=1),
            limit=2,
        )
        await second_worker.commit()
    assert second.scanned == 2

    reached_on_second_batch = await _case_snapshot(cases[2].id)
    assert reached_on_second_batch.updated_at > old_retry_at


async def test_capacity_retry_refreshes_expired_due_before_assignment(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="late-capacity-owner")
    candidate = await contact_db.add_candidate(label="late-capacity")
    job = await contact_db.add_job(label="late-capacity", recruiter=owner)
    case = CandidateContactCase(
        candidate_id=candidate.id,
        state=CandidateContactState.unassigned.value,
        due_at=BASE_TIME - timedelta(days=1),
    )
    contact_db.db.add(case)
    await contact_db.db.flush()
    contact_db.db.add(
        CandidateContactOpportunity(
            case_id=case.id,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            linked_at=BASE_TIME - timedelta(days=1),
        )
    )
    await contact_db.commit()

    after_hours = BASE_TIME + timedelta(hours=9)
    async with AsyncSessionLocal() as worker_db:
        first = await process_contact_cases(
            worker_db,
            now=after_hours,
        )
        await worker_db.commit()
    assigned = await _case_snapshot(case.id)
    assert first.assigned_from_waiting == 1
    assert assigned.state == CandidateContactState.queued.value
    assert assigned.owner_user_id == owner.id
    assert assigned.due_at is not None
    assert assigned.due_at > after_hours

    async with AsyncSessionLocal() as next_tick_db:
        next_tick = await process_contact_cases(
            next_tick_db,
            now=after_hours + timedelta(minutes=1),
        )
        await next_tick_db.commit()
    assert next_tick.reassigned == 0
    still_assigned = await _case_snapshot(case.id)
    assert still_assigned.owner_user_id == owner.id


async def test_idempotent_attempt_race_replays_once_and_rejects_conflicts(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="idempotency-owner")
    candidate = await contact_db.add_candidate(label="idempotency")
    job = await contact_db.add_job(label="idempotency", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    expected_version = case.version
    await contact_db.commit()

    async def submit() -> tuple[int, bool]:
        async with AsyncSessionLocal() as attempt_db:
            result = await record_contact_attempt(
                attempt_db,
                case_id=case_id,
                actor_user_id=owner.id,
                outcome="no_answer",
                opportunity_outcomes=None,
                expected_version=expected_version,
                idempotency_key=f"{contact_db.prefix}-same-attempt",
                occurred_at=BASE_TIME + timedelta(minutes=15),
            )
            await attempt_db.commit()
            return result.call.id, result.replayed

    first, second = await asyncio.gather(submit(), submit())
    assert first[0] == second[0]
    assert {first[1], second[1]} == {False, True}

    async with AsyncSessionLocal() as verification_db:
        assert (
            await verification_db.scalar(
                select(func.count(Call.id)).where(Call.contact_case_id == case_id)
            )
            == 1
        )
        with pytest.raises(ContactIdempotencyConflict):
            await record_contact_attempt(
                verification_db,
                case_id=case_id,
                actor_user_id=owner.id,
                outcome="wrong_number",
                opportunity_outcomes=None,
                expected_version=expected_version,
                idempotency_key=f"{contact_db.prefix}-same-attempt",
                occurred_at=BASE_TIME + timedelta(minutes=15),
            )
        await verification_db.rollback()

    async with AsyncSessionLocal() as stale_db:
        with pytest.raises(ContactCaseVersionConflict):
            await record_contact_attempt(
                stale_db,
                case_id=case_id,
                actor_user_id=owner.id,
                outcome="no_answer",
                opportunity_outcomes=None,
                expected_version=expected_version,
                idempotency_key=f"{contact_db.prefix}-stale-version",
                occurred_at=BASE_TIME + timedelta(minutes=20),
            )


async def test_attempt_guards_read_case_state_after_the_row_lock(
    contact_db: ContactDb,
) -> None:
    """Optimistic guards muszą porównywać stan PO zdjęciu blokady wiersza.

    Endpoint ładuje sprawę bez blokady (``db.get``) i dopiero potem woła
    serwis tą samą sesją, więc wiersz siedzi już w identity mapie. To NIE jest
    rzadki wyścig: ``record_contact_attempt`` blokuje się na locku Candidate,
    który trzyma współbieżne ``ensure_contact_opportunity`` — czyli dokładnie
    ta transakcja, która podbija ``version``. Bez ``populate_existing`` select
    ``FOR UPDATE`` oddaje zmapowaną instancję nietkniętą i guard porównuje
    wartości sprzed blokady.
    """

    owner = await contact_db.add_user(UserRole.recruiter, label="postlock-owner")
    candidate = await contact_db.add_candidate(label="postlock")
    job = await contact_db.add_job(label="postlock", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    stale_version = case.version
    await contact_db.commit()

    async with AsyncSessionLocal() as request_db:
        # Odwzorowanie preloadu z endpointu — sprawa wchodzi do identity mapy.
        preloaded = await request_db.get(CandidateContactCase, case_id)
        assert preloaded is not None
        assert preloaded.version == stale_version

        # Współbieżny pisarz commituje, gdy request czekałby na blokady.
        async with AsyncSessionLocal() as writer_db:
            await writer_db.execute(
                update(CandidateContactCase)
                .where(CandidateContactCase.id == case_id)
                .values(version=CandidateContactCase.version + 1)
            )
            await writer_db.commit()

        with pytest.raises(ContactCaseVersionConflict):
            await record_contact_attempt(
                request_db,
                case_id=case_id,
                actor_user_id=owner.id,
                outcome="no_answer",
                opportunity_outcomes=None,
                expected_version=stale_version,
                idempotency_key=f"{contact_db.prefix}-postlock",
                occurred_at=BASE_TIME + timedelta(minutes=5),
            )
        # Instancja w sesji musi nieść wartość po blokadzie, nie sprzed niej.
        assert preloaded.version == stale_version + 1
        await request_db.rollback()


async def test_reassign_guards_read_case_state_after_the_row_lock(
    contact_db: ContactDb,
) -> None:
    """Ta sama pułapka na ścieżce reassign — endpoint też preloaduje sprawę."""

    owner = await contact_db.add_user(UserRole.recruiter, label="postlock-re-owner")
    candidate = await contact_db.add_candidate(label="postlock-re")
    job = await contact_db.add_job(label="postlock-re", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    stale_version = case.version
    await contact_db.commit()

    async with AsyncSessionLocal() as request_db:
        preloaded = await request_db.get(CandidateContactCase, case_id)
        assert preloaded is not None

        async with AsyncSessionLocal() as writer_db:
            await writer_db.execute(
                update(CandidateContactCase)
                .where(CandidateContactCase.id == case_id)
                .values(version=CandidateContactCase.version + 1)
            )
            await writer_db.commit()

        with pytest.raises(ContactCaseVersionConflict):
            await reassign_contact_case(
                request_db,
                case_id=case_id,
                actor_user_id=owner.id,
                reason="stale-guard",
                expected_version=stale_version,
                occurred_at=BASE_TIME + timedelta(minutes=5),
            )
        assert preloaded.version == stale_version + 1
        await request_db.rollback()


async def test_two_no_answers_start_cooldown_then_choose_different_owner(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="no-answer-a")
    fallback_owner = await contact_db.add_user(UserRole.tac, label="no-answer-b")
    candidate = await contact_db.add_candidate(label="no-answer")
    job = await contact_db.add_job(
        label="no-answer",
        recruiter=first_owner,
        tac=fallback_owner,
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    version = case.version
    await contact_db.commit()

    async with AsyncSessionLocal() as first_db:
        first = await record_contact_attempt(
            first_db,
            case_id=case_id,
            actor_user_id=first_owner.id,
            outcome="no_answer",
            opportunity_outcomes=None,
            expected_version=version,
            idempotency_key=f"{contact_db.prefix}-no-answer-1",
            occurred_at=BASE_TIME + timedelta(hours=1),
        )
        await first_db.commit()
        second_version = first.case.version

    async with AsyncSessionLocal() as second_db:
        second = await record_contact_attempt(
            second_db,
            case_id=case_id,
            actor_user_id=first_owner.id,
            outcome="no_answer",
            opportunity_outcomes=None,
            expected_version=second_version,
            idempotency_key=f"{contact_db.prefix}-no-answer-2",
            occurred_at=BASE_TIME + timedelta(days=1),
        )
        await second_db.commit()
        cooldown_until = second.case.cooldown_until

    assert second.case.state == CandidateContactState.cooldown.value
    assert second.case.owner_user_id is None
    assert second.case.queue_slot is None
    assert second.case.previous_owner_user_id == first_owner.id
    assert cooldown_until == BASE_TIME + timedelta(days=4)

    async with AsyncSessionLocal() as worker_db:
        stats = await process_contact_cases(
            worker_db,
            now=cooldown_until + timedelta(minutes=1),
        )
        await worker_db.commit()

    reassigned = await _case_snapshot(case_id)
    assert stats.cooldown_released == 1
    assert stats.reassigned == 1
    assert reassigned.owner_user_id == fallback_owner.id
    assert reassigned.previous_owner_user_id == first_owner.id
    assert reassigned.state == CandidateContactState.queued.value
    assert reassigned.queue_slot is not None
    assert reassigned.cycle == 2


async def test_closing_one_opportunity_does_not_bypass_cooldown(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="close-cooldown")
    candidate = await contact_db.add_candidate(label="close-cooldown")
    first_job = await contact_db.add_job(label="close-cooldown-a", recruiter=owner)
    second_job = await contact_db.add_job(label="close-cooldown-b", recruiter=owner)
    cooldown_until = BASE_TIME + timedelta(hours=72)
    case = CandidateContactCase(
        candidate_id=candidate.id,
        previous_owner_user_id=owner.id,
        state=CandidateContactState.cooldown.value,
        attempt_count=2,
        cooldown_until=cooldown_until,
        due_at=cooldown_until,
    )
    contact_db.db.add(case)
    await contact_db.db.flush()
    contact_db.db.add_all(
        [
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=first_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=second_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
        ]
    )
    await contact_db.commit()

    preserved = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        reason="job_closed",
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()
    assert preserved is not None
    assert preserved.state == CandidateContactState.cooldown.value
    assert preserved.cooldown_until == cooldown_until
    assert preserved.owner_user_id is None
    assert preserved.queue_slot is None

    completed = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        reason="job_closed",
        occurred_at=BASE_TIME + timedelta(hours=2),
    )
    await contact_db.commit()
    assert completed is not None
    assert completed.state == CandidateContactState.completed.value
    assert completed.cooldown_until is None


async def test_closing_one_opportunity_does_not_bypass_wrong_number_block(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="close-phone-block")
    candidate = await contact_db.add_candidate(label="close-phone-block")
    first_job = await contact_db.add_job(label="close-phone-a", recruiter=owner)
    second_job = await contact_db.add_job(label="close-phone-b", recruiter=owner)
    case = CandidateContactCase(
        candidate_id=candidate.id,
        state=CandidateContactState.blocked_no_phone.value,
        blocked_phone_value=candidate.phone,
    )
    contact_db.db.add(case)
    await contact_db.db.flush()
    contact_db.db.add_all(
        [
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=first_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=second_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            ),
        ]
    )
    await contact_db.commit()

    preserved = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        reason="job_closed",
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()
    assert preserved is not None
    assert preserved.state == CandidateContactState.blocked_no_phone.value
    assert preserved.blocked_phone_value == candidate.phone
    assert preserved.owner_user_id is None
    assert preserved.queue_slot is None


async def test_closing_owned_opportunity_moves_queued_case_to_remaining_owner(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="close-owner-a")
    remaining_owner = await contact_db.add_user(
        UserRole.recruiter, label="close-owner-b"
    )
    candidate = await contact_db.add_candidate(label="close-owner-transfer")
    first_job = await contact_db.add_job(label="close-owner-a", recruiter=first_owner)
    remaining_job = await contact_db.add_job(
        label="close-owner-b", recruiter=remaining_owner
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=remaining_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    original_due = case.due_at
    await contact_db.commit()

    transferred = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        reason="job_closed",
        actor_user_id=first_owner.id,
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()

    assert transferred is not None
    assert transferred.state == CandidateContactState.queued.value
    assert transferred.owner_user_id == remaining_owner.id
    assert transferred.queue_slot is not None
    assert transferred.due_at == original_due


async def test_callback_manual_reassign_preserves_state_and_due(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="callback-a")
    target_owner = await contact_db.add_user(UserRole.tac, label="callback-b")
    candidate = await contact_db.add_candidate(label="callback-preserve")
    job = await contact_db.add_job(
        label="callback-preserve",
        recruiter=first_owner,
        tac=target_owner,
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    callback_due = BASE_TIME + timedelta(hours=8)
    case.state = CandidateContactState.callback_due.value
    case.due_at = callback_due
    await contact_db.commit()

    reassigned = await reassign_contact_case(
        contact_db.db,
        case_id=case.id,
        actor_user_id=first_owner.id,
        reason="manual_coverage",
        expected_version=case.version,
        target_user_id=target_owner.id,
        occurred_at=BASE_TIME + timedelta(hours=2),
    )
    await contact_db.commit()

    assert reassigned.state == CandidateContactState.callback_due.value
    assert reassigned.owner_user_id == target_owner.id
    assert reassigned.due_at == callback_due

    turnover = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)
    first_tick = await process_contact_cases(contact_db.db, now=turnover)
    await contact_db.commit()
    after_turnover = await _case_snapshot(case.id)
    assert first_tick.reassigned == 1
    assert after_turnover.state == CandidateContactState.callback_due.value
    assert after_turnover.due_at is not None
    assert after_turnover.due_at > turnover

    second_tick = await process_contact_cases(
        contact_db.db,
        now=turnover + timedelta(minutes=1),
    )
    await contact_db.commit()
    assert second_tick.reassigned == 0


@pytest.mark.parametrize(
    "state",
    [
        CandidateContactState.handoff_pending.value,
        CandidateContactState.blocked_no_phone.value,
    ],
)
async def test_manual_relationship_owner_transfer_ignores_slot_capacity(
    contact_db: ContactDb,
    state: str,
) -> None:
    first_owner = await contact_db.add_user(
        UserRole.recruiter, label=f"{state}-transfer-a"
    )
    full_target = await contact_db.add_user(UserRole.tac, label=f"{state}-transfer-b")
    job = await contact_db.add_job(
        label=f"{state}-transfer",
        recruiter=first_owner,
        tac=full_target,
    )
    for slot in range(1, 21):
        filler_candidate = await contact_db.add_candidate(label=f"{state}-full-{slot}")
        contact_db.db.add(
            CandidateContactCase(
                candidate_id=filler_candidate.id,
                owner_user_id=full_target.id,
                state=CandidateContactState.queued.value,
                queue_slot=slot,
                assigned_at=BASE_TIME,
                due_at=BASE_TIME + timedelta(hours=7),
            )
        )

    candidate = await contact_db.add_candidate(label=f"{state}-transfer")
    contact_case = CandidateContactCase(
        candidate_id=candidate.id,
        owner_user_id=first_owner.id,
        state=state,
        attempt_count=1,
        cycle=3,
        assigned_at=BASE_TIME,
        blocked_phone_value=(
            candidate.phone
            if state == CandidateContactState.blocked_no_phone.value
            else None
        ),
    )
    contact_db.db.add(contact_case)
    await contact_db.db.flush()
    contact_db.db.add(
        CandidateContactOpportunity(
            case_id=contact_case.id,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            linked_at=BASE_TIME,
            outcome=(
                "interested"
                if state == CandidateContactState.handoff_pending.value
                else None
            ),
            presented_at=(
                BASE_TIME
                if state == CandidateContactState.handoff_pending.value
                else None
            ),
        )
    )
    await contact_db.commit()

    changed = await reassign_contact_case(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=first_owner.id,
        reason="manager_coverage",
        expected_version=contact_case.version,
        target_user_id=full_target.id,
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()

    assert changed.state == state
    assert changed.owner_user_id == full_target.id
    assert changed.previous_owner_user_id == first_owner.id
    assert changed.queue_slot is None
    assert changed.due_at is None
    assert changed.attempt_count == 1
    assert changed.cycle == 3
    event = await contact_db.db.scalar(
        select(CandidateContactEvent)
        .where(CandidateContactEvent.case_id == contact_case.id)
        .order_by(CandidateContactEvent.id.desc())
        .limit(1)
    )
    assert event is not None
    assert event.event_type == "reassigned"
    assert event.details["relationship_only"] is True


async def test_manual_ownerless_handoff_assignment_preserves_relationship_state(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="ownerless-manual")
    candidate = await contact_db.add_candidate(label="ownerless-manual")
    job = await contact_db.add_job(label="ownerless-manual", recruiter=owner)
    contact_case = CandidateContactCase(
        candidate_id=candidate.id,
        state=CandidateContactState.handoff_pending.value,
        attempt_count=1,
        cycle=4,
    )
    contact_db.db.add(contact_case)
    await contact_db.db.flush()
    contact_db.db.add(
        CandidateContactOpportunity(
            case_id=contact_case.id,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            linked_at=BASE_TIME,
            outcome="interested",
            presented_at=BASE_TIME,
        )
    )
    await contact_db.commit()

    changed = await reassign_contact_case(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=owner.id,
        reason="assign_ownerless_handoff",
        expected_version=contact_case.version,
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()

    assert changed.state == CandidateContactState.handoff_pending.value
    assert changed.owner_user_id == owner.id
    assert changed.queue_slot is None
    assert changed.due_at is None
    assert changed.attempt_count == 1
    assert changed.cycle == 4
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactEvent.id)).where(
                CandidateContactEvent.case_id == contact_case.id,
                CandidateContactEvent.event_type == "reassigned",
            )
        )
        == 1
    )


async def test_worker_reassigns_inactive_owner_before_friday_due(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="inactive-a")
    fallback_owner = await contact_db.add_user(UserRole.tac, label="inactive-b")
    candidate = await contact_db.add_candidate(label="inactive-friday")
    job = await contact_db.add_job(
        label="inactive-friday",
        recruiter=first_owner,
        tac=fallback_owner,
    )
    friday_morning = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=friday_morning,
    )
    assert case is not None
    original_due = case.due_at
    first_owner.is_active = False
    await contact_db.commit()

    stats = await process_contact_cases(
        contact_db.db,
        now=friday_morning + timedelta(hours=1),
    )
    await contact_db.commit()
    reassigned = await _case_snapshot(case.id)

    assert stats.reassigned == 1
    assert reassigned.owner_user_id == fallback_owner.id
    assert reassigned.state == CandidateContactState.queued.value
    assert reassigned.due_at == original_due


async def test_worker_blocks_cleared_phone_before_due_without_reassignment(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="phone-cleared")
    fallback = await contact_db.add_user(UserRole.tac, label="phone-cleared-fallback")
    candidate = await contact_db.add_candidate(label="phone-cleared")
    job = await contact_db.add_job(
        label="phone-cleared",
        recruiter=owner,
        tac=fallback,
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    await contact_db.db.execute(
        update(Candidate).where(Candidate.id == candidate.id).values(phone=None)
    )
    await contact_db.commit()

    stats = await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(minutes=5),
    )
    await contact_db.commit()
    blocked = await _case_snapshot(case.id)
    assert stats.reassigned == 0
    assert blocked.state == CandidateContactState.blocked_no_phone.value
    assert blocked.owner_user_id == owner.id
    assert blocked.queue_slot is None


async def test_wrong_number_restore_retains_fallback_owner(
    contact_db: ContactDb,
) -> None:
    primary = await contact_db.add_user(UserRole.recruiter, label="wrong-primary")
    fallback = await contact_db.add_user(UserRole.tac, label="wrong-fallback")
    candidate = await contact_db.add_candidate(label="wrong-retain")
    job = await contact_db.add_job(
        label="wrong-retain",
        recruiter=primary,
        tac=fallback,
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    case = await reassign_contact_case(
        contact_db.db,
        case_id=case.id,
        actor_user_id=primary.id,
        target_user_id=fallback.id,
        expected_version=case.version,
        reason="coverage",
        occurred_at=BASE_TIME + timedelta(minutes=5),
    )
    await contact_db.commit()
    blocked = await record_contact_attempt(
        contact_db.db,
        case_id=case.id,
        actor_user_id=fallback.id,
        outcome="wrong_number",
        opportunity_outcomes=None,
        expected_version=case.version,
        idempotency_key=f"{contact_db.prefix}-wrong-retain",
        occurred_at=BASE_TIME + timedelta(minutes=10),
    )
    await contact_db.commit()
    assert blocked.case.owner_user_id == fallback.id

    await contact_db.db.execute(
        update(Candidate)
        .where(Candidate.id == candidate.id)
        .values(phone="+48 799 800 901")
    )
    await contact_db.commit()
    await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(minutes=20),
    )
    await contact_db.commit()
    restored = await _case_snapshot(case.id)
    assert restored.state == CandidateContactState.queued.value
    assert restored.owner_user_id == fallback.id


async def test_closing_owned_handoff_moves_relationship_owner_without_slot(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="handoff-a")
    remaining_owner = await contact_db.add_user(UserRole.recruiter, label="handoff-b")
    candidate = await contact_db.add_candidate(label="handoff-owner-transfer")
    first_job = await contact_db.add_job(label="handoff-a", recruiter=first_owner)
    remaining_job = await contact_db.add_job(
        label="handoff-b", recruiter=remaining_owner
    )
    case = CandidateContactCase(
        candidate_id=candidate.id,
        owner_user_id=first_owner.id,
        state=CandidateContactState.handoff_pending.value,
        assigned_at=BASE_TIME,
    )
    contact_db.db.add(case)
    await contact_db.db.flush()
    contact_db.db.add_all(
        [
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=first_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
                outcome="interested",
                presented_at=BASE_TIME,
            ),
            CandidateContactOpportunity(
                case_id=case.id,
                candidate_id=candidate.id,
                job_id=remaining_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
                outcome="interested",
                presented_at=BASE_TIME,
            ),
        ]
    )
    await contact_db.commit()

    transferred = await close_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        reason="job_closed",
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()

    assert transferred is not None
    assert transferred.state == CandidateContactState.handoff_pending.value
    assert transferred.owner_user_id == remaining_owner.id
    assert transferred.queue_slot is None


async def test_ownerless_handoff_rotation_does_not_spam_or_starve_due_work(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="fair-due-a")
    fallback = await contact_db.add_user(UserRole.tac, label="fair-due-b")
    handoff_cases: list[CandidateContactCase] = []
    old_retry_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for index in range(3):
        candidate = await contact_db.add_candidate(label=f"ownerless-{index}")
        handoff = CandidateContactCase(
            candidate_id=candidate.id,
            state=CandidateContactState.handoff_pending.value,
            updated_at=old_retry_at,
        )
        contact_db.db.add(handoff)
        handoff_cases.append(handoff)

    due_candidate = await contact_db.add_candidate(label="fair-due")
    due_job = await contact_db.add_job(
        label="fair-due",
        recruiter=owner,
        tac=fallback,
    )
    due_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=due_candidate.id,
        job_id=due_job.id,
        source="pipeline",
        occurred_at=datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
    )
    assert due_case is not None
    due_case.due_at = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)
    initial_versions = [item.version for item in handoff_cases]
    await contact_db.commit()

    first = await process_contact_cases(
        contact_db.db,
        now=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
        limit=2,
    )
    await contact_db.commit()
    reassigned_due = await _case_snapshot(due_case.id)
    assert first.reassigned == 1
    assert reassigned_due.owner_user_id == fallback.id

    await process_contact_cases(
        contact_db.db,
        now=datetime(2026, 8, 1, 8, 1, tzinfo=timezone.utc),
        limit=2,
    )
    await contact_db.commit()
    snapshots = [await _case_snapshot(item.id) for item in handoff_cases]
    assert [item.version for item in snapshots] == initial_versions


async def test_closed_job_contact_intake_is_noop(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="closed-intake")
    candidate = await contact_db.add_candidate(label="closed-intake")
    job = await contact_db.add_job(label="closed-intake", recruiter=owner)
    job.status = JobStatus.closed
    await contact_db.commit()

    result = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    await contact_db.commit()

    assert result is None
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactCase.id)).where(
                CandidateContactCase.candidate_id == candidate.id
            )
        )
        == 0
    )


async def test_concurrent_job_close_cannot_miss_inflight_contact_intake(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="close-race")
    candidate = await contact_db.add_candidate(label="close-race")
    job = await contact_db.add_job(label="close-race", recruiter=owner)
    await contact_db.commit()
    intake_ready = asyncio.Event()
    close_waiting = asyncio.Event()
    allow_intake_commit = asyncio.Event()

    async def run_intake() -> None:
        async with AsyncSessionLocal() as intake_db:
            created = await ensure_contact_opportunity(
                intake_db,
                candidate_id=candidate.id,
                job_id=job.id,
                source="pipeline",
                occurred_at=BASE_TIME,
            )
            assert created is not None
            intake_ready.set()
            await allow_intake_commit.wait()
            await intake_db.commit()

    async def run_close() -> None:
        await intake_ready.wait()
        async with AsyncSessionLocal() as close_db:
            closing_job = await close_db.get(Job, job.id)
            assert closing_job is not None
            closing_job.status = JobStatus.closed
            close_waiting.set()
            await close_job_contact_opportunities(
                close_db,
                job_id=job.id,
                reason="job_closed",
                occurred_at=BASE_TIME + timedelta(hours=1),
            )
            await close_db.commit()

    intake_task = asyncio.create_task(run_intake())
    close_task = asyncio.create_task(run_close())
    await close_waiting.wait()
    await asyncio.sleep(0.05)
    allow_intake_commit.set()
    await asyncio.gather(intake_task, close_task)

    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.candidate_id == candidate.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.closed_at is not None


async def test_pipeline_removal_keeps_contact_triggered_by_outreach_shortlist(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="trigger-shortlist")
    candidate = await contact_db.add_candidate(label="trigger-shortlist")
    job = await contact_db.add_job(label="trigger-shortlist", recruiter=owner)
    shortlist = JobShortlistEntry(
        job_id=job.id,
        candidate_id=candidate.id,
        outreach_status="do_kontaktu",
        created_by=owner.id,
    )
    stage = CandidateStage(
        candidate_id=candidate.id,
        job_id=job.id,
        stage=PipelineStage.new,
        moved_at=BASE_TIME,
        moved_by=owner.id,
    )
    contact_db.db.add_all([shortlist, stage])
    await contact_db.commit()
    await contact_db.db.execute(
        delete(CandidateStage).where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == job.id,
        )
    )

    assert await has_active_contact_trigger(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
    )


async def test_shortlist_removal_uses_latest_pipeline_stage_not_any_history(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="trigger-terminal")
    candidate = await contact_db.add_candidate(label="trigger-terminal")
    job = await contact_db.add_job(label="trigger-terminal", recruiter=owner)
    shortlist = JobShortlistEntry(
        job_id=job.id,
        candidate_id=candidate.id,
        outreach_status="do_kontaktu",
        created_by=owner.id,
    )
    contact_db.db.add_all(
        [
            shortlist,
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.new,
                moved_at=BASE_TIME,
                moved_by=owner.id,
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.rejected,
                moved_at=BASE_TIME + timedelta(hours=1),
                moved_by=owner.id,
            ),
        ]
    )
    await contact_db.commit()

    assert not await has_active_contact_trigger(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        exclude_shortlist_entry_id=shortlist.id,
    )


async def test_deleted_job_keeps_closed_opportunity_and_audit_is_immutable(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="delete-audit-owner")
    candidate = await contact_db.add_candidate(label="delete-audit")
    job = await contact_db.add_job(label="delete-audit", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    await contact_db.commit()

    changed = await close_job_contact_opportunities(
        contact_db.db,
        job_id=job.id,
        actor_user_id=owner.id,
        reason="job_deleted",
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    assert [item.id for item in changed] == [case.id]
    await contact_db.db.delete(job)
    await contact_db.commit()

    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == case.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.closed_reason == "job_deleted"
    assert opportunity.closed_at == BASE_TIME + timedelta(hours=1)

    event_id = await contact_db.db.scalar(
        select(CandidateContactEvent.id)
        .where(
            CandidateContactEvent.case_id == case.id,
            CandidateContactEvent.event_type == "opportunity_closed",
        )
        .order_by(CandidateContactEvent.id.desc())
        .limit(1)
    )
    assert event_id is not None

    async with AsyncSessionLocal() as mutation_db:
        with pytest.raises(DBAPIError, match="append-only"):
            await mutation_db.execute(
                update(CandidateContactEvent)
                .where(CandidateContactEvent.id == event_id)
                .values(event_type="tampered")
            )
        await mutation_db.rollback()

    async with AsyncSessionLocal() as mutation_db:
        with pytest.raises(DBAPIError, match="append-only"):
            await mutation_db.execute(
                delete(CandidateContactEvent).where(
                    CandidateContactEvent.id == event_id
                )
            )
        await mutation_db.rollback()


async def test_completed_handoff_can_finish_a_phone_blocked_case(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="blocked-handoff")
    candidate = await contact_db.add_candidate(label="blocked-handoff")
    job = await contact_db.add_job(label="blocked-handoff", recruiter=owner)
    event = await contact_db.add_calendar_event(
        candidate=candidate,
        job=job,
        creator=owner,
        label="blocked-handoff",
    )
    case = CandidateContactCase(
        candidate_id=candidate.id,
        state=CandidateContactState.blocked_no_phone.value,
        blocked_phone_value=candidate.phone,
    )
    contact_db.db.add(case)
    await contact_db.db.flush()
    contact_db.db.add(
        CandidateContactOpportunity(
            case_id=case.id,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            linked_at=BASE_TIME,
            outcome="interested",
            presented_at=BASE_TIME,
        )
    )
    await contact_db.commit()

    completed = await sync_calendar_handoff(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        event_id=event.id,
        scheduled=True,
        actor_user_id=owner.id,
        occurred_at=BASE_TIME + timedelta(hours=1),
    )
    await contact_db.commit()
    assert completed is not None
    assert completed.state == CandidateContactState.completed.value
    assert completed.blocked_phone_value == candidate.phone

    new_job = await contact_db.add_job(label="blocked-handoff-new", recruiter=owner)
    reopened = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=new_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(hours=2),
    )
    await contact_db.commit()
    assert reopened.state == CandidateContactState.blocked_no_phone.value
    assert reopened.queue_slot is None

    await contact_db.db.execute(
        update(Candidate)
        .where(Candidate.id == candidate.id)
        .values(phone="+48 700 800 900")
    )
    await contact_db.commit()
    await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(hours=3),
    )
    await contact_db.commit()
    restored = await _case_snapshot(case.id)
    assert restored.state == CandidateContactState.queued.value
    assert restored.blocked_phone_value is None


async def test_existing_calendar_handoff_is_applied_during_opportunity_intake(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="event-first-owner")
    candidate = await contact_db.add_candidate(label="event-first")
    job = await contact_db.add_job(label="event-first", recruiter=owner)
    event = await contact_db.add_calendar_event(
        candidate=candidate,
        job=job,
        creator=owner,
        label="event-first",
    )
    await contact_db.commit()

    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    await contact_db.commit()
    assert case is not None
    assert case.state == CandidateContactState.completed.value
    assert case.queue_slot is None
    opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == case.id,
            CandidateContactOpportunity.job_id == job.id,
        )
    )
    assert opportunity is not None
    assert opportunity.meeting_event_id == event.id
    assert opportunity.outcome == "interested"


async def test_event_before_second_opportunity_keeps_first_call_owner_and_slot(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="event-second-a")
    second_owner = await contact_db.add_user(UserRole.recruiter, label="event-second-b")
    candidate = await contact_db.add_candidate(label="event-second")
    first_job = await contact_db.add_job(label="event-second-a", recruiter=first_owner)
    second_job = await contact_db.add_job(
        label="event-second-b", recruiter=second_owner
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    original_slot = case.queue_slot
    await contact_db.add_calendar_event(
        candidate=candidate,
        job=second_job,
        creator=second_owner,
        label="event-before-second",
    )
    await contact_db.commit()

    same_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=5),
    )
    await contact_db.commit()
    assert same_case is not None
    assert same_case.id == case.id
    assert same_case.state == CandidateContactState.queued.value
    assert same_case.owner_user_id == first_owner.id
    assert same_case.queue_slot == original_slot


async def test_event_before_second_opportunity_does_not_requeue_handoff_only_case(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="handoff-event-a")
    second_owner = await contact_db.add_user(
        UserRole.recruiter, label="handoff-event-b"
    )
    candidate = await contact_db.add_candidate(label="handoff-event-second")
    first_job = await contact_db.add_job(label="handoff-event-a", recruiter=owner)
    second_job = await contact_db.add_job(
        label="handoff-event-b", recruiter=second_owner
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert case is not None
    connected = await record_contact_attempt(
        contact_db.db,
        case_id=case.id,
        actor_user_id=owner.id,
        outcome="connected",
        opportunity_outcomes={first_job.id: "interested"},
        expected_version=case.version,
        idempotency_key=f"{contact_db.prefix}-handoff-event-first",
        occurred_at=BASE_TIME + timedelta(minutes=5),
    )
    assert connected.case.state == CandidateContactState.handoff_pending.value
    assert connected.case.queue_slot is None
    event = await contact_db.add_calendar_event(
        candidate=candidate,
        job=second_job,
        creator=second_owner,
        label="handoff-before-second",
    )
    await contact_db.commit()

    same_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=10),
    )
    await contact_db.commit()

    assert same_case is not None
    assert same_case.id == case.id
    assert same_case.state == CandidateContactState.handoff_pending.value
    assert same_case.owner_user_id == owner.id
    assert same_case.queue_slot is None
    second_opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == case.id,
            CandidateContactOpportunity.job_id == second_job.id,
        )
    )
    assert second_opportunity is not None
    assert second_opportunity.outcome == "interested"
    assert second_opportunity.meeting_event_id == event.id


async def test_existing_mixed_handoff_respects_assignment_kill_switch(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="event-off-a")
    second_owner = await contact_db.add_user(UserRole.recruiter, label="event-off-b")
    candidate = await contact_db.add_candidate(label="event-off")
    first_job = await contact_db.add_job(label="event-off-a", recruiter=first_owner)
    second_job = await contact_db.add_job(label="event-off-b", recruiter=second_owner)
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
        assign_if_possible=False,
    )
    assert contact_case is not None
    event = await contact_db.add_calendar_event(
        candidate=candidate,
        job=second_job,
        creator=second_owner,
        label="event-off",
    )
    await contact_db.commit()

    same_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=5),
        assign_if_possible=False,
    )
    await contact_db.commit()

    assert same_case is not None
    assert same_case.id == contact_case.id
    assert same_case.state == CandidateContactState.unassigned.value
    assert same_case.owner_user_id is None
    assert same_case.queue_slot is None
    second_opportunity = await contact_db.db.scalar(
        select(CandidateContactOpportunity).where(
            CandidateContactOpportunity.case_id == contact_case.id,
            CandidateContactOpportunity.job_id == second_job.id,
        )
    )
    assert second_opportunity is not None
    assert second_opportunity.outcome == "interested"
    assert second_opportunity.meeting_event_id == event.id


async def test_assignment_off_new_offer_returns_handoff_owner_to_queue_when_enabled(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="handoff-off-owner")
    candidate = await contact_db.add_candidate(label="handoff-off")
    first_job = await contact_db.add_job(label="handoff-off-a", recruiter=owner)
    second_job = await contact_db.add_job(label="handoff-off-b", recruiter=owner)
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert contact_case is not None
    connected = await record_contact_attempt(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=owner.id,
        outcome="connected",
        opportunity_outcomes={first_job.id: "interested"},
        expected_version=contact_case.version,
        idempotency_key=f"{contact_db.prefix}-handoff-off",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    assert connected.case.state == CandidateContactState.handoff_pending.value
    await contact_db.commit()

    pending = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=2),
        assign_if_possible=False,
    )
    await contact_db.commit()
    assert pending is not None
    assert pending.state == CandidateContactState.unassigned.value
    assert pending.owner_user_id == owner.id
    assert pending.queue_slot is None

    stats = await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(minutes=3),
    )
    await contact_db.commit()
    queued = await _case_snapshot(contact_case.id)
    assert stats.assigned_from_waiting == 1
    assert queued.state == CandidateContactState.queued.value
    assert queued.owner_user_id == owner.id
    assert queued.queue_slot is not None


async def test_completed_case_reopened_with_assignment_off_can_return_to_former_owner(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="completed-off-owner")
    candidate = await contact_db.add_candidate(label="completed-off")
    first_job = await contact_db.add_job(label="completed-off-a", recruiter=owner)
    second_job = await contact_db.add_job(label="completed-off-b", recruiter=owner)
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert contact_case is not None
    completed = await record_contact_attempt(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=owner.id,
        outcome="connected",
        opportunity_outcomes={first_job.id: "not_interested"},
        expected_version=contact_case.version,
        idempotency_key=f"{contact_db.prefix}-completed-off",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    assert completed.case.state == CandidateContactState.completed.value
    assert completed.case.previous_owner_user_id == owner.id
    await contact_db.commit()

    pending = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=2),
        assign_if_possible=False,
    )
    await contact_db.commit()
    assert pending is not None
    assert pending.state == CandidateContactState.unassigned.value
    assert pending.owner_user_id is None
    assert pending.previous_owner_user_id is None
    assert pending.queue_slot is None

    stats = await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(minutes=3),
    )
    await contact_db.commit()
    queued = await _case_snapshot(contact_case.id)
    assert stats.assigned_from_waiting == 1
    assert queued.state == CandidateContactState.queued.value
    assert queued.owner_user_id == owner.id
    assert queued.queue_slot is not None


async def test_full_sticky_handoff_owner_waits_without_fallback_reassignment(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="sticky-full-owner")
    fallback = await contact_db.add_user(UserRole.tac, label="sticky-full-fallback")
    candidate = await contact_db.add_candidate(label="sticky-full")
    first_job = await contact_db.add_job(
        label="sticky-full-a",
        recruiter=owner,
        tac=fallback,
    )
    second_job = await contact_db.add_job(
        label="sticky-full-b",
        recruiter=owner,
        tac=fallback,
    )
    contact_case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=first_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    assert contact_case is not None
    connected = await record_contact_attempt(
        contact_db.db,
        case_id=contact_case.id,
        actor_user_id=owner.id,
        outcome="connected",
        opportunity_outcomes={first_job.id: "interested"},
        expected_version=contact_case.version,
        idempotency_key=f"{contact_db.prefix}-sticky-full",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    assert connected.case.state == CandidateContactState.handoff_pending.value

    filler_job = await contact_db.add_job(label="sticky-fillers", recruiter=owner)
    for slot in range(1, 21):
        filler = await contact_db.add_candidate(label=f"sticky-filler-{slot}")
        filler_case = CandidateContactCase(
            candidate_id=filler.id,
            owner_user_id=owner.id,
            state=CandidateContactState.queued.value,
            queue_slot=slot,
            assigned_at=BASE_TIME,
            due_at=BASE_TIME + timedelta(days=1),
        )
        contact_db.db.add(filler_case)
        await contact_db.db.flush()
        contact_db.db.add(
            CandidateContactOpportunity(
                case_id=filler_case.id,
                candidate_id=filler.id,
                job_id=filler_job.id,
                source="pipeline",
                linked_at=BASE_TIME,
            )
        )
    await contact_db.commit()

    waiting = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=second_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=2),
    )
    await contact_db.commit()
    assert waiting is not None
    assert waiting.state == CandidateContactState.awaiting_capacity.value
    assert waiting.owner_user_id == owner.id
    assert waiting.queue_slot is None

    stats = await process_contact_cases(
        contact_db.db,
        now=BASE_TIME + timedelta(minutes=3),
    )
    await contact_db.commit()
    still_waiting = await _case_snapshot(contact_case.id)
    assert stats.reassigned == 0
    assert still_waiting.state == CandidateContactState.awaiting_capacity.value
    assert still_waiting.owner_user_id == owner.id
    assert still_waiting.owner_user_id != fallback.id
    assert still_waiting.queue_slot is None


async def test_connected_releases_slot_but_keeps_handoff_owner_and_calendar_cycles(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="handoff-owner")
    candidate = await contact_db.add_candidate(label="handoff")
    job = await contact_db.add_job(label="handoff", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    initial_version = case.version
    await contact_db.commit()

    async with AsyncSessionLocal() as attempt_db:
        result = await record_contact_attempt(
            attempt_db,
            case_id=case_id,
            actor_user_id=owner.id,
            outcome="connected",
            opportunity_outcomes={job.id: "interested"},
            expected_version=initial_version,
            idempotency_key=f"{contact_db.prefix}-connected",
            occurred_at=BASE_TIME + timedelta(minutes=20),
        )
        await attempt_db.commit()

    assert result.case.state == CandidateContactState.handoff_pending.value
    assert result.case.owner_user_id == owner.id
    assert result.case.queue_slot is None

    event = await contact_db.add_calendar_event(
        candidate=candidate,
        job=job,
        creator=owner,
        label="cycle",
    )
    completed_replacement = await contact_db.add_calendar_event(
        candidate=candidate,
        job=job,
        creator=owner,
        label="completed-replacement",
    )
    completed_replacement.status = EventStatus.completed
    await contact_db.commit()

    async with AsyncSessionLocal() as calendar_db:
        scheduled = await sync_calendar_handoff(
            calendar_db,
            candidate_id=candidate.id,
            job_id=job.id,
            event_id=event.id,
            scheduled=True,
            actor_user_id=owner.id,
            occurred_at=BASE_TIME + timedelta(hours=1),
        )
        await calendar_db.commit()
    assert scheduled is not None
    assert scheduled.state == CandidateContactState.completed.value

    async with AsyncSessionLocal() as cancel_db:
        await cancel_db.execute(
            update(CalendarEvent)
            .where(CalendarEvent.id == event.id)
            .values(status=EventStatus.cancelled)
        )
        cancelled = await sync_calendar_handoff(
            cancel_db,
            candidate_id=candidate.id,
            job_id=job.id,
            event_id=event.id,
            scheduled=False,
            actor_user_id=owner.id,
            occurred_at=BASE_TIME + timedelta(hours=2),
        )
        replacement_opportunity = await cancel_db.scalar(
            select(CandidateContactOpportunity).where(
                CandidateContactOpportunity.case_id == case_id,
                CandidateContactOpportunity.job_id == job.id,
            )
        )
        await cancel_db.commit()
    assert cancelled is not None
    assert cancelled.state == CandidateContactState.completed.value
    assert replacement_opportunity is not None
    assert replacement_opportunity.meeting_event_id == completed_replacement.id

    async with AsyncSessionLocal() as final_cancel_db:
        await final_cancel_db.execute(
            update(CalendarEvent)
            .where(CalendarEvent.id == completed_replacement.id)
            .values(status=EventStatus.cancelled)
        )
        fully_cancelled = await sync_calendar_handoff(
            final_cancel_db,
            candidate_id=candidate.id,
            job_id=job.id,
            event_id=completed_replacement.id,
            scheduled=False,
            actor_user_id=owner.id,
            occurred_at=BASE_TIME + timedelta(hours=2, minutes=30),
        )
        await final_cancel_db.commit()
    assert fully_cancelled is not None
    assert fully_cancelled.state == CandidateContactState.handoff_pending.value
    assert fully_cancelled.owner_user_id == owner.id
    assert fully_cancelled.queue_slot is None

    # A schedule -> cancel -> reschedule cycle must remain auditable and must
    # not collide with a globally unique, static event idempotency key.
    async with AsyncSessionLocal() as reschedule_db:
        await reschedule_db.execute(
            update(CalendarEvent)
            .where(CalendarEvent.id == event.id)
            .values(status=EventStatus.scheduled)
        )
        rescheduled = await sync_calendar_handoff(
            reschedule_db,
            candidate_id=candidate.id,
            job_id=job.id,
            event_id=event.id,
            scheduled=True,
            actor_user_id=owner.id,
            occurred_at=BASE_TIME + timedelta(hours=3),
        )
        await reschedule_db.commit()
    assert rescheduled is not None
    assert rescheduled.state == CandidateContactState.completed.value
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactEvent.id)).where(
                CandidateContactEvent.case_id == case_id,
                CandidateContactEvent.event_type == "handoff_scheduled",
            )
        )
        == 2
    )


async def test_restart_catches_friday_eod_once_on_monday_morning(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="eod-a")
    fallback_owner = await contact_db.add_user(UserRole.tac, label="eod-b")
    candidate = await contact_db.add_candidate(label="eod")
    job = await contact_db.add_job(
        label="eod",
        recruiter=first_owner,
        tac=fallback_owner,
    )
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
    )
    case_id = case.id
    friday_18_warsaw = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)
    await contact_db.db.execute(
        update(CandidateContactCase)
        .where(CandidateContactCase.id == case_id)
        .values(due_at=friday_18_warsaw)
    )
    await contact_db.commit()

    monday_09_warsaw = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as first_worker:
        first_stats = await process_contact_cases(
            first_worker,
            now=monday_09_warsaw,
        )
        await first_worker.commit()
    after_first = await _case_snapshot(case_id)

    async with AsyncSessionLocal() as restarted_worker:
        second_stats = await process_contact_cases(
            restarted_worker,
            now=monday_09_warsaw,
        )
        await restarted_worker.commit()
    after_second = await _case_snapshot(case_id)

    assert first_stats.reassigned == 1
    assert after_first.owner_user_id == fallback_owner.id
    assert after_first.owner_user_id != first_owner.id
    assert after_first.version == after_second.version
    assert second_stats.reassigned == 0


async def test_eod_without_replacement_records_capacity_wait_not_reassignment(
    contact_db: ContactDb,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="eod-only-owner")
    candidate = await contact_db.add_candidate(label="eod-no-replacement")
    job = await contact_db.add_job(label="eod-no-replacement", recruiter=owner)
    assigned_at = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=assigned_at,
    )
    assert case is not None
    case_id = case.id
    case.due_at = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)
    case.assigned_at = assigned_at
    await contact_db.commit()

    stats = await process_contact_cases(
        contact_db.db,
        now=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
    )
    await contact_db.commit()

    waiting = await _case_snapshot(case_id)
    event_types = set(
        (
            await contact_db.db.execute(
                select(CandidateContactEvent.event_type).where(
                    CandidateContactEvent.case_id == case_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert stats.reassigned == 0
    assert waiting.state == CandidateContactState.unassigned.value
    assert waiting.owner_user_id is None
    assert waiting.queue_slot is None
    assert "awaiting_capacity" in event_types
    assert "reassigned" not in event_types


async def test_skip_locked_worker_processes_other_due_case(
    contact_db: ContactDb,
) -> None:
    first_owner = await contact_db.add_user(UserRole.recruiter, label="skip-a")
    fallback_owner = await contact_db.add_user(UserRole.tac, label="skip-b")
    job = await contact_db.add_job(
        label="skip-locked",
        recruiter=first_owner,
        tac=fallback_owner,
    )
    case_ids: list[int] = []
    for label in ("locked", "available"):
        candidate = await contact_db.add_candidate(label=label)
        case = await ensure_contact_opportunity(
            contact_db.db,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            occurred_at=BASE_TIME,
        )
        case_ids.append(case.id)
    overdue = BASE_TIME + timedelta(hours=7)
    await contact_db.db.execute(
        update(CandidateContactCase)
        .where(CandidateContactCase.id.in_(case_ids))
        .values(due_at=overdue)
    )
    await contact_db.commit()

    async with AsyncSessionLocal() as blocker:
        locked_id = min(case_ids)
        await blocker.scalar(
            select(CandidateContactCase)
            .where(CandidateContactCase.id == locked_id)
            .with_for_update()
        )
        async with AsyncSessionLocal() as worker:
            stats = await process_contact_cases(
                worker,
                now=BASE_TIME + timedelta(hours=9),
                limit=10,
            )
            await worker.commit()
        await blocker.rollback()

    available_id = max(case_ids)
    available = await _case_snapshot(available_id)
    locked = await _case_snapshot(locked_id)
    assert stats.scanned == 1
    assert stats.reassigned == 1
    assert available.owner_user_id == fallback_owner.id
    assert locked.owner_user_id == first_owner.id


async def test_feature_and_assignment_flags_are_fail_closed(
    contact_db: ContactDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="flags-owner")
    candidate = await contact_db.add_candidate(label="flags")
    historical_candidate = await contact_db.add_candidate(label="flags-historical")
    job = await contact_db.add_job(label="flags", recruiter=owner)
    await contact_db.commit()

    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", False)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )
    assert (
        await maybe_ensure_contact_opportunity(
            contact_db.db,
            candidate_id=candidate.id,
            job_id=job.id,
            source="pipeline",
            occurred_at=BASE_TIME,
        )
        is None
    )
    await contact_db.commit()
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactCase.id)).where(
                CandidateContactCase.candidate_id == candidate.id
            )
        )
        == 0
    )

    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    assert (
        await maybe_ensure_contact_opportunity(
            contact_db.db,
            candidate_id=historical_candidate.id,
            job_id=job.id,
            source="pipeline",
            occurred_at=BASE_TIME - timedelta(days=2),
        )
        is None
    )
    created = await maybe_ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    await contact_db.commit()
    assert created is not None
    assert created.state == CandidateContactState.unassigned.value
    assert created.owner_user_id is None
    assert created.queue_slot is None

    # The worker wrapper must also remain a no-op while assignment is OFF.
    assert await run_candidate_contact_queue_once(now=BASE_TIME) is None
    unchanged = await _case_for_candidate(candidate.id)
    assert unchanged.state == CandidateContactState.unassigned.value
    assert (
        await contact_db.db.scalar(
            select(func.count(CandidateContactCase.id)).where(
                CandidateContactCase.candidate_id == historical_candidate.id
            )
        )
        == 0
    )

    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED", True)
    worker_stats = await run_candidate_contact_queue_once(now=BASE_TIME)
    assert worker_stats is not None
    assigned = await _case_for_candidate(candidate.id)
    assert assigned.owner_user_id == owner.id
    assert assigned.queue_slot is not None
    assert assigned.state == CandidateContactState.queued.value


async def test_traffit_intake_off_makes_zero_remote_requests(
    contact_db: ContactDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingTraffitClient:
        def __init__(self) -> None:
            self.requests = 0

        async def get_paginated(self, *_args: Any, **_kwargs: Any):
            self.requests += 1
            if False:
                yield {}

    client = CountingTraffitClient()
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        False,
    )
    stats = await run_traffit_contact_intake_once(
        contact_db.db,
        client,  # type: ignore[arg-type]
        now=BASE_TIME,
    )
    assert stats.fetched == 0
    assert stats.processed == 0
    assert client.requests == 0


async def test_strict_terminal_watermark_blocks_stale_daily_start_then_newer_reopens(
    contact_db: ContactDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = f"pytest-contact-watermark-{contact_db.prefix}"
    candidate_external_id = f"candidate-watermark-{contact_db.prefix}"
    job_external_id = f"job-watermark-{contact_db.prefix}"
    id_base = 1_000_000_000_000 + (uuid.uuid4().int % 1_000_000_000)
    stale_id = str(id_base)
    terminal_id = str(id_base + 1)
    newer_id = str(id_base + 2)
    owner = await contact_db.add_user(UserRole.recruiter, label="watermark-owner")
    candidate = await contact_db.add_candidate(label="watermark")
    candidate.external_source = "traffit"
    candidate.external_id = candidate_external_id
    job = await contact_db.add_job(label="watermark", recruiter=owner)
    job.external_source = "traffit"
    job.external_id = job_external_id
    await contact_db.commit()

    class StaticTraffitClient:
        async def get_paginated(self, *_args: Any, **_kwargs: Any):
            yield {
                "id": terminal_id,
                "created_at": BASE_TIME.isoformat(),
                "employee": {"id": candidate_external_id},
                "recruitment": {"id": job_external_id},
                "workflow_state": {"type": "end-bad"},
            }

    monkeypatch.setattr(contact_traffit_task, "_STREAM", stream)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )

    try:
        strict_stats = await contact_traffit_task.run_traffit_contact_intake_once(
            contact_db.db,
            StaticTraffitClient(),  # type: ignore[arg-type]
            now=BASE_TIME + timedelta(minutes=1),
        )
        await contact_db.commit()
        assert strict_stats.processed == 1
        assert strict_stats.closed == 0
        assert (
            await contact_db.db.scalar(
                select(CandidateContactCase).where(
                    CandidateContactCase.candidate_id == candidate.id
                )
            )
            is None
        )

        stale_daily = await maybe_ensure_contact_opportunity(
            contact_db.db,
            candidate_id=candidate.id,
            job_id=job.id,
            source="traffit",
            source_external_ref=stale_id,
            occurred_at=BASE_TIME,
        )
        await contact_db.commit()
        assert stale_daily is None
        assert (
            await contact_db.db.scalar(
                select(CandidateContactCase).where(
                    CandidateContactCase.candidate_id == candidate.id
                )
            )
            is None
        )

        newer_daily = await maybe_ensure_contact_opportunity(
            contact_db.db,
            candidate_id=candidate.id,
            job_id=job.id,
            source="traffit",
            source_external_ref=newer_id,
            occurred_at=BASE_TIME,
        )
        await contact_db.commit()
        assert newer_daily is not None
        assert newer_daily.state == CandidateContactState.unassigned.value
        assert newer_daily.owner_user_id is None
        assert newer_daily.queue_slot is None
        opportunity = await contact_db.db.scalar(
            select(CandidateContactOpportunity).where(
                CandidateContactOpportunity.candidate_id == candidate.id,
                CandidateContactOpportunity.job_id == job.id,
            )
        )
        assert opportunity is not None
        assert opportunity.closed_at is None
        assert opportunity.source_cursor_external_id == newer_id
    finally:
        async with AsyncSessionLocal() as cleanup_db:
            await cleanup_db.execute(
                delete(CandidateContactTraffitLedger).where(
                    CandidateContactTraffitLedger.external_event_id == terminal_id,
                    CandidateContactTraffitLedger.candidate_id == candidate.id,
                    CandidateContactTraffitLedger.job_id == job.id,
                )
            )
            await cleanup_db.execute(
                delete(CandidateContactTraffitCursor).where(
                    CandidateContactTraffitCursor.stream == stream
                )
            )
            await cleanup_db.commit()


async def test_api_scope_roles_and_pii_projection(
    contact_db: ContactDb,
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="api-owner")
    other_owner = await contact_db.add_user(UserRole.recruiter, label="api-other")
    unrelated = await contact_db.add_user(UserRole.recruiter, label="api-unrelated")
    viewer = await contact_db.add_user(UserRole.user, label="api-viewer")
    manager = await contact_db.add_user(
        UserRole.head_of_recruitment,
        label="api-manager",
    )
    candidate = await contact_db.add_candidate(
        label="api-pii",
        phone="+48 501 234 567",
    )
    owner_job = await contact_db.add_job(label="api-owner", recruiter=owner)
    other_job = await contact_db.add_job(label="api-other", recruiter=other_owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=owner_job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=other_job.id,
        source="pipeline",
        occurred_at=BASE_TIME + timedelta(minutes=1),
    )
    case_id = case.id
    await contact_db.commit()
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)

    queue_response = await app_client.get(
        "/api/candidate-contact/queue",
        headers=_headers(owner),
    )
    assert queue_response.status_code == 200, queue_response.text
    queue_body = queue_response.json()
    matching_items = [item for item in queue_body["items"] if item["id"] == case_id]
    assert len(matching_items) == 1
    assert matching_items[0]["candidate"]["phone"] == "+48 501 234 567"
    assert {item["job_id"] for item in matching_items[0]["opportunities"]} == {
        owner_job.id,
        other_job.id,
    }

    partial_scope_response = await app_client.get(
        f"/api/candidate-contact/candidates/{candidate.id}",
        headers=_headers(other_owner),
    )
    assert partial_scope_response.status_code == 200, partial_scope_response.text
    partial_scope_case = partial_scope_response.json()
    assert partial_scope_case["candidate"]["phone"] == "+48 501 234 567"
    assert {item["job_id"] for item in partial_scope_case["opportunities"]} == {
        other_job.id
    }

    unrelated_response = await app_client.get(
        f"/api/candidate-contact/candidates/{candidate.id}",
        headers=_headers(unrelated),
    )
    assert unrelated_response.status_code == 200
    assert unrelated_response.json() is None
    assert "+48 501 234 567" not in unrelated_response.text

    viewer_response = await app_client.get(
        f"/api/candidate-contact/candidates/{candidate.id}",
        headers=_headers(viewer),
    )
    assert viewer_response.status_code == 403
    assert "+48 501 234 567" not in viewer_response.text

    oversight_response = await app_client.get(
        "/api/candidate-contact/oversight?limit=100",
        headers=_headers(manager),
    )
    assert oversight_response.status_code == 200, oversight_response.text
    manager_case = next(
        item for item in oversight_response.json()["items"] if item["id"] == case_id
    )
    assert manager_case["candidate"]["phone"] == "+48 501 234 567"
    assert {item["job_id"] for item in manager_case["opportunities"]} == {
        owner_job.id,
        other_job.id,
    }


async def test_attempt_api_returns_409_for_stale_expected_version(
    contact_db: ContactDb,
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await contact_db.add_user(UserRole.recruiter, label="api-version-owner")
    replacement = await contact_db.add_user(
        UserRole.recruiter,
        label="api-version-replacement",
    )
    candidate = await contact_db.add_candidate(label="api-version")
    job = await contact_db.add_job(label="api-version", recruiter=owner)
    case = await ensure_contact_opportunity(
        contact_db.db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="pipeline",
        occurred_at=BASE_TIME,
    )
    case_id = case.id
    stale_version = case.version
    await contact_db.commit()
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)

    first = await app_client.post(
        f"/api/candidate-contact/cases/{case_id}/attempts",
        headers={
            **_headers(owner),
            "Idempotency-Key": f"{contact_db.prefix}-api-first",
        },
        json={
            "expected_version": stale_version,
            "outcome": "no_answer",
            "opportunity_outcomes": [],
        },
    )
    assert first.status_code == 200, first.text

    # The same key remains idempotent after ownership changes, but replay must
    # not become a PII bypass after the original caller loses every linked job.
    job.recruiter_id = replacement.id
    await contact_db.commit()
    replay_without_scope = await app_client.post(
        f"/api/candidate-contact/cases/{case_id}/attempts",
        headers={
            **_headers(owner),
            "Idempotency-Key": f"{contact_db.prefix}-api-first",
        },
        json={
            "expected_version": stale_version,
            "outcome": "no_answer",
            "opportunity_outcomes": [],
        },
    )
    assert replay_without_scope.status_code == 403
    job.recruiter_id = owner.id
    await contact_db.commit()

    stale = await app_client.post(
        f"/api/candidate-contact/cases/{case_id}/attempts",
        headers={
            **_headers(owner),
            "Idempotency-Key": f"{contact_db.prefix}-api-stale",
        },
        json={
            "expected_version": stale_version,
            "outcome": "no_answer",
            "opportunity_outcomes": [],
        },
    )
    assert stale.status_code == 409, stale.text
    assert "version conflict" in stale.json()["detail"]
