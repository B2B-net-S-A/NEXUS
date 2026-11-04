"""Wspólne narzędzia testów „Mojego miesiąca” (bez własnych testów).

Konta, kartoteki, uprawnienia i wnioski urlopowe zakładane surowym SQL-em na
kolumnach z kontraktu modułu urlopów (``leave_requests``,
``leave_request_days``) — dokładnie te, które czyta most
``app/services/hr/time_leave_bridge.py``. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    db, role: str = "employee", *, profile: bool = True, **profile_values
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"czas-{marker}@example.com",
        name=f"Anna Przykładowa {marker}",
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


async def grant(db, user: User, action: str) -> None:
    db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    await db.flush()


async def add_leave(
    db,
    user_id: int,
    days: list[date],
    *,
    status: str = "approved",
    leave_type: str = "vacation",
    fraction: float = 1.0,
    paid: bool = True,
) -> str:
    """Wniosek z dniami (surowy SQL — kolumny z kontraktu modułu urlopów)."""

    half_day = "morning" if fraction < 1 else None
    leave_id = await db.scalar(
        text(
            """
            INSERT INTO leave_requests (user_id, leave_type, status, start_date,
                                        end_date, half_day, paid_days, unpaid_days)
            VALUES (:user_id, :leave_type, :status, :start, :end, :half_day, :paid,
                    :unpaid)
            RETURNING id::text
            """
        ),
        {
            "user_id": user_id,
            "leave_type": leave_type,
            "status": status,
            "start": min(days),
            "end": max(days),
            "half_day": half_day,
            "paid": fraction * len(days) if paid else 0,
            "unpaid": 0 if paid else fraction * len(days),
        },
    )
    for day in days:
        await db.execute(
            text(
                """
                INSERT INTO leave_request_days (leave_request_id, user_id, day,
                                                fraction, paid, active)
                VALUES (CAST(:leave_id AS uuid), :user_id, :day, :fraction, :paid, true)
                """
            ),
            {
                "leave_id": leave_id,
                "user_id": user_id,
                "day": day,
                "fraction": fraction,
                "paid": paid,
            },
        )
    return leave_id


async def set_leave_status(db, leave_id: str, status: str) -> None:
    active = status in ("pending", "approved")
    await db.execute(
        text("UPDATE leave_requests SET status = :status WHERE id = CAST(:id AS uuid)"),
        {"status": status, "id": leave_id},
    )
    await db.execute(
        text(
            "UPDATE leave_request_days SET active = :active "
            "WHERE leave_request_id = CAST(:id AS uuid)"
        ),
        {"active": active, "id": leave_id},
    )


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _previous() -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )


@pytest_asyncio.fixture
async def time_on():
    previous = await _previous()
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def time_off():
    previous = await _previous()
    await _set_modules({key: False for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def notifications_of(user_id: int, ntype: str) -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                "SELECT title, message FROM notifications "
                "WHERE user_id = :user_id AND notification_type::text = :ntype "
                "ORDER BY id"
            ),
            {"user_id": user_id, "ntype": ntype},
        )
        return [(title, message) for title, message in rows.all()]
