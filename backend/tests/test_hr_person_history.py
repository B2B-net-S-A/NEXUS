"""Kartoteka → „Nieobecności i godziny” (`GET /api/hr/people/{id}/history`).

Ten sam krąg co pełna kartoteka (osoba, przełożony, Kadry, Finanse, admin);
rodzaj nieobecności tylko dla kręgu D6, Finanse spoza niego widzą
„Nieobecność” i tylko zatwierdzone. Dane fikcyjne (repo jest publiczne).
Czyste funkcje (`person_history`) biegną bez bazy.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import person_history
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

# ── Czyste funkcje (bez bazy) ────────────────────────────────────────────────


def test_absence_state_buckets() -> None:
    today = date(2026, 10, 22)
    assert (
        person_history.absence_state("pending", date(2026, 11, 2), today) == "waiting"
    )
    assert (
        person_history.absence_state("rejected", date(2026, 9, 1), today) == "rejected"
    )
    assert (
        person_history.absence_state("approved", date(2026, 11, 2), today) == "planned"
    )
    # Dzień trwający dziś już się liczy (jak saldo).
    assert person_history.absence_state("approved", today, today) == "used"
    assert person_history.absence_state("approved", date(2026, 3, 2), today) == "used"
    assert person_history.absence_state("cancelled", date(2026, 3, 2), today) is None


def test_absence_label_hides_type_and_form() -> None:
    label = person_history.absence_label
    # Poza kręgiem D6 — zawsze neutralnie.
    assert (
        label("sick_leave", "uop", type_visible=False, form_visible=True)
        == "Nieobecność"
    )
    # Krąg D6 z formą: słowa formy (B2B nie ma „urlopu wypoczynkowego”).
    assert (
        label("vacation", "b2b", type_visible=True, form_visible=True)
        == "Przerwa w świadczeniu usług"
    )
    assert (
        label("vacation", "uop", type_visible=True, form_visible=True) != "Nieobecność"
    )
    # Kadry bez Płac: rodzaj z puli zdradzałby formę.
    assert (
        label("vacation", "b2b", type_visible=True, form_visible=False) == "Nieobecność"
    )
    assert (
        label("on_demand", "uop", type_visible=True, form_visible=False)
        == "Nieobecność"
    )
    assert label("sick_leave", "uop", type_visible=True, form_visible=False) not in (
        "Nieobecność",
        "",
    )


def test_recent_months_cross_the_year() -> None:
    assert person_history.recent_months(date(2026, 2, 10), 4) == [
        (2026, 2),
        (2026, 1),
        (2025, 12),
        (2025, 11),
    ]


def test_employed_in_uses_profile_dates() -> None:
    profile = EmployeeProfile(
        user_id=1,
        work_start_date=date(2026, 9, 15),
        last_working_day=date(2026, 11, 30),
    )
    assert not person_history.employed_in(profile, 2026, 8)
    assert person_history.employed_in(profile, 2026, 9)
    assert person_history.employed_in(profile, 2026, 11)
    assert not person_history.employed_in(profile, 2026, 12)
    assert person_history.employed_in(EmployeeProfile(user_id=1), 2020, 12)


# ── Trasa (baza w CI) ────────────────────────────────────────────────────────


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, profile: bool = False, **profile_values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"hist-{marker}@example.com",
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


async def _seed(db):
    """Przełożony, osoba na UoP z L4, urlopem, wnioskiem i raportem godzin."""

    from app.core.scheduling import business_today
    from app.models.hr_leave import LeaveRequest
    from app.models.hr_time import Timesheet, TimesheetEntry

    today = business_today()
    year = today.year
    boss = await _user(db, "recruiter", profile=True)
    person = await _user(
        db,
        "employee",
        profile=True,
        manager_user_id=boss.id,
        employment_type="uop",
        work_start_date=date(year - 1, 1, 1),
    )
    db.add_all(
        [
            LeaveRequest(
                user_id=person.id,
                leave_type="sick_leave",
                status="approved",
                # 1 stycznia — „wykorzystana” przy każdej dacie biegu testu.
                start_date=date(year, 1, 1),
                end_date=date(year, 1, 1),
                note="sekretny powód",
            ),
            LeaveRequest(
                user_id=person.id,
                leave_type="vacation",
                status="pending",
                start_date=date(year, 12, 28),
                end_date=date(year, 12, 29),
            ),
            LeaveRequest(
                user_id=person.id,
                leave_type="vacation",
                status="cancelled",
                start_date=date(year, 2, 2),
                end_date=date(year, 2, 2),
            ),
            # Inny rok — poza listą.
            LeaveRequest(
                user_id=person.id,
                leave_type="vacation",
                status="approved",
                start_date=date(year - 1, 6, 1),
                end_date=date(year - 1, 6, 2),
            ),
        ]
    )
    sheet = Timesheet(
        user_id=person.id,
        year=today.year,
        month=today.month,
        status="approved",
        approved_by=boss.id,
        pdf_hash="a" * 64,
    )
    db.add(sheet)
    await db.flush()
    db.add(
        TimesheetEntry(
            timesheet_id=sheet.id,
            work_date=date(today.year, today.month, 1),
            hours=Decimal("7.5"),
            description="Praca",
        )
    )
    await db.commit()
    return today, boss, person, sheet


@pytest.mark.asyncio
async def test_history_in_full_scope_with_type_for_d6_circle(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        today, boss, person, sheet = await _seed(db)

    for viewer in (person, boss):
        response = await app_client.get(
            f"/api/hr/people/{person.id}/history", headers=_headers(viewer)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == today.year
        absences = body["absences"]
        assert absences["type_visible"] is True
        states = sorted(
            (item["state"], item["leave_type"]) for item in absences["items"]
        )
        # Anulowany i z innego roku nie wracają.
        assert states == sorted([("used", "sick_leave"), ("waiting", "vacation")])
        assert "sekretny" not in response.text
        months = body["timesheets"]["items"]
        assert months[0]["year"] == today.year and months[0]["month"] == today.month
        assert months[0]["timesheet_id"] == sheet.id
        assert months[0]["status"] == "approved"
        assert months[0]["hours"] == 7.5
        assert months[0]["has_pdf"] is True
        assert months[0]["norm_hours"] > 0
        # Osoba składa raport — miesiące bez raportu są wierszem „nie założony”.
        assert len(months) == person_history.TIMESHEET_MONTHS
        assert all(item["status"] is None for item in months[1:])


@pytest.mark.asyncio
async def test_history_for_finance_without_type_and_only_approved(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        _, _, person, _ = await _seed(db)
        finance = await _user(db, "finance")
        await db.commit()

    response = await app_client.get(
        f"/api/hr/people/{person.id}/history", headers=_headers(finance)
    )
    assert response.status_code == 200
    absences = response.json()["absences"]
    assert absences["type_visible"] is False
    assert [(i["state"], i["leave_type"], i["label"]) for i in absences["items"]] == [
        ("used", None, "Nieobecność")
    ]
    assert "sick_leave" not in response.text
    assert "Zwolnienie" not in response.text


@pytest.mark.asyncio
async def test_history_for_people_admin_without_form_hides_pool_wording(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        from app.core.scheduling import business_today
        from app.models.hr_leave import LeaveRequest

        year = business_today().year
        hr = await _user(db, "recruiter", profile=True)
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        contractor = await _user(db, "employee", profile=True, employment_type="b2b")
        db.add(
            LeaveRequest(
                user_id=contractor.id,
                leave_type="vacation",
                status="approved",
                start_date=date(year, 3, 2),
                end_date=date(year, 3, 3),
            )
        )
        await db.commit()

    response = await app_client.get(
        f"/api/hr/people/{contractor.id}/history", headers=_headers(hr)
    )
    assert response.status_code == 200
    absences = response.json()["absences"]
    assert absences["type_visible"] is True
    assert [i["label"] for i in absences["items"]] == ["Nieobecność"]
    assert "Przerwa" not in response.text


@pytest.mark.asyncio
async def test_history_refused_outside_full_scope(app_client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        _, _, person, _ = await _seed(db)
        colleague = await _user(db, "recruiter", profile=True)
        await db.commit()

    refused = await app_client.get(
        f"/api/hr/people/{person.id}/history", headers=_headers(colleague)
    )
    assert refused.status_code == 403
    missing = await app_client.get(
        "/api/hr/people/987654321/history", headers=_headers(colleague)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_history_parts_follow_open_modules(app_client) -> None:
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: key == "people" for key in HR_MODULE_KEYS})
    try:
        async with AsyncSessionLocal() as db:
            _, boss, person, _ = await _seed(db)
        response = await app_client.get(
            f"/api/hr/people/{person.id}/history", headers=_headers(boss)
        )
        assert response.status_code == 200
        assert response.json()["absences"] is None
        assert response.json()["timesheets"] is None
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})
