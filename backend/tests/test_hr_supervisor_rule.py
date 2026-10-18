"""Jedna reguła przełożonego (decyzja koordynatora 17.10.2026, ``recipients``).

Do 17.10.2026 urlop i czas liczyły „kto decyduje” po swojemu: wniosek
urlopowy szedł do przełożonego, który odszedł (urlop nie sprawdzał
``exited``), timesheet tej samej osoby — do Kadr z adminami (czas nie znał
heada pionu), a head pionu był tylko w zgłoszeniach z B2B. Teraz jedna
funkcja ``supervisor_of``: przełożony z kartoteki, gdy ma aktywne konto i nie
odszedł → head pionu → Kadry (bez adminów, chyba że Kadr nie ma). Kto dostaje
sprawę do decyzji, ten może o niej zdecydować.

Dane fikcyjne (repo jest publiczne); daty w 2094, z dala od „dziś”.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import recipients
from app.services.hr_foundation_schema import (
    HR_DIVISIONS_SETTING,
    HR_MODULE_KEYS,
    HR_MODULES_SETTING,
)

LEAVE = "/api/hr/leave"
TIME = "/api/hr/time"
Y, M = 2094, 3
MON = date(Y, M, 8)
FRI = date(Y, M, 12)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"supervisor-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **profile_values))
        await db.flush()
    return user


async def _grant(db, user: User, action: str) -> None:
    db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    await db.flush()


async def _set(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        heads = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_DIVISIONS_SETTING)
        )
    await _set(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    yield
    await _set(HR_DIVISIONS_SETTING, heads)
    await _set(HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS})


async def _bells(user_id: int, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                )
            )
        )


async def _submit_timesheet(app_client, worker: User) -> int:
    h = _headers(worker)
    entry = await app_client.post(
        f"{TIME}/me/{Y}/{M}/entries",
        json={"work_date": f"{Y}-03-15", "hours": 8, "description": "Praca"},
        headers=h,
    )
    assert entry.status_code == 201, entry.text
    sent = await app_client.post(f"{TIME}/me/{Y}/{M}/submit", headers=h)
    assert sent.status_code == 200, sent.text
    return sent.json()["id"]


@pytest.mark.asyncio
async def test_leave_and_timesheet_go_to_the_same_supervisor_who_can_decide(
    app_client, modules_on
) -> None:
    """Przełożony odszedł: wniosek urlopowy i timesheet idą do heada pionu."""

    async with AsyncSessionLocal() as db:
        head = await _user(db, "head_of_recruitment", profile=True)
        gone = await _user(db, "recruiter", profile=True, employment_status="exited")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        worker = await _user(
            db,
            "employee",
            profile=True,
            employment_type="uop",
            manager_user_id=gone.id,
            division="back_office",
        )
        await db.commit()
    await _set(HR_DIVISIONS_SETTING, {"front_office": None, "back_office": head.id})

    preview = await app_client.post(
        f"{LEAVE}/preview",
        json={
            "leave_type": "vacation",
            "start_date": MON.isoformat(),
            "end_date": FRI.isoformat(),
        },
        headers=_headers(worker),
    )
    assert preview.json()["approver"] == head.name
    created = await app_client.post(
        f"{LEAVE}/requests",
        json={
            "leave_type": "vacation",
            "start_date": MON.isoformat(),
            "end_date": FRI.isoformat(),
        },
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"
    timesheet_id = await _submit_timesheet(app_client, worker)

    for ntype in (
        NotificationType.hr_leave_requested,
        NotificationType.hr_timesheet_submitted,
    ):
        assert len(await _bells(head.id, ntype)) == 1, ntype
        assert await _bells(gone.id, ntype) == [], ntype
        assert await _bells(hr.id, ntype) == [], ntype

    # Kto dostał sprawę do decyzji, ten o niej decyduje.
    pending = await app_client.get(f"{LEAVE}/approvals/pending", headers=_headers(head))
    assert pending.status_code == 200, pending.text
    assert created.json()["id"] in {item["id"] for item in pending.json()["items"]}
    approved = await app_client.post(
        f"{LEAVE}/approvals/{created.json()['id']}/approve",
        json={},
        headers=_headers(head),
    )
    assert approved.status_code == 200, approved.text
    team = await app_client.get(f"{TIME}/team/{Y}/{M}", headers=_headers(head))
    assert team.status_code == 200, team.text
    assert worker.id in {item["user_id"] for item in team.json()["items"]}
    accepted = await app_client.post(
        f"{TIME}/timesheets/{timesheet_id}/approve", headers=_headers(head)
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_without_manager_and_head_kadry_decide_not_every_admin(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        worker = await _user(
            db, "employee", profile=True, employment_type="uop", division="front_office"
        )
        await db.commit()
    await _set(HR_DIVISIONS_SETTING, {"front_office": None, "back_office": None})

    await _submit_timesheet(app_client, worker)
    assert len(await _bells(hr.id, NotificationType.hr_timesheet_submitted)) == 1
    assert await _bells(admin.id, NotificationType.hr_timesheet_submitted) == []


@pytest.mark.asyncio
async def test_supervisor_chain_and_division_charges_agree(modules_on) -> None:
    """``supervisor_of`` (jedna osoba) i ``division_charges`` (zakres heada)
    liczą „brak żywego przełożonego” tak samo."""

    async with AsyncSessionLocal() as db:
        head = await _user(db, "head_of_recruitment", profile=True)
        boss = await _user(db, "recruiter", profile=True)
        off_boss = await _user(db, "recruiter", profile=True)
        off_boss.is_active = False
        gone_boss = await _user(
            db, "recruiter", profile=True, employment_status="exited"
        )
        no_profile_boss = await _user(db, "recruiter")
        people = {
            "alone": await _user(db, "employee", profile=True, division="back_office"),
            "managed": await _user(
                db,
                "employee",
                profile=True,
                division="back_office",
                manager_user_id=boss.id,
            ),
            "inactive": await _user(
                db,
                "employee",
                profile=True,
                division="back_office",
                manager_user_id=off_boss.id,
            ),
            "exited_boss": await _user(
                db,
                "employee",
                profile=True,
                division="back_office",
                manager_user_id=gone_boss.id,
            ),
            "boss_without_profile": await _user(
                db,
                "employee",
                profile=True,
                division="back_office",
                manager_user_id=no_profile_boss.id,
            ),
            "other_division": await _user(
                db, "employee", profile=True, division="front_office"
            ),
        }
        await db.commit()
    await _set(HR_DIVISIONS_SETTING, {"front_office": None, "back_office": head.id})

    async with AsyncSessionLocal() as db:
        charges = await recipients.division_charges(db, head.id)
        today = business_today()
        chain = {}
        for key, person in people.items():
            profile = await db.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == person.id)
            )
            chain[key] = await recipients.supervisor_of(db, profile, today)

    assert chain["managed"].user_ids == (boss.id,)
    assert chain["managed"].kind == "manager"
    assert chain["boss_without_profile"].user_ids == (no_profile_boss.id,)
    for key in ("alone", "inactive", "exited_boss"):
        assert chain[key].user_ids == (head.id,), key
        assert chain[key].kind == "division_head"
        assert chain[key].label == head.name
    assert chain["other_division"].kind == "people_admin"
    assert chain["other_division"].label == "Kadry"

    mine = {people[key].id for key in ("alone", "inactive", "exited_boss")}
    assert mine <= charges
    assert (
        not {
            people[key].id
            for key in ("managed", "boss_without_profile", "other_division")
        }
        & charges
    )
