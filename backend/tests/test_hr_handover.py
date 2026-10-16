"""Odejście = przekazanie pracy (krok E4): po 18:00 ostatniego dnia, nie wcześniej,
istniejącymi ścieżkami zapisu, idempotentnie, z wynikiem w liczbach.

Świat: odchodząca osoba prowadzi rekrutację, jest Delivery Leadem innej,
głównym opiekunem klienta i ma osobę na liście „Moi ludzie”. Przejmuje
przełożony (rekruter i Delivery Lead). Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.hr_profile import EmployeeProfile
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.my_people import MyPeopleOverride
from app.models.notification import Notification, NotificationType
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service as service
from app.services.hr.handover import receiver_problem, work_summary
from app.services.hr.lifecycle_jobs import run_once
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from app.services.job_team import jobs_worked_by_clause

WARSAW = ZoneInfo("Europe/Warsaw")


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    """Moduły włączone i czysta karta pętli: bez rezerwacji przebiegów i bez
    żywych odejść z innych testów (wspólna baza — pętla bierze wszystkie)."""

    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_lifecycle%'")
        )
        await db.execute(
            text(
                "UPDATE lifecycle_cases SET status = 'cancelled' "
                "WHERE kind = 'offboarding' AND status IN ('draft', 'active')"
            )
        )
        await db.commit()
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _last_day() -> date:
    day = business_today() + timedelta(days=9)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WARSAW)


async def _world() -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:

        def person(label: str, roles: list[str]) -> User:
            user = User(
                email=f"handover-{label}-{tag}@example.com",
                name=f"Osoba {label} {tag}",
                role=UserRole(roles[0]),
                roles=roles,
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            return user

        hr = person("kadry", ["recruiter"])
        boss = person("szef", ["delivery_lead", "recruiter"])
        leaver = person("odchodzi", ["recruiter", "delivery_lead"])
        client = Client(name=f"Klient Przykładowy {tag}")
        db.add(client)
        await db.flush()
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id),
                EmployeeProfile(user_id=leaver.id, manager_user_id=boss.id),
            ]
        )
        recruited = Job(
            title=f"Rekrutacja prowadzona {tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=leaver.id,
        )
        led = Job(
            title=f"Rekrutacja DL {tag}",
            status=JobStatus.published,
            client_id=client.id,
            delivery_lead_id=leaver.id,
        )
        closed = Job(
            title=f"Rekrutacja zamknięta {tag}",
            status=JobStatus.closed,
            client_id=client.id,
            recruiter_id=leaver.id,
            delivery_lead_id=leaver.id,
        )
        db.add_all([recruited, led, closed])
        candidate = Candidate(name="Ola", lastname=f"Przykładowa{tag}")
        db.add(candidate)
        await db.flush()
        db.add_all(
            [
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=leaver.id, client_id=client.id, is_head=True
                ),
                MyPeopleOverride(
                    user_id=leaver.id, candidate_id=candidate.id, kind="pinned"
                ),
            ]
        )
        await db.commit()
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=leaver.id,
            last_working_day=_last_day(),
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=None,
            manager_given=False,
            template_id=None,
        )
        await service.start_case(db, case, actor=hr)
        await db.commit()
        return {
            "hr": hr.id,
            "boss": boss.id,
            "leaver": leaver.id,
            "client": client.id,
            "recruited": recruited.id,
            "led": led.id,
            "closed": closed.id,
            "candidate": candidate.id,
            "case": case.id,
            "last_day": case.last_working_day,
        }


async def _activities(db, action: str, entity_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.action == action, Activity.entity_id == entity_id
            )
        )
        or 0
    )


@pytest.mark.asyncio
async def test_summary_counts_what_the_person_has(modules_on) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        counts = await work_summary(
            db, world["leaver"], last_working_day=world["last_day"]
        )
    assert counts["recruitments"] == 1  # zamknięta się nie liczy
    assert counts["delivery_lead_jobs"] == 1
    assert counts["dl_clients"] == 1
    assert counts["my_people"] == 1
    assert set(counts) == {
        "recruitments",
        "pipeline_cards",
        "client_meetings",
        "followups",
        "my_people",
        "delivery_lead_jobs",
        "dl_clients",
        "substitutions",
    }


@pytest.mark.asyncio
async def test_handover_waits_for_18_00_then_moves_work_once(modules_on) -> None:
    world = await _world()
    last_day = world["last_day"]

    before = await _run(_at(last_day, 17, 50))
    assert before.get("handover_cases", 0) == 0
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["recruited"])
        assert job.recruiter_id == world["leaver"]
        case = await db.get(LifecycleCase, world["case"])
        assert case.handover_executed_at is None

    after = await _run(_at(last_day, 18, 5))
    assert after["handover_cases"] == 1
    assert after["handover_failed"] == 0
    async with AsyncSessionLocal() as db:
        working = await db.scalar(
            select(func.count(Job.id)).where(
                Job.id == world["recruited"], jobs_worked_by_clause([world["leaver"]])
            )
        )
        assert working == 0
        receiver_working = await db.scalar(
            select(func.count(Job.id)).where(
                Job.id == world["recruited"], jobs_worked_by_clause([world["boss"]])
            )
        )
        assert receiver_working == 1
        link = await db.scalar(
            select(JobCollaborator).where(
                JobCollaborator.job_id == world["recruited"],
                JobCollaborator.user_id == world["boss"],
            )
        )
        assert link is not None and link.source == JobCollaboratorSource.manual
        assert (await db.get(Job, world["led"])).delivery_lead_id == world["boss"]
        closed = await db.get(Job, world["closed"])
        assert closed.delivery_lead_id == world["leaver"], "zamkniętej nie ruszamy"
        assignment = await db.scalar(
            select(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.client_id == world["client"]
            )
        )
        assert assignment.delivery_lead_user_id == world["boss"]
        assert assignment.is_head is True
        pinned = await db.scalar(
            select(MyPeopleOverride).where(
                MyPeopleOverride.user_id == world["boss"],
                MyPeopleOverride.candidate_id == world["candidate"],
            )
        )
        assert pinned is not None and pinned.kind == "pinned"
        rows = {
            row.work_kind: row
            for row in await db.scalars(
                select(WorkHandover).where(WorkHandover.case_id == world["case"])
            )
        }
        assert {row.status for row in rows.values()} == {"done"}
        assert rows["recruitments"].result == {"jobs": 1}
        assert rows["dl_clients"].result == {"clients": 1, "heads": 1}
        assert rows["my_people"].result == {"people": 1, "pinned": 1}
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world["boss"],
                Notification.notification_type == NotificationType.hr_work_handover,
            )
        )
        assert bell is not None and "rekrutacje: 1" in bell.message
        released = await _activities(db, "owner_released", world["recruited"])
        updated = await _activities(db, "updated", world["led"])

    # Drugi przebieg: nic do przekazania, żadnych nowych wpisów.
    again = await _run(_at(last_day, 18, 35))
    assert again.get("handover_cases", 0) == 0
    async with AsyncSessionLocal() as db:
        assert await _activities(db, "owner_released", world["recruited"]) == released
        assert await _activities(db, "updated", world["led"]) == updated


@pytest.mark.asyncio
async def test_handover_without_eligible_receiver_fails_and_waits(modules_on) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(WorkHandover).where(
                WorkHandover.case_id == world["case"],
                WorkHandover.work_kind == "recruitments",
            )
        )
        row.receiver_user_id = None
        await db.commit()
    result = await _run(_at(world["last_day"], 18, 10))
    assert result["handover_failed"] == 1
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(WorkHandover).where(
                WorkHandover.case_id == world["case"],
                WorkHandover.work_kind == "recruitments",
            )
        )
        assert row.status == "failed" and row.error == "no_receiver"
        case = await db.get(LifecycleCase, world["case"])
        assert case.handover_executed_at is None
        job = await db.get(Job, world["recruited"])
        assert job.recruiter_id == world["leaver"], "bez przejmującego nic nie znika"
        warn = await db.scalar(
            select(Notification).where(
                Notification.user_id == world["hr"],
                Notification.notification_type == NotificationType.hr_lifecycle_task,
                Notification.related_entity_id == world["case"],
            )
        )
        assert warn is not None


def test_receiver_must_have_the_role_the_work_needs() -> None:
    recruiter = User(id=1, role=UserRole.recruiter, roles=["recruiter"], is_active=True)
    finance = User(id=2, role=UserRole.finance, roles=["finance"], is_active=True)
    inactive = User(id=3, role=UserRole.recruiter, roles=["recruiter"], is_active=False)
    assert receiver_problem(recruiter, "recruitments", 9) is None
    assert receiver_problem(finance, "recruitments", 9) == "receiver_not_eligible"
    assert receiver_problem(recruiter, "dl_clients", 9) == "receiver_not_eligible"
    assert receiver_problem(inactive, "recruitments", 9) == "receiver_inactive"
    assert receiver_problem(recruiter, "recruitments", 1) == "receiver_is_leaver"
    assert receiver_problem(None, "my_people", 9) == "no_receiver"


async def _run(now: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        return await run_once(db, now=now)
