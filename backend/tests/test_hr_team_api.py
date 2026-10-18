"""„Ludzie → Mój zespół” (etap 2, D6, 17.10.2026) — ``/api/hr/team``.

Przełożony widzi bezpośrednich podwładnych: kto jest dziś (rodzaj nieobecności
— krąg D6), pulę urlopu tylko u osób z pulą, a u reszty (B2B, zlecenie bez puli)
zaplanowane nieobecności, bieżący miesiąc, premie w drodze z kwotą, ale BEZ
stawek godzinowych i bez danych reguły (marża), oraz rzeczy do decyzji.
Kadry oglądają cudzy zespół przez ``?manager=``; kwoty premii widzi wtedy tylko
osoba z Płacami. Dane i kwoty fikcyjne.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_payroll import EmployeeRate, HrBonus
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.hr_time import Timesheet
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr.leave_policy import LEAVE_TYPE_LABELS
from app.services.hr.time_calendar import holiday_name
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/team"
#: Kwoty zmyślone i rzadkie — test szuka ich w całej odpowiedzi.
RATE = Decimal("987.65")
MARGIN = "123.45"
BONUS = Decimal("1500.00")


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str = "employee", *, profile: bool = True, **values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"team-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
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
async def modules():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )

    async def switch(**overrides: bool) -> None:
        await _set_modules({key: overrides.get(key, True) for key in HR_MODULE_KEYS})

    await switch()
    yield switch
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _future_workdays(count: int) -> list[date]:
    """Dni robocze po dziś w tym samym roku (może być mniej pod koniec roku)."""

    today = business_today()
    days: list[date] = []
    day = today + timedelta(days=1)
    while len(days) < count and day.year == today.year:
        if day.weekday() < 5 and holiday_name(day) is None:
            days.append(day)
        day += timedelta(days=1)
    return days


async def _leave(db, user: User, start: date, end: date, *, status: str, kind: str):
    request = LeaveRequest(
        user_id=user.id, leave_type=kind, status=status, start_date=start, end_date=end
    )
    db.add(request)
    await db.flush()
    return request


async def _world() -> dict:
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        sick = await _user(db, manager_user_id=boss.id, employment_type="uop")
        contractor = await _user(db, manager_user_id=boss.id)  # B2B bez puli
        other_boss = await _user(db, "recruiter")
        stranger = await _user(db, manager_user_id=other_boss.id)
        db.add(
            LeaveEntitlement(
                user_id=sick.id, year=today.year, entitlement_days=Decimal("20")
            )
        )
        # Dziś nieobecna (zwolnienie lekarskie — rodzaj widzi przełożony, D6).
        await _leave(
            db,
            sick,
            today - timedelta(days=1),
            today + timedelta(days=1),
            status="approved",
            kind="sick_leave",
        )
        planned = _future_workdays(2)
        if planned:
            request = await _leave(
                db,
                contractor,
                planned[0],
                planned[-1],
                status="approved",
                kind="vacation",
            )
            db.add_all(
                LeaveRequestDay(
                    leave_request_id=request.id, user_id=contractor.id, day=day
                )
                for day in planned
            )
        pending = await _leave(
            db,
            contractor,
            date(2091, 11, 12),
            date(2091, 11, 13),
            status="pending",
            kind="vacation",
        )
        timesheet = Timesheet(
            user_id=contractor.id,
            year=today.year,
            month=today.month,
            status="submitted",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(timesheet)
        db.add(
            EmployeeRate(
                user_id=contractor.id,
                hourly_rate=RATE,
                effective_from=date(today.year, today.month, 1),
            )
        )
        db.add(
            HrBonus(
                recipient_user_id=contractor.id,
                amount=BONUS,
                currency="PLN",
                category="recruiter",
                period_year=2091,
                period_month=11,
                status="proposed",
                source="contract_placement",
                source_key=f"team-test-{uuid.uuid4().hex}",
                rule_snapshot={"margin_per_hour": MARGIN, "hourly_rate": str(RATE)},
                description="Rekruter — placement (Bank Przykładowy)",
            )
        )
        await db.commit()
        return {
            "boss": boss,
            "sick": sick,
            "contractor": contractor,
            "other_boss": other_boss,
            "stranger": stranger,
            "planned": len(planned),
            "pending": str(pending.id),
            "timesheet": timesheet.id,
        }


@pytest.mark.asyncio
async def test_manager_sees_today_absences_month_bonuses_and_decisions(
    app_client, modules
) -> None:
    world = await _world()
    response = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["user_id"]: row for row in body["people"]}

    assert set(rows) == {world["sick"].id, world["contractor"].id}
    assert body["is_own"] is True and body["sees_bonuses"] is True

    sick = rows[world["sick"].id]
    assert sick["employment_type"] == "uop"
    assert sick["today"]["absent"] is True
    assert sick["today"]["leave_type_label"] == LEAVE_TYPE_LABELS["sick_leave"]
    assert sick["leave"]["has_pool"] is True
    assert sick["leave"]["remaining_days"] == "20.0"

    contractor = rows[world["contractor"].id]
    assert contractor["employment_type"] == "b2b"
    assert contractor["today"] == {"absent": False}
    # B2B bez puli: zamiast „zostało” — zaplanowane nieobecności.
    assert contractor["leave"]["has_pool"] is False
    assert contractor["leave"]["remaining_days"] is None
    assert contractor["leave"]["planned_days"] == f"{world['planned']:.1f}"
    assert contractor["month"]["status"] == "submitted"
    assert body["month"]["norm_hours"] > 0
    assert [item["id"] for item in contractor["to_decide"]["leave_requests"]] == [
        world["pending"]
    ]
    assert [item["id"] for item in contractor["to_decide"]["timesheets"]] == [
        world["timesheet"]
    ]
    bonuses = contractor["bonuses"]
    assert bonuses["count"] == 1 and bonuses["proposals"] == 1
    assert bonuses["totals"] == [{"currency": "PLN", "amount": "1500.00"}]
    assert body["stats"]["absent_today"] == 1
    assert body["stats"]["bonus_proposals"] == 1


@pytest.mark.asyncio
async def test_team_response_never_carries_rates_or_margin(app_client, modules) -> None:
    """D2: przełożony widzi godziny i kwoty premii zespołu, nigdy stawek."""

    world = await _world()
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "finance", profile=False)
        await _grant(db, hr, "people_admin")
        await db.commit()
    for viewer, params in ((world["boss"], {}), (hr, {"manager": world["boss"].id})):
        response = await app_client.get(BASE, params=params, headers=_headers(viewer))
        assert response.status_code == 200, response.text
        text = json.dumps(response.json())
        for forbidden in ("hourly_rate", "rule_snapshot", "margin", str(RATE), MARGIN):
            assert forbidden not in text, forbidden


@pytest.mark.asyncio
async def test_access_is_for_managers_and_kadry(app_client, modules) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter", profile=False)
        await _grant(db, hr, "people_admin")
        await db.commit()

    no_team = await app_client.get(BASE, headers=_headers(world["contractor"]))
    assert no_team.status_code == 403
    foreign = await app_client.get(
        BASE,
        params={"manager": world["other_boss"].id},
        headers=_headers(world["boss"]),
    )
    assert foreign.status_code == 403
    managers = await app_client.get(f"{BASE}/managers", headers=_headers(world["boss"]))
    assert managers.status_code == 403

    as_hr = await app_client.get(
        BASE, params={"manager": world["boss"].id}, headers=_headers(hr)
    )
    assert as_hr.status_code == 200
    body = as_hr.json()
    assert body["manager"]["user_id"] == world["boss"].id and body["is_own"] is False
    # Kadry bez Płac nie widzą kwot premii (payroll_access).
    assert body["sees_bonuses"] is False
    assert all(row["bonuses"] is None for row in body["people"])
    # Rodzaj nieobecności Kadry widzą (krąg D6).
    sick = next(row for row in body["people"] if row["user_id"] == world["sick"].id)
    assert sick["today"]["leave_type_label"] == LEAVE_TYPE_LABELS["sick_leave"]

    listed = await app_client.get(f"{BASE}/managers", headers=_headers(hr))
    assert world["boss"].id in {item["user_id"] for item in listed.json()["items"]}
    missing = await app_client.get(
        BASE, params={"manager": 2_000_000_000}, headers=_headers(hr)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_switched_off_modules(app_client, modules) -> None:
    world = await _world()
    await modules(people=False)
    off = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert off.status_code == 404

    await modules(leave=False, payroll=False)
    partial = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert partial.status_code == 200
    body = partial.json()
    assert body["modules"] == {"leave": False, "time": True, "payroll": False}
    assert body["sees_bonuses"] is False
    for row in body["people"]:
        # Wyłączony moduł to „nie dotyczy” (null), a nie zero.
        assert row["today"] is None and row["leave"] is None and row["bonuses"] is None
        assert row["to_decide"]["leave_requests"] == []
