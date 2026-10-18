"""Podwładni przy odejściu przełożonego (etap 2, D5, 17.10.2026).

Piąty rodzaj pracy w przekazaniu: osoby z kartoteką, których przełożonym jest
odchodzący. Domyślnie przejmuje przełożony odchodzącego; bez niego — nikt,
a przekazanie z podwładnymi kończy się ``failed`` jak inne rodzaje (konto
czeka na przekazanie, „Wyłącz konto teraz” bez „mimo to” = 409). Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service as service
from app.services.hr.handover import RECEIVER_ERRORS, receiver_problem, work_summary
from app.services.hr.lifecycle_jobs import run_once
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from app.services.hr_lifecycle_schema import TRANSFER_KINDS

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
    """Jak w ``test_hr_handover.py``: pętla bierze wszystkie żywe odejścia
    wspólnej bazy, więc cudze sprawy zamykamy przed testem."""

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


async def _team(*, leader_has_manager: bool = True) -> dict:
    """Szefowa → kierowniczka (odchodzi) → dwie osoby + wnuczka pod pierwszą."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:

        def person(label: str, role: str = "employee") -> User:
            user = User(
                email=f"reports-{label}-{tag}@example.com",
                name=f"Osoba {label} {tag}",
                role=UserRole(role),
                roles=[role],
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            return user

        hr = person("kadry", "recruiter")
        boss = person("szefowa", "head_of_recruitment")
        leader = person("kierowniczka", "recruiter")
        first = person("pierwsza")
        second = person("druga")
        grandchild = person("wnuczka")
        gone = person("byla")
        await db.flush()
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id),
                EmployeeProfile(
                    user_id=leader.id,
                    manager_user_id=boss.id if leader_has_manager else None,
                ),
                EmployeeProfile(user_id=first.id, manager_user_id=leader.id),
                EmployeeProfile(user_id=second.id, manager_user_id=leader.id),
                EmployeeProfile(user_id=grandchild.id, manager_user_id=first.id),
                # Zakończyła współpracę — nie jest podwładną do przekazania.
                EmployeeProfile(
                    user_id=gone.id,
                    manager_user_id=leader.id,
                    employment_status="exited",
                ),
            ]
        )
        await db.commit()
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=leader.id,
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
            "leader": leader.id,
            "first": first.id,
            "second": second.id,
            "grandchild": grandchild.id,
            "gone": gone.id,
            "case": case.id,
            "last_day": case.last_working_day,
        }


async def _row(db, case_id: int) -> WorkHandover:
    return await db.scalar(
        select(WorkHandover).where(
            WorkHandover.case_id == case_id, WorkHandover.work_kind == "reports"
        )
    )


async def _manager_of(db, user_id: int) -> Optional[int]:
    return await db.scalar(
        select(EmployeeProfile.manager_user_id).where(
            EmployeeProfile.user_id == user_id
        )
    )


def test_reports_are_the_fifth_transfer_kind() -> None:
    # Szósty rodzaj (etap 3, O11) to opieka nad konsultantami.
    assert TRANSFER_KINDS[4] == "reports" and len(TRANSFER_KINDS) == 6
    employee = User(id=7, role=UserRole.employee, roles=["employee"], is_active=True)
    bot = User(id=8, role=UserRole.automation, roles=["automation"], is_active=True)
    assert receiver_problem(employee, "reports", 1) is None
    assert receiver_problem(bot, "reports", 1) == "receiver_not_eligible"
    assert receiver_problem(employee, "reports", 7) == "receiver_is_leaver"


@pytest.mark.asyncio
async def test_plan_counts_reports_and_defaults_to_leavers_manager(modules_on) -> None:
    team = await _team()
    async with AsyncSessionLocal() as db:
        row = await _row(db, team["case"])
        counts = await work_summary(
            db, team["leader"], last_working_day=team["last_day"]
        )
        case = await db.get(LifecycleCase, team["case"])
        payload = await service.case_payload(
            db, case, viewer=await db.get(User, team["hr"]), scope="admin"
        )
    assert row.receiver_user_id == team["boss"]
    assert row.item_count == 2, "osoba, która odeszła, się nie liczy"
    assert counts["reports"] == 2
    work = {item["kind"]: item for item in payload["work"]}
    assert work["reports"]["label"] == "Podwładni"
    assert work["reports"]["transferable"] is True
    assert work["reports"]["receiver_user_id"] == team["boss"]


