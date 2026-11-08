"""Wyłączenie konta zwalnia przypisania do rekrutacji (audyt 08.11.2026, B8)."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.client import Client
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.account_assignment_release import (
    planned_release,
    release_user_assignments,
)
from app.services.account_deactivation import deactivate_account

pytestmark = pytest.mark.asyncio


async def _db_or_skip():
    pytest.importorskip("asyncpg")
    from sqlalchemy import text

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable for integration test: {exc}")


def _user(role: UserRole, *, active: bool = True) -> User:
    tag = uuid.uuid4().hex[:8]
    return User(
        email=f"release-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!PassX"),
        name=f"Release {tag}",
        role=role,
        is_active=active,
    )


async def _world(db):
    recruiter = _user(UserRole.recruiter)
    lead = _user(UserRole.delivery_lead)
    client = Client(name=f"ReleaseClient-{uuid.uuid4().hex[:8]}")
    db.add_all([recruiter, lead, client])
    await db.flush()

    def job(status: JobStatus, owner: int | None) -> Job:
        return Job(
            title=f"Rekrutacja-{uuid.uuid4().hex[:8]}",
            client_id=client.id,
            status=status,
            recruiter_id=owner,
            delivery_lead_id=lead.id,
        )

    owned = job(JobStatus.published, recruiter.id)
    assigned = job(JobStatus.published, None)
    proposed = job(JobStatus.published, None)
    closed = job(JobStatus.closed, recruiter.id)
    db.add_all([owned, assigned, proposed, closed])
    await db.flush()
    db.add_all(
        [
            JobWorkAssignment(
                job_id=assigned.id,
                user_id=recruiter.id,
                role="recruiter",
                source="manual",
                state="active",
            ),
            JobWorkAssignment(
                job_id=proposed.id,
                user_id=recruiter.id,
                role="recruiter",
                source="auto",
                state="proposed",
            ),
        ]
    )
    await db.commit()
    return recruiter, lead, owned, assigned, proposed, closed


async def _assignment(db, job: Job, user: User) -> JobWorkAssignment:
    return await db.scalar(
        select(JobWorkAssignment).where(
            JobWorkAssignment.job_id == job.id, JobWorkAssignment.user_id == user.id
        )
    )


async def _bells(db, lead: User) -> set[int]:
    rows = await db.scalars(
        select(Notification.related_entity_id).where(
            Notification.user_id == lead.id,
            Notification.notification_type == NotificationType.recruiter_parked,
        )
    )
    return set(rows.all())


async def test_release_frees_open_recruitments_and_tells_the_dl():
    await _db_or_skip()
    async with AsyncSessionLocal() as db:
        recruiter, lead, owned, assigned, proposed, closed = await _world(db)
        recruiter.is_active = False

        released = await release_user_assignments(db, recruiter, actor_id=None)
        await db.commit()

        assert set(released) == {owned.id, assigned.id}
        await db.refresh(owned)
        await db.refresh(closed)
        assert owned.recruiter_id is None
        # Zamknięta rekrutacja zachowuje prowadzącego: historia i metryki.
        assert closed.recruiter_id == recruiter.id

        active = await _assignment(db, assigned, recruiter)
        assert (active.state, active.release_reason) == ("released", "deactivated")
        assert active.released_at is not None
        idea = await _assignment(db, proposed, recruiter)
        assert (idea.state, idea.release_reason) == (
            "released",
            "proposal:deactivated",
        )

        # Sama propozycja to nie była praca: bez dzwonka.
        assert await _bells(db, lead) == {owned.id, assigned.id}
        trail = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "job",
                Activity.entity_id == owned.id,
                Activity.action == "owner_released",
            )
        )
        assert trail.details["reason"] == "deactivated"


async def test_release_twice_changes_nothing():
    await _db_or_skip()
    async with AsyncSessionLocal() as db:
        recruiter, lead, *_ = await _world(db)
        await release_user_assignments(db, recruiter, actor_id=None)
        await db.commit()

        assert await planned_release(db, recruiter.id) == {}
        assert await release_user_assignments(db, recruiter, actor_id=None) == []


async def test_person_without_assignments_is_left_alone():
    await _db_or_skip()
    async with AsyncSessionLocal() as db:
        lonely = _user(UserRole.recruiter)
        db.add(lonely)
        await db.commit()
        assert await release_user_assignments(db, lonely, actor_id=None) == []


async def test_deactivating_an_account_releases_its_assignments():
    await _db_or_skip()
    async with AsyncSessionLocal() as db:
        recruiter, _lead, owned, *_ = await _world(db)
        await deactivate_account(
            db, recruiter, action="user_deactivated", actor_id=None, details={}
        )
        await db.commit()
        await db.refresh(owned)
        assert owned.recruiter_id is None
        assert recruiter.is_active is False


async def test_pending_handover_keeps_assignments_for_the_receiver():
    # Przekazanie szuka rekrutacji po tych wierszach (`hr/handover.py`).
    await _db_or_skip()
    async with AsyncSessionLocal() as db:
        recruiter, _lead, owned, assigned, *_ = await _world(db)
        today = datetime.now(timezone.utc).date()
        case = LifecycleCase(
            kind="offboarding",
            user_id=recruiter.id,
            status="active",
            last_working_day=today,
        )
        db.add(case)
        await db.commit()

        assert await release_user_assignments(db, recruiter, actor_id=None) == []
        await db.refresh(owned)
        assert owned.recruiter_id == recruiter.id
        live = await _assignment(db, assigned, recruiter)
        assert live.state == "active"

        # Po przekazaniu nic już nie blokuje zwolnienia resztek.
        db.add(
            WorkHandover(
                case_id=case.id,
                work_kind="recruitments",
                status="done",
                executed_at=datetime.now(timezone.utc),
                result={"moved": 0},
            )
        )
        await db.commit()
        assert owned.id in await release_user_assignments(db, recruiter, actor_id=None)


async def test_failed_release_does_not_stop_deactivation(monkeypatch):
    await _db_or_skip()
    from app.services import account_assignment_release as release

    async def broken(*_args, **_kwargs):
        raise RuntimeError("awaria zwolnienia")

    monkeypatch.setattr(release, "release_user_assignments", broken)
    async with AsyncSessionLocal() as db:
        recruiter, _lead, owned, *_ = await _world(db)
        await deactivate_account(
            db, recruiter, action="user_deactivated", actor_id=None, details={}
        )
        await db.commit()
        await db.refresh(owned)
        assert recruiter.is_active is False
        assert owned.recruiter_id == recruiter.id
