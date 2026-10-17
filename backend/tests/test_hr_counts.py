"""Liczniki zakładek „Ludzi” — ``GET /api/hr/counts`` (17.10.2026).

„Akceptacje”: wnioski i timesheety, o których czytający może zdecydować (ten
sam zakres co ekran); „Sprawy”: otwarte sprawy przypisane do niego. ``null``
= liczba osoby nie dotyczy. Router jest wpinany do ``app/main.py`` przez
koordynatora, więc test stawia własną aplikację z samym tym routerem.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import hr_counts
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.admin_case import AdminCase
from app.models.app_setting import AppSetting
from app.models.hr_leave import LeaveRequest
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str = "employee", *, manager: User | None = None) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"hr-counts-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        EmployeeProfile(
            user_id=user.id, manager_user_id=manager.id if manager else None
        )
    )
    await db.flush()
    return user


def _leave(user: User, status: str = "pending") -> LeaveRequest:
    return LeaveRequest(
        user_id=user.id,
        leave_type="vacation",
        status=status,
        start_date=date(2030, 3, 4),
        end_date=date(2030, 3, 5),
        paid_days=Decimal("2"),
        unpaid_days=Decimal("0"),
        source="self",
    )


def _timesheet(user: User, month: int, status: str = "submitted", **extra):
    return Timesheet(
        user_id=user.id,
        year=2030,
        month=month,
        status=status,
        submitted_at=datetime(2030, month, 2, tzinfo=timezone.utc),
        **extra,
    )


def _case(assignee: User, status: str = "new") -> AdminCase:
    closed = status in {"done", "closed"}
    return AdminCase(
        title="Wydanie karty wejściowej",
        status=status,
        assignee_user_id=assignee.id,
        source="manual",
        closed_at=datetime(2030, 3, 1, tzinfo=timezone.utc) if closed else None,
    )


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _modules(value: dict):
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules(value)
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def modules_on():
    async for _ in _modules({key: True for key in HR_MODULE_KEYS}):
        yield


@pytest_asyncio.fixture
async def modules_off():
    async for _ in _modules({key: False for key in HR_MODULE_KEYS}):
        yield


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(hr_counts.router, prefix="/api/hr/counts")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_manager_counts_only_own_team_and_not_own_items(
    client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        first = await _user(db, manager=boss)
        second = await _user(db, manager=boss)
        stranger = await _user(db)
        db.add_all(
            [
                _leave(first),
                _leave(second, status="approved"),  # już zdecydowany
                _leave(stranger),  # spoza zespołu
                _leave(boss),  # własny wniosek
                _timesheet(second, 1),
                _timesheet(second, 2),  # drugi miesiąc też czeka
                _timesheet(first, 1, status="draft"),
                _timesheet(first, 2, payroll_locked=True),  # zamknięty płacami
                _timesheet(stranger, 1),
            ]
        )
        await db.commit()

    response = await client.get("/api/hr/counts", headers=_headers(boss))
    assert response.status_code == 200
    # 1 wniosek + 2 timesheety; Sprawy bez dostępu = brak liczby.
    assert response.json() == {"approvals": 3, "cases": None}

    worker = await client.get("/api/hr/counts", headers=_headers(first))
    assert worker.json() == {"approvals": 0, "cases": None}


@pytest.mark.asyncio
async def test_people_admin_counts_everyone_but_self(client, modules_on) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter")
        db.add(
            UserActionOverride(user_id=hr.id, action="people_admin", access="manage")
        )
        other = await _user(db)
        await db.flush()
        db.add(_leave(hr))
        await db.commit()
    before = (await client.get("/api/hr/counts", headers=_headers(hr))).json()

    async with AsyncSessionLocal() as db:
        db.add_all([_leave(other), _timesheet(other, 5)])
        await db.commit()
    after = (await client.get("/api/hr/counts", headers=_headers(hr))).json()
    assert after["approvals"] == before["approvals"] + 2


@pytest.mark.asyncio
async def test_cases_count_open_assigned_and_hide_without_access(
    client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        assignee = await _user(db)
        handler = await _user(db, "talent_community_manager")
        db.add(UserActionOverride(user_id=handler.id, action="cases", access="manage"))
        nobody = await _user(db)
        db.add_all(
            [
                _case(assignee),
                _case(assignee, status="waiting"),
                _case(assignee, status="done"),
                _case(assignee, status="closed"),
            ]
        )
        await db.commit()

    mine = await client.get("/api/hr/counts", headers=_headers(assignee))
    assert mine.json()["cases"] == 2
    # Obsługa skrzynki bez przypisanych spraw: zero, nie brak liczby.
    assert (await client.get("/api/hr/counts", headers=_headers(handler))).json()[
        "cases"
    ] == 0
    assert (await client.get("/api/hr/counts", headers=_headers(nobody))).json()[
        "cases"
    ] is None


@pytest.mark.asyncio
async def test_switched_off_modules_give_no_numbers_except_admin(
    client, modules_off
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        report = await _user(db, manager=boss)
        db.add(_leave(report))
        admin = await _user(db, "admin")
        await db.commit()

    off = await client.get("/api/hr/counts", headers=_headers(boss))
    assert off.status_code == 200
    assert off.json() == {"approvals": None, "cases": None}
    # Admin widzi ekrany przy wyłączonym module — liczby też.
    on = (await client.get("/api/hr/counts", headers=_headers(admin))).json()
    assert isinstance(on["approvals"], int) and on["approvals"] >= 1
    assert isinstance(on["cases"], int)


@pytest.mark.asyncio
async def test_counts_need_a_session(client) -> None:
    assert (await client.get("/api/hr/counts")).status_code == 401
