"""Saldo urlopu rozbite (etap 2, „Mój czas → Przegląd”): wykorzystane,
zaplanowane, czeka — i „zostało” jak dotąd (z odjęciem oczekujących).

Brzegi: urlop trwający dziś (dzień dzisiejszy jest już wykorzystany), pół
dnia, urlop przez Nowy Rok (każdy dzień do puli swojego roku). „Dziś” podajemy
jawnie, żeby test nie zależał od zegara. Dane fikcyjne; daty w latach 209x.
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
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.user import User, UserRole
from app.services.hr.calendar import WorkCalendar
from app.services.hr.leave_balance import balance_payload
from app.services.hr.leave_policy import requested_days
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


async def _worker(db, employment_type: str = "uop") -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"balance-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, employment_type=employment_type))
    await db.flush()
    return user


async def _pool(db, user: User, year: int, days: str, used_initial: str = "0") -> None:
    db.add(
        LeaveEntitlement(
            user_id=user.id,
            year=year,
            entitlement_days=Decimal(days),
            used_initial_days=Decimal(used_initial),
        )
    )
    await db.flush()


async def _leave(
    db,
    user: User,
    start: date,
    end: date,
    status: str,
    *,
    half_day: str | None = None,
    leave_type: str = "vacation",
    paid: bool = True,
) -> None:
    """Wniosek z dniami liczonymi tą samą funkcją co przy składaniu."""

    days = requested_days(WorkCalendar(), start, end, half_day)
    request = LeaveRequest(
        user_id=user.id,
        leave_type=leave_type,
        status=status,
        start_date=start,
        end_date=end,
        half_day=half_day,
        paid_days=sum((fraction for _day, fraction in days), Decimal("0"))
        if paid
        else Decimal("0"),
        unpaid_days=Decimal("0")
        if paid
        else sum((fraction for _day, fraction in days), Decimal("0")),
    )
    db.add(request)
    await db.flush()
    for day, fraction in days:
        db.add(
            LeaveRequestDay(
                leave_request_id=request.id,
                user_id=user.id,
                day=day,
                fraction=fraction,
                paid=paid,
                active=status in ("pending", "approved"),
            )
        )
    await db.flush()


async def _balance(
    user: User, year: int, today: date, employment_type: str = "uop"
) -> dict:
    async with AsyncSessionLocal() as db:
        return await balance_payload(
            db,
            user_id=user.id,
            year=year,
            employment_type=employment_type,
            today=today,
        )


def _split(balance: dict) -> tuple[str, str, str, str]:
    return (
        balance["used_days"],
        balance["planned_days"],
        balance["pending_days"],
        balance["remaining_days"],
    )


@pytest.mark.asyncio
async def test_leave_running_today_counts_today_as_used() -> None:
    mon, fri = date(2092, 11, 17), date(2092, 11, 21)  # pon.–pt., bez świąt
    async with AsyncSessionLocal() as db:
        worker = await _worker(db)
        await _pool(db, worker, 2092, "26", used_initial="4")
        await _leave(db, worker, mon, fri, "approved")
        await _leave(db, worker, date(2092, 12, 1), date(2092, 12, 2), "pending")
        await db.commit()

    # Środa: pon.–śr. wykorzystane (z 4 dniami sprzed NEXUSA), czw.–pt. zaplanowane.
    wednesday = await _balance(worker, 2092, date(2092, 11, 19))
    assert _split(wednesday) == ("7.0", "2.0", "2.0", "15.0")
    assert wednesday["approved_days"] == "5.0"
    assert wednesday["as_of"] == "2092-11-19"
    # Dzień przed urlopem: całość zaplanowana; „zostało” bez zmian w czasie.
    before = await _balance(worker, 2092, date(2092, 11, 16))
    assert _split(before) == ("4.0", "5.0", "2.0", "15.0")
    # Rok po roku urlopu: wszystko wykorzystane.
    after = await _balance(worker, 2092, date(2093, 1, 15))
    assert _split(after) == ("9.0", "0.0", "2.0", "15.0")


@pytest.mark.asyncio
async def test_half_day_today_is_used_tomorrow_is_planned() -> None:
    today = date(2092, 11, 19)
    async with AsyncSessionLocal() as db:
        worker = await _worker(db)
        await _pool(db, worker, 2092, "20")
        await _leave(db, worker, today, today, "approved", half_day="afternoon")
        tomorrow = date(2092, 11, 20)
        await _leave(db, worker, tomorrow, tomorrow, "approved", half_day="morning")
        await db.commit()

    assert _split(await _balance(worker, 2092, today)) == ("0.5", "0.5", "0.0", "19.0")


@pytest.mark.asyncio
async def test_new_year_leave_splits_between_two_pools() -> None:
    # 29.12.2092 (pon.) – 02.01.2093 (pt.): 1 stycznia to święto, nie dzień urlopu.
    start, end = date(2092, 12, 29), date(2093, 1, 2)
    async with AsyncSessionLocal() as db:
        worker = await _worker(db)
        await _pool(db, worker, 2092, "26")
        await _pool(db, worker, 2093, "26")
        await _leave(db, worker, start, end, "approved")
        await db.commit()

    old_year = await _balance(worker, 2092, date(2092, 12, 31))
    assert _split(old_year) == ("3.0", "0.0", "0.0", "23.0")
    new_year = await _balance(worker, 2093, date(2092, 12, 31))
    assert _split(new_year) == ("0.0", "1.0", "0.0", "25.0")
    # Po Nowym Roku dzień 02.01 jest już wykorzystany w puli nowego roku.
    assert _split(await _balance(worker, 2093, date(2093, 1, 2))) == (
        "1.0",
        "0.0",
        "0.0",
        "25.0",
    )


@pytest.mark.asyncio
async def test_contractor_without_pool_has_no_remaining_but_counts_days() -> None:
    """B2B bez umownych dni i zlecenie: bez „zostało”, ale dni nieobecności
    (bez wynagrodzenia) liczą się w wykorzystanych, zaplanowanych i czekających."""

    today = date(2092, 11, 19)
    async with AsyncSessionLocal() as db:
        no_pool = await _worker(db, "b2b")
        await _leave(
            db, no_pool, date(2092, 11, 17), date(2092, 11, 18), "approved", paid=False
        )
        await _leave(
            db, no_pool, date(2092, 12, 1), date(2092, 12, 3), "approved", paid=False
        )
        await _leave(
            db, no_pool, date(2092, 12, 8), date(2092, 12, 8), "pending", paid=False
        )
        zero_pool = await _worker(db, "zlecenie")
        await _pool(db, zero_pool, 2092, "0")
        await _leave(
            db, zero_pool, date(2092, 12, 1), date(2092, 12, 2), "approved", paid=False
        )
        await db.commit()

    balance = await _balance(no_pool, 2092, today, "b2b")
    assert balance["has_pool"] is False and balance["has_paid_pool"] is False
    assert _split(balance) == ("2.0", "3.0", "1.0", None)
    assert balance["on_demand_limit"] is None and balance["childcare_limit"] is None
    zero = await _balance(zero_pool, 2092, today, "zlecenie")
    assert zero["has_pool"] is True and zero["has_paid_pool"] is False
    assert (zero["used_days"], zero["planned_days"]) == ("0.0", "2.0")


@pytest.mark.asyncio
async def test_contractor_with_contract_pool_counts_paid_days_only() -> None:
    """B2B z umowną pulą: liczą się dni płatne; dzień ponad pulę (bez
    wynagrodzenia) nie zjada puli i nie wchodzi do trzech liczb."""

    today = date(2092, 11, 19)
    async with AsyncSessionLocal() as db:
        worker = await _worker(db, "b2b")
        await _pool(db, worker, 2092, "5")
        await _leave(db, worker, date(2092, 11, 17), date(2092, 11, 18), "approved")
        await _leave(db, worker, date(2092, 12, 1), date(2092, 12, 1), "approved")
        await _leave(
            db, worker, date(2092, 12, 2), date(2092, 12, 2), "approved", paid=False
        )
        await db.commit()

    balance = await _balance(worker, 2092, today, "b2b")
    assert balance["has_paid_pool"] is True
    assert _split(balance) == ("2.0", "1.0", "0.0", "2.0")
    assert balance["unpaid_days"] == "1.0"
    assert balance["on_demand_used"] is None


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest.mark.asyncio
async def test_rejected_and_cancelled_do_not_count_and_route_returns_split(
    app_client, modules_on
) -> None:
    async with AsyncSessionLocal() as db:
        worker = await _worker(db)
        await _pool(db, worker, 2092, "10")
        await _leave(db, worker, date(2092, 11, 17), date(2092, 11, 18), "rejected")
        await _leave(db, worker, date(2092, 11, 19), date(2092, 11, 19), "cancelled")
        await db.commit()

    token = create_access_token(subject=worker.id, role=worker.role.value)
    response = await app_client.get(
        "/api/hr/leave/balance",
        params={"year": 2092},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert _split(body) == ("0.0", "0.0", "0.0", "10.0")
    assert {"used_days", "planned_days", "as_of", "approved_days"} <= set(body)
