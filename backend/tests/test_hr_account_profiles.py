"""Kartoteka idzie za kontem (decyzja Artura 19.10.2026: „Konto decyduje + lista rozjazdów”)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import account_profiles, people
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

MISMATCHES = "/api/hr/people/account-mismatches"


async def _profile(user_id: int) -> EmployeeProfile:
    async with AsyncSessionLocal() as db:
        return await people.profile_of(db, user_id)


async def _switch(user_id: int, active: bool) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_active = active
        await db.commit()


@pytest.mark.asyncio
async def test_switching_the_account_off_and_on_moves_the_profile() -> None:
    async with AsyncSessionLocal() as db:
        working = await make_user(db, "recruiter")
        later = business_today() + timedelta(days=20)
        leaving = await make_user(
            db, "recruiter", employment_status="offboarding", last_working_day=later
        )
        earlier = business_today() - timedelta(days=3)
        gone_earlier = await make_user(
            db, "recruiter", employment_status="offboarding", last_working_day=earlier
        )
        await db.commit()

    for user in (working, leaving, gone_earlier):
        await _switch(user.id, False)

    today = business_today()
    closed = await _profile(working.id)
    assert closed.employment_status == "exited"
    assert closed.last_working_day == today and closed.exited_at is not None
    # Odejście w toku z wyłączonym kontem → „zakończył” z dniem wyłączenia.
    assert (await _profile(leaving.id)).last_working_day == today
    # Wcześniejsza data z kartoteki zostaje.
    assert (await _profile(gone_earlier.id)).last_working_day == earlier

    async with AsyncSessionLocal() as db:
        trail = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id == working.id,
                    HrAuditEvent.action == account_profiles.FOLLOW_ACTION,
                )
            )
        ).all()
    assert [event.details["to"] for event in trail] == ["exited"]
    assert trail[0].details["source"] == "account"

    await _switch(working.id, True)
    back = await _profile(working.id)
    assert back.employment_status == "active"
    assert back.last_working_day is None and back.exited_at is None


@pytest.mark.asyncio
async def test_rolled_back_account_change_leaves_the_profile_alone() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db, "recruiter")
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.get(User, user.id)
        row.is_active = False
        await db.flush()
        await db.rollback()
    assert (await _profile(user.id)).employment_status == "active"


@pytest.mark.asyncio
async def test_ensure_profile_only_for_active_staff_accounts() -> None:
    async with AsyncSessionLocal() as db:
        staff = await make_user(db, "recruiter", profile=False)
        robot = await make_user(db, "automation", profile=False)
        unverified = await make_user(db, "recruiter", profile=False)
        unverified.email_verified = False
        await db.flush()
        assert await account_profiles.ensure_profile(
            db, staff, actor_id=None, source="test"
        )
        assert not await account_profiles.ensure_profile(
            db, robot, actor_id=None, source="test"
        )
        assert not await account_profiles.ensure_profile(
            db, unverified, actor_id=None, source="test"
        )
        # Drugi raz nic nie zakłada.
        assert not await account_profiles.ensure_profile(
            db, staff, actor_id=None, source="test"
        )
        await db.commit()
    created = await _profile(staff.id)
    assert created.employment_status == "active"
    assert created.employment_type_pending is True
    assert created.created_from_account is True
    assert created.manager_user_id is None


@pytest.mark.asyncio
async def test_admin_created_account_gets_a_profile(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "")
    created = await app_client.post(
        "/api/admin/users",
        headers=app_auth_headers,
        json={
            "email": f"kartoteka-{uuid.uuid4().hex[:8]}@example.com",
            "password": "Haslo-testowe-123!",
            "name": "Konto Z Kartoteką",
            "role": "recruiter",
        },
    )
    assert created.status_code == 201, created.text
    profile = await _profile(created.json()["id"])
    assert profile is not None and profile.employment_type_pending is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_mismatch_list_and_align_follow_the_account(app_client) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        report = await make_user(db, "recruiter", manager_user_id=boss.id)
        returned = await make_user(
            db,
            "recruiter",
            employment_status="exited",
            last_working_day=date(2026, 1, 31),
        )
        missing = await make_user(db, "recruiter", profile=False)
        robot = await make_user(db, "automation", profile=False)
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        finance = await make_user(db, "finance", profile=False)
        await grant(db, finance, "payroll")
        await db.commit()
    # Stan sprzed listenera: konto wyłączone surowym SQL-em, kartoteka „aktywny”.
    async with AsyncSessionLocal() as db:
        await db.execute(
            User.__table__.update().where(User.id == boss.id).values(is_active=False)
        )
        await db.commit()

    refused = await app_client.get(MISMATCHES, headers=headers(report))
    assert refused.status_code == 403
    listing = await app_client.get(MISMATCHES, headers=headers(finance))
    assert listing.status_code == 200, listing.text
    by_id = {item["user_id"]: item for item in listing.json()["items"]}
    assert by_id[boss.id]["kind"] == "exit"
    assert by_id[boss.id]["proposed_status"] == "exited"
    # Podwładnych przepina się w Strukturze (sprawy odejścia już nie będzie).
    assert by_id[boss.id]["reports"] == 1
    assert by_id[returned.id]["kind"] == "return"
    assert by_id[missing.id]["kind"] == "missing"
    assert robot.id not in by_id and report.id not in by_id

    aligned = await app_client.post(
        f"{MISMATCHES}/align",
        json={"user_ids": [boss.id, returned.id, missing.id]},
        headers=headers(hr),
    )
    assert aligned.status_code == 200, aligned.text
    assert aligned.json()["aligned"] == {"exit": 1, "return": 1, "missing": 1}
    assert (await _profile(boss.id)).employment_status == "exited"
    assert (await _profile(returned.id)).employment_status == "active"
    assert (await _profile(returned.id)).last_working_day is None
    assert (await _profile(missing.id)).created_from_account is True

    after = await app_client.get(MISMATCHES, headers=headers(hr))
    left = {item["user_id"] for item in after.json()["items"]}
    assert not left & {boss.id, returned.id, missing.id}
    assert after.json()["pending"]["employment_type"] >= 1
    assert after.json()["pending"]["manager"] >= 1


def test_staff_account_rule() -> None:
    def account(role: UserRole, verified: bool = True) -> User:
        return User(
            email="x@example.com",
            name="X",
            role=role,
            roles=[role.value],
            email_verified=verified,
        )

    assert people.is_staff_account(account(UserRole.recruiter))
    assert people.is_staff_account(account(UserRole.talent_community_manager))
    assert not people.is_staff_account(account(UserRole.automation))
    assert not people.is_staff_account(account(UserRole.user))
    assert not people.is_staff_account(account(UserRole.recruiter, verified=False))
