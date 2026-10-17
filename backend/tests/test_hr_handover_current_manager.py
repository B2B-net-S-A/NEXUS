"""Przekazanie podwładnych idzie do OBECNEGO przełożonego odchodzącego (17.10.2026).

Do poprawki domyślny przejmujący był przełożonym zapisanym w sprawie odejścia
w chwili jej założenia: Kadry przepinały odchodzącą w „Strukturze” (albo
w kartotece) pod nową szefową, a jej podwładni i tak trafiali po 18:00 do
byłego przełożonego. Teraz zmiana przełożonego w kartotece przechodzi na żywą
sprawę odejścia, gdy sprawa szła za kartoteką (jej przełożony = poprzedni
z kartoteki); przejmujący domyślny idzie za nim. Przejmujący wskazany przez
Kadry w sprawie i przełożony wskazany w sprawie ręcznie zostają.

Dane fikcyjne (repo jest publiczne).
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
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import lifecycle_service as service
from app.services.hr import people, structure
from app.services.hr.lifecycle_jobs import run_once
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


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_lifecycle%'")
        )
        # Przebieg pętli bierze wszystkie sprawy z dniem przekazania — cudze
        # z innych testów nie mogą się tu wykonać.
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


def _headers(user_id: int) -> dict[str, str]:
    token = create_access_token(subject=user_id, role="recruiter")
    return {"Authorization": f"Bearer {token}"}


async def _people(*labels: str) -> dict[str, int]:
    """Konta z kartoteką (poza „kadry” — Kadry z uprawnieniem, bez kartoteki)."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        users: dict[str, User] = {}
        for label in labels:
            role = "employee" if label.startswith("first") else "recruiter"
            user = User(
                email=f"handover-{label}-{tag}@example.com",
                name=f"Osoba {label} {tag}",
                role=UserRole(role),
                roles=[role],
                is_active=True,
                profile_completed=True,
            )
            db.add(user)
            users[label] = user
        await db.flush()
        for label, user in users.items():
            if label == "kadry":
                db.add(
                    UserActionOverride(
                        user_id=user.id, action="people_admin", access="manage"
                    )
                )
            else:
                db.add(EmployeeProfile(user_id=user.id, employment_status="active"))
        await db.commit()
        return {label: user.id for label, user in users.items()}


def _last_day() -> date:
    day = business_today() + timedelta(days=9)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WARSAW)


async def _manager_of(user_id: int) -> Optional[int]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == user_id
            )
        )


async def _leader_case(
    ids: dict[str, int], *, case_manager: Optional[int] = None
) -> tuple[int, date]:
    """``leader`` pod ``boss``, ``first`` pod ``leader``; odejście ``leader``."""

    async with AsyncSessionLocal() as db:
        hr = await db.get(User, ids["kadry"])
        for user_id, manager in (
            (ids["leader"], ids["boss"]),
            (ids["first"], ids["leader"]),
        ):
            await people.update_profile(
                db, user_id=user_id, values={"manager_user_id": manager}, actor=hr
            )
        await db.commit()
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=ids["leader"],
            last_working_day=_last_day(),
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=case_manager,
            manager_given=case_manager is not None,
            template_id=None,
        )
        await service.start_case(db, case, actor=hr)
        await db.commit()
        return case.id, case.last_working_day


async def _reports_row(case_id: int) -> WorkHandover:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(WorkHandover).where(
                WorkHandover.case_id == case_id, WorkHandover.work_kind == "reports"
            )
        )


@pytest.mark.asyncio
async def test_reports_follow_manager_changed_in_structure(modules_on) -> None:
    ids = await _people("kadry", "boss", "boss2", "leader", "first")
    case_id, last_day = await _leader_case(ids)
    assert (await _reports_row(case_id)).receiver_user_id == ids["boss"]

    # Kadry przepinają odchodzącą w „Strukturze” pod nową szefową.
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, ids["kadry"])
        await structure.reassign(
            db, user_ids=[ids["leader"]], manager_user_id=ids["boss2"], actor=hr
        )
        await db.commit()
        tree = await structure.structure(db)
    leaving = next(r for r in tree["people"] if r["user_id"] == ids["leader"])[
        "leaving"
    ]
    # Podpowiedź w Strukturze i wiersz przekazania mówią to samo — nowa szefowa.
    assert leaving["reports_receiver_user_id"] == ids["boss2"]
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, case_id)
        assert case.manager_user_id == ids["boss2"]

    async with AsyncSessionLocal() as db:
        await run_once(db, now=_at(last_day, 18, 5))
    row = await _reports_row(case_id)
    assert (row.status, row.receiver_user_id) == ("done", ids["boss2"])
    assert await _manager_of(ids["first"]) == ids["boss2"]


