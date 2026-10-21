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
from app.models.oauth_client import OAuthClient
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
async def test_account_back_on_restores_the_departure_in_progress() -> None:
    """Decyzja Artura 21.10.2026: pomyłkowe wyłączenie konta nie kasuje odejścia.

    Ponowne włączenie wraca do statusu i ostatniego dnia sprzed wyłączenia,
    o ile od wyłączenia nikt nie zmienił kartoteki ręcznie."""
    later = business_today() + timedelta(days=20)
    async with AsyncSessionLocal() as db:
        leaving = await make_user(
            db, "recruiter", employment_status="offboarding", last_working_day=later
        )
        onboarding = await make_user(db, "recruiter", employment_status="onboarding")
        edited = await make_user(
            db, "recruiter", employment_status="offboarding", last_working_day=later
        )
        await db.commit()

    for user in (leaving, onboarding, edited):
        await _switch(user.id, False)
    # Kadry po wyłączeniu poprawiły ostatni dzień ręcznie — to już ich decyzja.
    fixed_day = business_today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        row = await people.profile_of(db, edited.id)
        row.last_working_day = fixed_day
        await db.commit()
    for user in (leaving, onboarding, edited):
        await _switch(user.id, True)

    back = await _profile(leaving.id)
    assert back.employment_status == "offboarding"
    assert back.last_working_day == later and back.exited_at is None
    assert (await _profile(onboarding.id)).employment_status == "onboarding"
    # Ręczna zmiana po wyłączeniu: powrót jak dotąd, „aktywny” bez ostatniego dnia.
    plain = await _profile(edited.id)
    assert plain.employment_status == "active" and plain.last_working_day is None

    async with AsyncSessionLocal() as db:
        trail = (
            await db.scalars(
                select(HrAuditEvent)
                .where(
                    HrAuditEvent.subject_user_id == leaving.id,
                    HrAuditEvent.action == account_profiles.FOLLOW_ACTION,
                )
                .order_by(HrAuditEvent.id)
            )
        ).all()
    assert [e.details["to"] for e in trail] == ["exited", "offboarding"]
    assert trail[1].details["last_working_day"] == later.isoformat()


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


async def _integration_account(db) -> User:
    """Konto, w którego imieniu działa klient OAuth (scrapery) — rola rekrutacji."""

    user = await make_user(db, "talent_community_manager", profile=False)
    marker = uuid.uuid4().hex[:10]
    db.add(
        OAuthClient(
            name=f"Integracje {marker}",
            client_id=f"integracje-{marker}",
            secret_hash="!test-no-secret!",
            scopes=["candidate:write"],
            enabled=True,
            acting_user_id=user.id,
        )
    )
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_integration_account_is_not_staff() -> None:
    # 20.10.2026: konto scraperów (acting user klienta OAuth, rola TCM) dostało
    # kartotekę i stało w kolejce timesheetów jako „Nie założony”.
    async with AsyncSessionLocal() as db:
        robot = await _integration_account(db)
        assert not await account_profiles.ensure_profile(
            db, robot, actor_id=None, source="test"
        )
        assert robot.id not in {
            item["user_id"] for item in await people.users_without_profile(db)
        }
        assert robot.id not in {
            item.user_id for item in await account_profiles.mismatches(db)
        }
        await db.rollback()


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

    def staff(user: User, integration_ids: frozenset[int] = frozenset()) -> bool:
        return people.is_staff_account(user, integration_ids=integration_ids)

    assert staff(account(UserRole.recruiter))
    assert staff(account(UserRole.talent_community_manager))
    assert not staff(account(UserRole.automation))
    assert not staff(account(UserRole.user))
    assert not staff(account(UserRole.recruiter, verified=False))
    robot = account(UserRole.talent_community_manager)
    robot.id = 244
    assert not staff(robot, frozenset({244}))


@pytest.mark.asyncio
async def test_integration_profile_cleanup_removes_only_bare_profiles() -> None:
    from app.models.app_setting import AppSetting
    from app.services.hr import integration_profile_cleanup as cleanup

    async with AsyncSessionLocal() as db:
        bare = await _integration_account(db)
        db.add(EmployeeProfile(user_id=bare.id, created_from_account=True))
        boss = await _integration_account(db)
        db.add(EmployeeProfile(user_id=boss.id, created_from_account=True))
        await make_user(db, "recruiter", manager_user_id=boss.id)
        manual = await _integration_account(db)
        db.add(EmployeeProfile(user_id=manual.id, created_from_account=False))
        staff = await make_user(db, "recruiter", created_from_account=True)
        await db.commit()
    ids = {bare.id, boss.id, manual.id, staff.id}
    marker = f"pytest_integration_profiles_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        summary = await cleanup.run_integration_profile_cleanup(
            db, marker=marker, only_user_ids=ids
        )
        await db.commit()
    bare_id = summary["deleted_profiles"][0]
    assert len(summary["deleted_profiles"]) == 1
    assert sorted(summary["skipped"].values()) == [
        "has_hr_data",
        "not_created_from_account",
    ]
    assert await _profile(bare.id) is None
    for kept in (boss, manual, staff):
        assert await _profile(kept.id) is not None

    async with AsyncSessionLocal() as db:
        trail = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.subject_user_id == bare.id,
                HrAuditEvent.action == cleanup.REMOVED_ACTION,
            )
        )
        assert trail is not None and trail.entity_id == str(bare_id)
        assert (await db.get(AppSetting, marker)).value["deleted_profiles"] == [bare_id]
        # Drugi start nic nie robi.
        assert (
            await cleanup.run_integration_profile_cleanup(
                db, marker=marker, only_user_ids=ids
            )
            is None
        )
        await db.delete(await db.get(AppSetting, marker))
        await db.commit()


def test_integration_profile_cleanup_runs_at_startup() -> None:
    from pathlib import Path

    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    phase = entrypoint.index('startup_phase "cleanup-integration-profiles"')
    assert entrypoint.index("run_integration_profile_cleanup(db)", phase) < (
        entrypoint.index("startup_phase", phase + 1)
    )
