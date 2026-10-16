"""Pętla „Wejście i odejście”: wyłączenie konta dzień po ostatnim dniu,
bezpieczniki (admin, masowe odejście, przywrócone konto), idempotencja,
poniedziałkowe przypomnienia, wyłączony moduł.

Zasady przejęte z ``compass_lifecycle`` (przepływ, który ten moduł zastępuje).
Dane fikcyjne.
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
from app.core.security import create_access_token
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service as service
from app.services.hr.deactivation import DEACTIVATION_ACTION, MAX_DEACTIVATIONS_PER_RUN
from app.services.hr.lifecycle_jobs import run_once, run_reminders
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

WARSAW = ZoneInfo("Europe/Warsaw")


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _clean_slate() -> None:
    """Wspólna baza: bez rezerwacji przebiegów i bez cudzych żywych odejść."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_lifecycle%'")
        )
        await db.execute(
            text(
                "UPDATE lifecycle_cases SET status = 'cancelled' "
                "WHERE status IN ('draft', 'active') AND user_id IS NOT NULL"
            )
        )
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _clean_slate()
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


async def _leaving(*, admin: bool = False, last_day: date | None = None) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hr = User(
            email=f"jobs-hr-{tag}@example.com",
            name=f"Kadry {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        boss = User(
            email=f"jobs-boss-{tag}@example.com",
            name=f"Przełożona {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        role = "admin" if admin else "recruiter"
        leaver = User(
            email=f"jobs-leaver-{tag}@example.com",
            name=f"Osoba Odchodząca {tag}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
        )
        db.add_all([hr, boss, leaver])
        await db.flush()
        db.add_all(
            [
                EmployeeProfile(user_id=boss.id),
                EmployeeProfile(user_id=leaver.id, manager_user_id=boss.id),
            ]
        )
        await db.commit()
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=leaver.id,
            last_working_day=last_day or _last_day(),
            exit_initiator="company",
            exit_reason="contract_end",
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
            "case": case.id,
            "last_day": case.last_working_day,
            "deactivate_on": case.deactivate_on,
        }


async def _run(now: datetime) -> dict:
    async with AsyncSessionLocal() as db:
        return await run_once(db, now=now)


async def _deactivations(db, user_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "user",
                Activity.entity_id == user_id,
                Activity.action == DEACTIVATION_ACTION,
            )
        )
        or 0
    )


@pytest.mark.asyncio
async def test_account_closes_the_day_after_the_last_day_and_only_once(
    modules_on,
) -> None:
    world = await _leaving()
    last_day = world["last_day"]

    await _run(_at(last_day, 23, 50))
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["leaver"])
        assert user.is_active is True, "w ostatnim dniu konto jeszcze działa"
        version = user.authorization_version

    result = await _run(_at(world["deactivate_on"], 0, 5))
    assert result["account_deactivated"] == 1
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["leaver"])
        assert user.is_active is False
        assert user.authorization_version == version + 1
        assert user.tokens_valid_after is not None
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == world["leaver"])
        )
        assert profile.employment_status == "exited"
        assert profile.exited_at is not None
        case = await db.get(LifecycleCase, world["case"])
        assert case.account_close_result == "deactivated"
        assert await _deactivations(db, world["leaver"]) == 1
        audit_rows = await db.scalar(
            text(
                "SELECT count(*) FROM hr_audit_events WHERE entity_type = 'lifecycle_case' "
                "AND entity_id = :id AND action = 'account_closed'"
            ),
            {"id": str(world["case"])},
        )
        assert audit_rows == 1

    await _run(_at(world["deactivate_on"], 0, 20))
    async with AsyncSessionLocal() as db:
        assert await _deactivations(db, world["leaver"]) == 1

    # Admin przywraca konto (powrót na umowę) — następny przebieg go nie ruszy.
    async with AsyncSessionLocal() as db:
        user = await db.get(User, world["leaver"])
        user.is_active = True
        await db.commit()
    await _run(_at(world["deactivate_on"], 0, 35))
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is True
        assert await _deactivations(db, world["leaver"]) == 1


@pytest.mark.asyncio
async def test_admin_account_is_never_closed_by_the_loop(modules_on) -> None:
    world = await _leaving(admin=True)
    result = await _run(_at(world["deactivate_on"], 9, 0))
    assert result["account_skipped_admin"] == 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is True
        case = await db.get(LifecycleCase, world["case"])
        assert case.account_close_result == "skipped_admin"
        assert await _deactivations(db, world["leaver"]) == 0