@pytest.mark.asyncio
async def test_profile_edit_moves_default_receiver_but_not_kadry_choice(
    app_client, modules_on
) -> None:
    ids = await _people("kadry", "boss", "boss2", "leader", "first", "chosen")
    case_id, _ = await _leader_case(ids)
    # Kadry wskazują w sprawie przejmującego „Moich ludzi” ręcznie.
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, case_id)
        hr = await db.get(User, ids["kadry"])
        await service.set_receivers(
            db, case, actor=hr, receivers={"my_people": ids["chosen"]}
        )
        await db.commit()

    edited = await app_client.patch(
        f"/api/hr/admin/profiles/{ids['leader']}",
        json={"manager_user_id": ids["boss2"]},
        headers=_headers(ids["kadry"]),
    )
    assert edited.status_code == 200, edited.text
    async with AsyncSessionLocal() as db:
        rows = {
            row.work_kind: row.receiver_user_id
            for row in await db.scalars(
                select(WorkHandover).where(WorkHandover.case_id == case_id)
            )
        }
        case = await db.get(LifecycleCase, case_id)
    assert case.manager_user_id == ids["boss2"]
    assert rows["reports"] == ids["boss2"]
    assert rows["recruitments"] == ids["boss2"]
    assert rows["my_people"] == ids["chosen"], "wybór Kadr zostaje"


@pytest.mark.asyncio
async def test_manager_set_by_hand_in_case_stays_after_structure_change(
    modules_on,
) -> None:
    ids = await _people("kadry", "boss", "boss2", "leader", "first", "interim")
    # Przełożony w sprawie wskazany ręcznie (inny niż w kartotece).
    case_id, _ = await _leader_case(ids, case_manager=ids["interim"])
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, ids["kadry"])
        await structure.reassign(
            db, user_ids=[ids["leader"]], manager_user_id=ids["boss2"], actor=hr
        )
        await db.commit()
        case = await db.get(LifecycleCase, case_id)
    assert case.manager_user_id == ids["interim"]
    assert (await _reports_row(case_id)).receiver_user_id == ids["interim"]


@pytest.mark.asyncio
async def test_removing_manager_in_structure_keeps_case_manager(modules_on) -> None:
    """Bez nowego przełożonego (zdjęty w Strukturze) — dotychczasowa reguła:
    przejmuje przełożony zapisany w sprawie."""

    ids = await _people("kadry", "boss", "leader", "first")
    case_id, _ = await _leader_case(ids)
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, ids["kadry"])
        await structure.reassign(
            db, user_ids=[ids["leader"]], manager_user_id=None, actor=hr
        )
        await db.commit()
        case = await db.get(LifecycleCase, case_id)
    assert case.manager_user_id == ids["boss"]
    assert (await _reports_row(case_id)).receiver_user_id == ids["boss"]


async def _offboard(user_id: int, hr_id: int, last_day: date) -> int:
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, hr_id)
        case = await service.create_offboarding(
            db,
            actor=hr,
            user_id=user_id,
            last_working_day=last_day,
            exit_initiator="employee",
            exit_reason="career_growth",
            exit_note=None,
            manager_user_id=None,
            manager_given=False,
            template_id=None,
        )
        await service.start_case(db, case, actor=hr)
        await db.commit()
        return case.id


@pytest.mark.asyncio
async def test_leaving_report_case_follows_its_managers_handover(modules_on) -> None:
    """Przełożony odchodzi pierwszy, jego podwładna odchodzi później: po
    przekazaniu podwładnych jej sprawa i domyślny przejmujący idą za nowym
    przełożonym (a nie za szefem, którego konto zaraz zniknie)."""

    ids = await _people("kadry", "top", "boss", "leader", "first")
    async with AsyncSessionLocal() as db:
        hr = await db.get(User, ids["kadry"])
        for user_id, manager in (
            (ids["boss"], ids["top"]),
            (ids["leader"], ids["boss"]),
            (ids["first"], ids["leader"]),
        ):
            await people.update_profile(
                db, user_id=user_id, values={"manager_user_id": manager}, actor=hr
            )
        await db.commit()
    boss_day = _last_day()
    leader_day = boss_day + timedelta(days=2)
    while leader_day.weekday() >= 5:
        leader_day += timedelta(days=1)
    await _offboard(ids["boss"], ids["kadry"], boss_day)
    leader_case = await _offboard(ids["leader"], ids["kadry"], leader_day)
    # Szef odchodzi wcześniej — jako przejmujący nie jest proponowany.
    assert (await _reports_row(leader_case)).receiver_user_id is None

    async with AsyncSessionLocal() as db:
        await run_once(db, now=_at(boss_day, 18, 5))
    assert await _manager_of(ids["leader"]) == ids["top"]
    async with AsyncSessionLocal() as db:
        case = await db.get(LifecycleCase, leader_case)
    assert case.manager_user_id == ids["top"]
    assert (await _reports_row(leader_case)).receiver_user_id == ids["top"]