@pytest.mark.asyncio
async def test_handover_moves_reports_to_receiver_with_trail(modules_on) -> None:
    team = await _team()
    result = await run_once_at(_at(team["last_day"], 18, 5))
    assert result["handover_failed"] == 0
    async with AsyncSessionLocal() as db:
        assert await _manager_of(db, team["first"]) == team["boss"]
        assert await _manager_of(db, team["second"]) == team["boss"]
        assert await _manager_of(db, team["grandchild"]) == team["first"]
        assert await _manager_of(db, team["gone"]) == team["leader"]
        row = await _row(db, team["case"])
        assert row.status == "done" and row.result == {"people": 2}
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id.in_([team["first"], team["second"]]),
                    HrAuditEvent.action == "profile_updated",
                )
            )
        )
        assert len(trail) == 2
        assert {event.details["source"] for event in trail} == {"hr_work_handover"}
        assert {event.details["manager_user_id"] for event in trail} == {team["boss"]}
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == team["boss"],
                Notification.notification_type == NotificationType.hr_work_handover,
            )
        )
        assert bell is not None and "podwładni: 2" in bell.message
        assert bell.link == "/people/team"


@pytest.mark.asyncio
async def test_without_receiver_reports_fail_and_account_waits(modules_on) -> None:
    team = await _team(leader_has_manager=False)
    async with AsyncSessionLocal() as db:
        assert (await _row(db, team["case"])).receiver_user_id is None
    result = await run_once_at(_at(team["last_day"], 18, 5))
    assert result["handover_failed"] == 1
    async with AsyncSessionLocal() as db:
        row = await _row(db, team["case"])
        assert row.status == "failed" and row.error == "no_receiver"
        assert await _manager_of(db, team["first"]) == team["leader"]
        case = await db.get(LifecycleCase, team["case"])
        assert case.handover_executed_at is None
        # Dzień wyłączenia minął — bez „mimo to” konto czeka na przekazanie.
        await db.execute(
            text(
                "UPDATE lifecycle_cases SET last_working_day = :last, "
                "deactivate_on = :off WHERE id = :id"
            ),
            {
                "last": business_today() - timedelta(days=2),
                "off": business_today() - timedelta(days=1),
                "id": team["case"],
            },
        )
        await db.commit()
        case = await db.get(LifecycleCase, team["case"])
        await db.refresh(case)
        hr = await db.get(User, team["hr"])
        with pytest.raises(service.LifecycleConflict, match="podwładni"):
            await service.deactivate_now(db, case, actor=hr, despite_handover=False)
        await db.rollback()


@pytest.mark.asyncio
async def test_direct_report_as_receiver_takes_the_leavers_place(modules_on) -> None:
    team = await _team()
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, team["case"])
        hr = await db.get(User, team["hr"])
        await service.set_receivers(
            db, case, actor=hr, receivers={"reports": team["first"]}
        )
        await db.commit()
    await run_once_at(_at(team["last_day"], 18, 5))
    async with AsyncSessionLocal() as db:
        assert await _manager_of(db, team["second"]) == team["first"]
        # Awans w miejsce kierowniczki: przełożoną zostaje jej szefowa.
        assert await _manager_of(db, team["first"]) == team["boss"]
        assert await _manager_of(db, team["grandchild"]) == team["first"]
        assert (await _row(db, team["case"])).status == "done"


@pytest.mark.asyncio
async def test_receiver_under_a_report_would_make_a_loop(modules_on) -> None:
    team = await _team()
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, team["case"])
        hr = await db.get(User, team["hr"])
        with pytest.raises(service.LifecycleError) as refused:
            await service.set_receivers(
                db, case, actor=hr, receivers={"reports": team["grandchild"]}
            )
        await db.rollback()
    assert str(refused.value) == RECEIVER_ERRORS["receiver_creates_loop"]


async def run_once_at(now: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        return await run_once(db, now=now)