@pytest.mark.asyncio
async def test_mass_exit_closes_nothing_and_hr_closes_one_by_one(
    app_client, modules_on
) -> None:
    worlds = [await _leaving() for _ in range(MAX_DEACTIVATIONS_PER_RUN + 1)]
    deactivate_on = worlds[0]["deactivate_on"]
    result = await _run(_at(deactivate_on, 1, 0))
    assert result["deactivation_due"] == MAX_DEACTIVATIONS_PER_RUN + 1
    assert result["deactivation_error"] == "mass_exit_suspected"
    async with AsyncSessionLocal() as db:
        for world in worlds:
            assert (await db.get(User, world["leaver"])).is_active is True
        run = await db.scalar(
            text(
                "SELECT error FROM hr_job_runs WHERE kind = 'hr_lifecycle' "
                "ORDER BY id DESC LIMIT 1"
            )
        )
        assert run == "mass_exit_suspected"

    # „Wyłącz konto teraz”: jedno konto, Kadry, najwcześniej w dniu wyłączenia.
    target = worlds[0]
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, target["hr"])
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        await db.commit()
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=hr.id, role=hr.role.value)}"
    }
    early = await app_client.post(
        f"/api/hr/lifecycle/cases/{target['case']}/deactivate-now", headers=headers
    )
    assert early.status_code == 409
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, target["case"])
        case.last_working_day = business_today() - timedelta(days=1)
        case.deactivate_on = business_today()
        await db.commit()
    done = await app_client.post(
        f"/api/hr/lifecycle/cases/{target['case']}/deactivate-now", headers=headers
    )
    assert done.status_code == 200, done.text
    assert done.json()["account_close_result"] == "deactivated"
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, target["leaver"])).is_active is False
        assert (await db.get(User, worlds[1]["leaver"])).is_active is True
    again = await app_client.post(
        f"/api/hr/lifecycle/cases/{target['case']}/deactivate-now", headers=headers
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_cancelled_offboarding_never_closes_the_account(modules_on) -> None:
    world = await _leaving()
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, world["case"])
        hr = await db.get(User, world["hr"])
        await service.cancel_case(db, case, actor=hr)
        await db.commit()
    await _run(_at(world["last_day"], 18, 30))
    await _run(_at(world["deactivate_on"], 8, 0))
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, world["leaver"])).is_active is True
        case = await db.get(LifecycleCase, world["case"])
        assert case.handover_executed_at is None
        assert case.account_closed_at is None


@pytest.mark.asyncio
async def test_switched_off_module_skips_the_loop() -> None:
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: False for key in HR_MODULE_KEYS})
    try:
        result = await _run(_at(business_today(), 18, 30))
        assert result == {"skipped": "module_off"}
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.mark.asyncio
async def test_monday_reminder_goes_to_the_assignee_once_a_week(modules_on) -> None:
    world = await _leaving()
    # Pierwszy poniedziałek, w którym zadania z terminem w ostatnim dniu są
    # już zaległe (i mieszczą się w 30 dniach).
    monday = world["last_day"] + timedelta(days=1)
    while monday.weekday() != 0:
        monday += timedelta(days=1)
    async with AsyncSessionLocal() as db:
        overdue = list(
            await db.scalars(
                select(LifecycleTask).where(
                    LifecycleTask.case_id == world["case"],
                    LifecycleTask.assignee_kind == "manager",
                )
            )
        )
        assert overdue and all(task.due_date < monday for task in overdue)

    tuesday = monday + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        assert await run_reminders(db, _at(tuesday, 10)) == {"reminders": "not_monday"}

    # Dzwonek ze startu sprawy padł „dziś” (zegar bazy); przypomnienie w realnym
    # świecie wychodzi w innym dniu — dzienny dedup dzwonków by je połknął.
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM notifications WHERE notification_type = 'hr_lifecycle_task' "
                "AND related_entity_id = :case"
            ),
            {"case": world["case"]},
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        first = await run_reminders(db, _at(monday, 10))
    assert first["reminders_sent"] >= 1
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == world["boss"],
                Notification.notification_type == NotificationType.hr_lifecycle_task,
                Notification.related_entity_type == "lifecycle_case",
                Notification.related_entity_id == world["case"],
            )
        )
        assert bell is not None and bell.title.startswith("Zaległe zadania")
    async with AsyncSessionLocal() as db:
        second = await run_reminders(db, _at(monday, 10, 15))
    assert second == {"reminders": "claimed"}


@pytest.mark.asyncio
async def test_task_pools_skip_inactive_accounts() -> None:
    """Compass brał „wszystkich adminów” bez wykluczenia osób, które odeszły —
    tu pula wykonawców (IT, Kadry, recepcja) to wyłącznie aktywne konta."""

    from app.services.hr.lifecycle_access import pool_member_ids

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        gone_admin = User(
            email=f"pool-gone-{tag}@example.com",
            name=f"Admin Były {tag}",
            role=UserRole.admin,
            roles=["admin"],
            is_active=False,
        )
        live_admin = User(
            email=f"pool-live-{tag}@example.com",
            name=f"Admin Obecny {tag}",
            role=UserRole.admin,
            roles=["admin"],
            is_active=True,
        )
        db.add_all([gone_admin, live_admin])
        await db.commit()
        it_pool = await pool_member_ids(db, "it")
    assert live_admin.id in it_pool
    assert gone_admin.id not in it_pool
