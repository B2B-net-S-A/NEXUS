"""„Ludzie w NEXUSIE” (krok E0): katalog, kartoteka, Kadry, przełączniki modułów.

Zakres widoczności: wizytówka dla każdej osoby z kartoteką, pełna kartoteka dla
samej osoby, jej przełożonego i Kadr; stawki nigdy tutaj. Wyłączony moduł
odpowiada 404 wszystkim poza adminem. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _results(response) -> str:
    """Wyniki wyszukiwania bez echa zapytania (`query`)."""

    body = response.json()
    body.pop("query", None)
    return json.dumps(body, ensure_ascii=False)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"hr-{marker}@example.com",
        name=f"Osoba {marker}",
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
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def modules_off():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: False for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.mark.asyncio
async def test_switched_off_module_hides_directory_except_for_admin(
    app_client, modules_off
) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        admin = await _user(db, "admin")
        await db.commit()

    denied = await app_client.get("/api/hr/people", headers=_headers(worker))
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    allowed = await app_client.get("/api/hr/people", headers=_headers(admin))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_directory_shows_cards_and_full_profile_only_in_scope(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True, employment_type="uop")
        report = await _user(
            db,
            "employee",
            profile=True,
            manager_user_id=boss.id,
            employment_type="zlecenie",
            job_title="Administracja",
        )
        colleague = await _user(db, "recruiter", profile=True, employment_type="b2b")
        await db.commit()

    as_colleague = await app_client.get(
        f"/api/hr/people/{report.id}", headers=_headers(colleague)
    )
    assert as_colleague.status_code == 200
    body = as_colleague.json()
    assert body["scope"] == "card"
    assert body["job_title"] == "Administracja"
    assert "employment_type" not in body
    assert "entitlements" not in body

    as_boss = await app_client.get(
        f"/api/hr/people/{report.id}", headers=_headers(boss)
    )
    assert as_boss.json()["scope"] == "full"
    assert as_boss.json()["employment_type"] == "zlecenie"

    own = await app_client.get(f"/api/hr/people/{report.id}", headers=_headers(report))
    assert own.json()["scope"] == "full"

    listing = await app_client.get("/api/hr/people", headers=_headers(boss))
    by_id = {item["user_id"]: item for item in listing.json()["items"]}
    assert by_id[report.id]["scope"] == "full"
    assert by_id[colleague.id]["scope"] == "card"
    assert "employment_type" not in by_id[colleague.id]


@pytest.mark.asyncio
async def test_account_without_profile_or_permission_is_refused(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        outsider = await _user(db, "recruiter")
        await db.commit()

    response = await app_client.get("/api/hr/people", headers=_headers(outsider))
    assert response.status_code == 403
    assert "kartoteki w NEXUSIE" in response.json()["detail"]


@pytest.mark.asyncio
async def test_people_admin_grant_opens_profile_creation(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        plain = await _user(db, "recruiter")
        newcomer = await _user(db, "employee")
        await db.commit()

    payload = {
        "user_id": newcomer.id,
        "employment_type": "uop",
        "default_location": "remote",
        "work_start_date": "2026-11-02",
    }
    refused = await app_client.post(
        "/api/hr/admin/profiles", json=payload, headers=_headers(plain)
    )
    assert refused.status_code == 403

    created = await app_client.post(
        "/api/hr/admin/profiles", json=payload, headers=_headers(hr)
    )
    assert created.status_code == 201, created.text
    # Kadry bez Płac zapisują formę, ale jej nie widzą (decyzja Artura 19.10.2026).
    assert created.json()["employment_type"] is None
    assert created.json()["employment_type_pending"] is False
    assert created.json()["default_location"] == "remote"

    again = await app_client.post(
        "/api/hr/admin/profiles", json=payload, headers=_headers(hr)
    )
    assert again.status_code == 422
    assert again.json()["detail"] == "Ta osoba ma już kartotekę."

    async with AsyncSessionLocal() as db:
        from app.models.hr_ops import HrAuditEvent

        events = (
            await db.scalars(
                select(HrAuditEvent).where(HrAuditEvent.subject_user_id == newcomer.id)
            )
        ).all()
    assert [event.action for event in events] == ["profile_created"]
    assert events[0].actor_user_id == hr.id


@pytest.mark.asyncio
async def test_manager_loop_and_dates_are_validated(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        first = await _user(db, "employee", profile=True)
        second = await _user(db, "employee", profile=True, manager_user_id=first.id)
        await db.commit()

    loop = await app_client.patch(
        f"/api/hr/admin/profiles/{first.id}",
        json={"manager_user_id": second.id},
        headers=_headers(admin),
    )
    assert loop.status_code == 422
    assert "pętlę przełożonych" in loop.json()["detail"]

    self_manager = await app_client.patch(
        f"/api/hr/admin/profiles/{first.id}",
        json={"manager_user_id": first.id},
        headers=_headers(admin),
    )
    assert self_manager.status_code == 422

    dates = await app_client.patch(
        f"/api/hr/admin/profiles/{second.id}",
        json={"work_start_date": "2026-11-02", "last_working_day": "2026-10-30"},
        headers=_headers(admin),
    )
    assert dates.status_code == 422

    cleared = await app_client.patch(
        f"/api/hr/admin/profiles/{second.id}",
        json={"manager_user_id": None},
        headers=_headers(admin),
    )
    assert cleared.status_code == 200
    assert cleared.json()["manager_user_id"] is None


@pytest.mark.asyncio
async def test_entitlements_accept_half_days_only(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        worker = await _user(db, "employee", profile=True)
        await db.commit()

    ok = await app_client.put(
        f"/api/hr/admin/profiles/{worker.id}/entitlements/2026",
        json={"entitlement_days": "26", "carried_over_days": "2.5"},
        headers=_headers(admin),
    )
    assert ok.status_code == 200, ok.text
    bad = await app_client.put(
        f"/api/hr/admin/profiles/{worker.id}/entitlements/2026",
        json={"entitlement_days": "26", "carried_over_days": "0.3"},
        headers=_headers(admin),
    )
    assert bad.status_code == 422

    mine = await app_client.get("/api/hr/me", headers=_headers(worker))
    assert mine.json()["has_profile"] is True
    assert mine.json()["entitlements"][0]["year"] == 2026


@pytest.mark.asyncio
async def test_company_days_off_reject_weekends_and_duplicates(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        await db.commit()

    # Wybieramy daleki rok, żeby nie zderzyć się z innymi testami.
    weekday = date(2093, 6, 1)
    while weekday.weekday() >= 5:
        weekday = weekday.replace(day=weekday.day + 1)
    saturday = date(2093, 6, 6)
    assert saturday.weekday() == 5

    weekend = await app_client.post(
        "/api/hr/admin/days-off",
        json={"day": saturday.isoformat(), "name": "Dzień firmy"},
        headers=_headers(admin),
    )
    assert weekend.status_code == 422
    added = await app_client.post(
        "/api/hr/admin/days-off",
        json={"day": weekday.isoformat(), "name": "Dzień firmy"},
        headers=_headers(admin),
    )
    assert added.status_code == 201
    duplicate = await app_client.post(
        "/api/hr/admin/days-off",
        json={"day": weekday.isoformat(), "name": "Drugi"},
        headers=_headers(admin),
    )
    assert duplicate.status_code == 422
    removed = await app_client.delete(
        f"/api/hr/admin/days-off/{added.json()['id']}", headers=_headers(admin)
    )
    assert removed.status_code == 204


@pytest.mark.asyncio
async def test_config_reports_modules_and_own_rights(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True)
        await _user(db, "employee", profile=True, manager_user_id=boss.id)
        finance = await _user(db, "finance")
        await db.commit()

    boss_config = (
        await app_client.get("/api/hr/config", headers=_headers(boss))
    ).json()
    assert boss_config["modules"]["leave"] is True
    assert boss_config["me"]["has_profile"] is True
    assert boss_config["me"]["is_manager"] is True
    assert boss_config["me"]["payroll"] is False

    finance_config = (
        await app_client.get("/api/hr/config", headers=_headers(finance))
    ).json()
    # D2: Płace domyślnie u Finansów.
    assert finance_config["me"]["payroll"] is True
    assert finance_config["me"]["has_profile"] is False


@pytest.mark.asyncio
async def test_modules_are_switched_only_by_admin(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter")
        await _grant(db, hr, "people_admin")
        admin = await _user(db, "admin")
        await db.commit()

    refused = await app_client.put(
        "/api/hr/admin/modules",
        json={"modules": {"leave": False}},
        headers=_headers(hr),
    )
    assert refused.status_code == 403
    unknown = await app_client.put(
        "/api/hr/admin/modules",
        json={"modules": {"nope": True}},
        headers=_headers(admin),
    )
    assert unknown.status_code == 422
    switched = await app_client.put(
        "/api/hr/admin/modules",
        json={"modules": {"leave": False}},
        headers=_headers(admin),
    )
    assert switched.status_code == 200
    assert switched.json()["modules"]["leave"] is False
    assert switched.json()["modules"]["people"] is True


@pytest.mark.asyncio
async def test_employee_role_sees_no_candidates(app_client, modules_on) -> None:
    marker = f"Teodor{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        worker = await _user(db, "employee", profile=True)
        recruiter = await _user(db, "recruiter")
        db.add(Candidate(name=marker, lastname="Testowy"))
        await db.commit()

    response = await app_client.get("/api/candidates", headers=_headers(worker))
    assert response.status_code == 403
    own = await app_client.get("/api/hr/people", headers=_headers(worker))
    assert own.status_code == 200
    # Wyszukiwarka w pasku przechodzi bramkę każdego konta, ale kategorie
    # filtruje sekcjami — „Pracownik” nie ma żadnej, więc nie dostaje nic.
    for path in ("/api/search/global", "/api/search/"):
        seen = await app_client.get(
            path, params={"q": marker}, headers=_headers(recruiter)
        )
        assert marker in _results(seen), path  # kontrola: rekruter tę osobę znajduje
        found = await app_client.get(
            path, params={"q": marker}, headers=_headers(worker)
        )
        assert found.status_code == 200
        assert marker not in _results(found), path


@pytest.mark.asyncio
async def test_directory_today_column_without_leave_type(
    app_client, modules_on
) -> None:
    """Kolumna „Dziś” (makieta 19.10.2026): nieobecność bez rodzaju (D6),
    praca zdalna i delegacja z `attendance_days`, bez notatek."""

    from app.core.scheduling import business_today
    from app.models.hr_leave import LeaveRequest
    from app.models.hr_time import AttendanceDay

    today = business_today()
    async with AsyncSessionLocal() as db:
        colleague = await _user(db, "recruiter", profile=True)
        sick = await _user(db, "employee", profile=True, employment_type="uop")
        remote = await _user(db, "employee", profile=True)
        trip = await _user(db, "employee", profile=True)
        present = await _user(db, "employee", profile=True)
        db.add(
            LeaveRequest(
                user_id=sick.id,
                leave_type="sick_leave",
                status="approved",
                start_date=today,
                end_date=today,
                note="sekretny powód",
            )
        )
        db.add(
            AttendanceDay(
                user_id=remote.id,
                day=today,
                status="active",
                location="remote",
                note="z domu, hydraulik",
            )
        )
        db.add(AttendanceDay(user_id=trip.id, day=today, status="business_trip"))
        await db.commit()

    listing = await app_client.get("/api/hr/people", headers=_headers(colleague))
    assert listing.status_code == 200
    by_id = {item["user_id"]: item for item in listing.json()["items"]}
    assert by_id[sick.id]["scope"] == "card"
    assert by_id[sick.id]["today"]["absent_until"] == today.isoformat()
    assert by_id[sick.id]["today"]["presence"] is None
    assert by_id[remote.id]["today"] == {
        "absent_until": None,
        "half_day": None,
        "substitute_name": None,
        "presence": "remote",
    }
    assert by_id[trip.id]["today"]["presence"] == "business_trip"
    assert by_id[present.id]["today"] is None
    text = listing.text
    assert "sick_leave" not in text
    assert "leave_type" not in text
    assert "sekretny" not in text
    assert "hydraulik" not in text


@pytest.mark.asyncio
async def test_directory_today_column_follows_open_modules(app_client) -> None:
    """Zamknięty moduł urlopów i czasu = katalog bez nieobecności i bez Z/D."""

    from app.core.scheduling import business_today
    from app.models.hr_leave import LeaveRequest
    from app.models.hr_time import AttendanceDay

    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules(
        {key: key == "people" for key in HR_MODULE_KEYS},
    )
    try:
        today = business_today()
        async with AsyncSessionLocal() as db:
            colleague = await _user(db, "recruiter", profile=True)
            absent = await _user(db, "employee", profile=True)
            remote = await _user(db, "employee", profile=True)
            db.add(
                LeaveRequest(
                    user_id=absent.id,
                    leave_type="vacation",
                    status="approved",
                    start_date=today,
                    end_date=today,
                )
            )
            db.add(
                AttendanceDay(
                    user_id=remote.id, day=today, status="active", location="remote"
                )
            )
            await db.commit()

        listing = await app_client.get("/api/hr/people", headers=_headers(colleague))
        assert listing.status_code == 200
        by_id = {item["user_id"]: item for item in listing.json()["items"]}
        assert by_id[absent.id]["today"] is None
        assert by_id[remote.id]["today"] is None
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.mark.asyncio
async def test_profile_leave_ring_only_in_full_scope_without_type_counters(
    app_client, modules_on
) -> None:
    """Pierścień dni przerwy w kartotece (makieta 19.10.2026): saldo z puli
    tylko w pełnym zakresie, bez liczników rodzajów; zlecenie bez puli."""

    from decimal import Decimal

    from app.core.scheduling import business_today
    from app.models.hr_profile import LeaveEntitlement

    year = business_today().year
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter", profile=True)
        report = await _user(
            db, "employee", profile=True, manager_user_id=boss.id, employment_type="uop"
        )
        contractor = await _user(
            db,
            "employee",
            profile=True,
            manager_user_id=boss.id,
            employment_type="zlecenie",
        )
        colleague = await _user(db, "recruiter", profile=True)
        db.add(
            LeaveEntitlement(
                user_id=report.id, year=year, entitlement_days=Decimal("26")
            )
        )
        await db.commit()

    as_boss = await app_client.get(
        f"/api/hr/people/{report.id}", headers=_headers(boss)
    )
    assert as_boss.status_code == 200
    ring = as_boss.json()["leave_balance"]
    assert ring["year"] == year
    assert ring["has_paid_pool"] is True
    assert float(ring["remaining_days"]) == 26.0
    assert set(ring) == {
        "year",
        "has_paid_pool",
        "entitlement_days",
        "carried_over_days",
        "used_days",
        "planned_days",
        "remaining_days",
    }

    no_pool = await app_client.get(
        f"/api/hr/people/{contractor.id}", headers=_headers(boss)
    )
    assert no_pool.json()["leave_balance"] is None

    as_colleague = await app_client.get(
        f"/api/hr/people/{report.id}", headers=_headers(colleague)
    )
    assert as_colleague.json()["scope"] == "card"
    assert "leave_balance" not in as_colleague.json()


@pytest.mark.asyncio
async def test_board_member_with_a_leftover_profile_is_not_staff(
    app_client, modules_on
) -> None:
    """Rada nadzorcza (0490) zakładana jest pierwszym logowaniem jako
    „Pracownik” — kartoteka z tego logowania zostaje po zmianie roli. Nie
    otwiera jej katalogu ludzi, samoobsługi ani wniosków o zgodę
    (audyt 22.10.2026, F76)."""

    from app.services.hr import people

    async with AsyncSessionLocal() as db:
        member = await _user(db, "board", profile=True)
        worker = await _user(db, "employee", profile=True)
        await db.commit()
        assert await people.has_live_profile(db, worker.id)
        assert not await people.has_live_profile(db, member.id)

    directory = await app_client.get("/api/hr/people", headers=_headers(member))
    assert directory.status_code == 403
    assert (
        await app_client.get("/api/hr/people", headers=_headers(worker))
    ).status_code == 200
