"""Dni płatne i bezpłatne wniosku — jedna reguła (``leave_policy.split_days``).

Do 17.10.2026 liczyły je trzy kopie (plan wniosku, przeliczenie po dniu wolnym
firmy, import z Compassa), a odczyt wniosku brał ``days_total`` z wierszy
dni, a ``paid_days`` / ``unpaid_days`` z kolumn wniosku. Teraz kolumny są
zapisanym wynikiem ``split_days`` z ``leave_request_days`` i odczyt liczy to
samo z wierszy. Przypadki brzegowe: pula wyczerpana w połowie wniosku, Nowy
Rok (pula dwóch lat), pół dnia. Dane fikcyjne; daty w 2096–2097.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import CompanyDayOff, EmployeeProfile, LeaveEntitlement
from app.models.user import User, UserRole
from app.services.hr import leave_service
from app.services.hr.calendar import WorkCalendar
from app.services.hr.leave_policy import (
    PoolYear,
    plan_days,
    requested_days,
    split_days,
)
from tests.test_hr_leave_api import modules_on  # noqa: F401 — fikstura

D = Decimal
START, END = date(2096, 12, 27), date(2097, 1, 4)


@pytest.mark.parametrize(
    ("leave_type", "form", "start", "end", "half_day", "pools", "expected"),
    [
        # Pula wyczerpana w połowie: pół dnia puli nie dzieli dnia.
        (
            "vacation",
            "b2b",
            date(2096, 3, 5),
            date(2096, 3, 9),
            None,
            {2096: PoolYear(2096, D("2.5"))},
            (D("5"), D("2"), D("3")),
        ),
        # Nowy Rok: każdy rok z własnej puli, 1 stycznia nie jest dniem roboczym.
        (
            "vacation",
            "zlecenie",
            START,
            END,
            None,
            {2096: PoolYear(2096, D("1.5")), 2097: PoolYear(2097, D("2"))},
            (D("6"), D("3"), D("3")),
        ),
        # Pół dnia mieści się w połówce puli.
        (
            "vacation",
            "b2b",
            date(2096, 3, 5),
            date(2096, 3, 5),
            "morning",
            {2096: PoolYear(2096, D("0.5"))},
            (D("0.5"), D("0.5"), D("0")),
        ),
        # Kontraktor bez puli: wszystko bezpłatne.
        (
            "vacation",
            "b2b",
            date(2096, 3, 5),
            date(2096, 3, 6),
            None,
            {},
            (D("2"), D("0"), D("2")),
        ),
        # Umowa o pracę: urlop z puli płatny, bez części bezpłatnej.
        (
            "vacation",
            "uop",
            date(2096, 3, 5),
            date(2096, 3, 6),
            None,
            {2096: PoolYear(2096, D("26"))},
            (D("2"), D("2"), D("0")),
        ),
        # Rodzaj spoza puli nie ma podziału.
        (
            "sick_leave",
            "uop",
            date(2096, 3, 5),
            date(2096, 3, 6),
            None,
            {},
            (D("2"), D("0"), D("0")),
        ),
    ],
)
def test_split_matches_the_plan_year_by_year(
    leave_type, form, start, end, half_day, pools, expected
) -> None:
    plan = plan_days(
        leave_type=leave_type,
        employment_type=form,
        days=requested_days(WorkCalendar(), start, end, half_day),
        pools=pools,
    )
    split = split_days(((d.fraction, d.paid) for d in plan.days), leave_type=leave_type)
    assert (split.total, split.paid, split.unpaid) == expected
    # Niezależnie liczony podział per rok mówi to samo.
    assert split.paid == sum((y.paid for y in plan.years), D("0"))
    assert split.unpaid == sum((y.unpaid for y in plan.years), D("0"))


def test_unpaid_follows_the_day_rows_not_todays_form() -> None:
    """Dni bezpłatne zgłoszenia z B2B zostają bezpłatne także po zmianie formy
    osoby na umowę o pracę — tak liczy też saldo roku (``leave_balance``)."""

    rows = [(D("1"), True), (D("1"), False)]
    assert split_days(rows, leave_type="vacation").unpaid == D("1")
    assert split_days(rows, leave_type="occasional").unpaid == D("0")


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _stored(request_id: uuid.UUID) -> tuple[tuple[D, D, D], tuple[D, D]]:
    async with AsyncSessionLocal() as db:
        request = await db.get(LeaveRequest, request_id)
        rows = (
            await db.execute(
                select(LeaveRequestDay.fraction, LeaveRequestDay.paid).where(
                    LeaveRequestDay.leave_request_id == request_id
                )
            )
        ).all()
    split = split_days(rows, leave_type=request.leave_type)
    return (split.total, split.paid, split.unpaid), (
        request.paid_days,
        request.unpaid_days,
    )


@pytest.mark.usefixtures("modules_on")
@pytest.mark.asyncio
async def test_columns_rows_and_read_agree_across_new_year_and_recount(
    app_client,
) -> None:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        worker = User(
            email=f"split-{marker}@example.com",
            name=f"Osoba Przykładowa {marker}",
            role=UserRole.employee,
            roles=["employee"],
            is_active=True,
        )
        hr = User(
            email=f"split-hr-{marker}@example.com",
            name=f"Kadry Przykładowe {marker}",
            role=UserRole.admin,
            roles=["admin"],
            is_active=True,
        )
        db.add_all([worker, hr])
        await db.flush()
        db.add(EmployeeProfile(user_id=worker.id, employment_type="b2b"))
        db.add_all(
            [
                LeaveEntitlement(
                    user_id=worker.id, year=2096, entitlement_days=D("1.5")
                ),
                LeaveEntitlement(user_id=worker.id, year=2097, entitlement_days=D("2")),
            ]
        )
        await db.commit()

    created = await app_client.post(
        "/api/hr/leave/requests",
        json={
            "leave_type": "vacation",
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
        },
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["days_total"], body["paid_days"], body["unpaid_days"]) == (
        "6.0",
        "3.0",
        "3.0",
    )
    request_id = uuid.UUID(body["id"])
    from_rows, columns = await _stored(request_id)
    assert from_rows == (D("6"), D("3"), D("3"))
    assert columns == from_rows[1:]

    # Dzień wolny firmy na bezpłatnym dniu: znika z wniosku, kolumny = wiersze.
    off_day = date(2096, 12, 28)
    async with AsyncSessionLocal() as db:
        db.add(CompanyDayOff(day=off_day, name="Dzień wolny (test)"))
        await db.flush()
        admin = await db.get(User, hr.id)
        await leave_service.recount_for_company_day_off(
            db, day=off_day, actor=admin, added=True
        )
        await db.commit()
    try:
        from_rows, columns = await _stored(request_id)
        assert from_rows == (D("5"), D("3"), D("2"))
        assert columns == from_rows[1:]
        mine = await app_client.get(
            "/api/hr/leave/my-requests", headers=_headers(worker)
        )
        row = next(item for item in mine.json()["items"] if item["id"] == body["id"])
        assert (row["days_total"], row["paid_days"], row["unpaid_days"]) == (
            "5.0",
            "3.0",
            "2.0",
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CompanyDayOff).where(CompanyDayOff.day == off_day))
            await db.commit()
