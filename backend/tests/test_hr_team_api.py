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
from app.models.hr_time import AttendanceDay, Timesheet
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


@pytest.mark.asyncio
async def test_week_shows_day_states_without_leave_type(app_client, modules) -> None:
    """Mini-tydzień pn–pt (19.10.2026): stan dnia bez rodzaju nieobecności (D6).

    Nieobecność, wniosek czeka (krąg D6 — przełożony), delegacja i praca
    zdalna z „Mojego miesiąca”; przy zamkniętym module czasu bez delegacji
    i pracy zdalnej, przy zamkniętych urlopach i czasie — ``null``.
    """

    world = await _world()
    async with AsyncSessionLocal() as db:
        tripper = await _user(db, manager_user_id=world["boss"].id)
        await db.commit()
    first = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert first.status_code == 200, first.text
    days = first.json()["week"]["days"]
    assert len(days) == 5
    assert [date.fromisoformat(day["date"]).weekday() for day in days] == [
        0,
        1,
        2,
        3,
        4,
    ]
    working = [date.fromisoformat(day["date"]) for day in days if day["kind"] == "work"]
    if len(working) < 3:
        pytest.skip(
            "Tydzień z więcej niż dwoma dniami wolnymi — brak dni do sprawdzenia."
        )
    trip_day, remote_day, pending_day = working[0], working[1], working[2]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                AttendanceDay(user_id=tripper.id, day=trip_day, status="business_trip"),
                AttendanceDay(
                    user_id=tripper.id,
                    day=remote_day,
                    status="active",
                    location="remote",
                    note="z domu, hydraulik",
                ),
            ]
        )
        await _leave(
            db, tripper, pending_day, pending_day, status="pending", kind="sick_leave"
        )
        await db.commit()

    response = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["user_id"]: row for row in body["people"]}
    states = {item["date"]: item["state"] for item in rows[tripper.id]["week"]}
    assert states[trip_day.isoformat()] == "business_trip"
    assert states[remote_day.isoformat()] == "remote"
    assert states[pending_day.isoformat()] == "pending"
    for day in days:
        if day["kind"] != "work":
            assert states[day["date"]] == "off"
    today = business_today().isoformat()
    sick = {item["date"]: item["state"] for item in rows[world["sick"].id]["week"]}
    if sick.get(today) not in (None, "off"):
        assert sick[today] == "absent"
    # D6: tydzień nie niesie rodzaju ani notatki dnia — także dla przełożonego.
    text = json.dumps([row["week"] for row in body["people"]], ensure_ascii=False)
    for forbidden in (
        "leave_type",
        "sick_leave",
        LEAVE_TYPE_LABELS["sick_leave"],
        "hydraulik",
    ):
        assert forbidden not in text, forbidden
    contractor = rows[world["contractor"].id]["to_decide"]
    assert contractor["leave_requests"][0]["created_at"]
    assert contractor["timesheets"][0]["submitted_at"]

    await modules(time=False)
    no_time = (await app_client.get(BASE, headers=_headers(world["boss"]))).json()
    row = next(item for item in no_time["people"] if item["user_id"] == tripper.id)
    no_time_states = {item["date"]: item["state"] for item in row["week"]}
    assert no_time_states[trip_day.isoformat()] == "work"
    assert no_time_states[remote_day.isoformat()] == "work"
    assert no_time_states[pending_day.isoformat()] == "pending"

    # Sam moduł czasu (audyt 21.10.2026): nieobecności nie są czytane, więc
    # dzień bez wpisu to „unknown”, nie „work”; zdalnie i delegacja zostają.
    await modules(leave=False)
    no_leave = (await app_client.get(BASE, headers=_headers(world["boss"]))).json()
    row = next(item for item in no_leave["people"] if item["user_id"] == tripper.id)
    no_leave_states = {item["date"]: item["state"] for item in row["week"]}
    assert no_leave_states[trip_day.isoformat()] == "business_trip"
    assert no_leave_states[remote_day.isoformat()] == "remote"
    assert no_leave_states[pending_day.isoformat()] == "unknown"
    assert "work" not in no_leave_states.values()

    await modules(time=False, leave=False)
    closed = (await app_client.get(BASE, headers=_headers(world["boss"]))).json()
    assert closed["week"] is None
    assert all(item["week"] is None for item in closed["people"])


@pytest.mark.asyncio
async def test_team_queue_lists_missing_days_for_open_months_only(modules) -> None:
    """„brak dd.mm” w „Moim zespole” (22.10.2026): dni robocze przed datą bez
    wpisu i bez całodniowej nieobecności — tylko w szkicu albo przy braku
    raportu; wysłany miesiąc nie ma braków do pokazania."""

    from app.models.hr_time import TimesheetEntry
    from app.services.hr.time_access import Actor
    from app.services.hr.time_calendar import month_calendar
    from app.services.hr.time_month import team_queue

    year, month = 2091, 3
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        common = dict(
            manager_user_id=boss.id,
            timesheet_required=True,
            work_start_date=date(2090, 1, 1),
        )
        drafting = await _user(db, **common)
        idle = await _user(db, **common)
        sent = await _user(db, **common)
        calendar = await month_calendar(db, year, month)
        working = [item.day for item in calendar if item.is_working_day]
        cutoff = working[5]
        before = [day for day in working if day < cutoff]

        draft = Timesheet(user_id=drafting.id, year=year, month=month, status="draft")
        submitted = Timesheet(
            user_id=sent.id,
            year=year,
            month=month,
            status="submitted",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add_all([draft, submitted])
        await db.flush()
        db.add(
            TimesheetEntry(
                timesheet_id=draft.id,
                work_date=before[0],
                hours=Decimal("8"),
                project="Alfa",
                description="Rekrutacje",
                source="manual",
                is_overtime=False,
                overtime_reason=None,
            )
        )
        # Całodniowa nieobecność to nie brak wpisu.
        request = await _leave(
            db, drafting, before[1], before[1], status="approved", kind="vacation"
        )
        db.add(
            LeaveRequestDay(
                leave_request_id=request.id, user_id=drafting.id, day=before[1]
            )
        )
        await db.flush()

        actor = Actor(
            user=boss,
            profile=None,
            is_admin=False,
            people_admin=False,
            payroll=False,
            report_ids=frozenset({drafting.id, idle.id, sent.id}),
        )
        rows = {
            item["user_id"]: item
            for item in await team_queue(
                db, actor=actor, year=year, month=month, missing_before=cutoff
            )
        }
        plain = await team_queue(db, actor=actor, year=year, month=month)
        await db.rollback()

    iso = [day.isoformat() for day in before]
    assert rows[drafting.id]["missing_dates"] == iso[2:]
    assert rows[idle.id]["missing_dates"] == iso
    assert rows[sent.id]["missing_dates"] == []
    assert all("missing_dates" not in item for item in plain)
