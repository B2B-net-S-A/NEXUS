"""Na zleceniu puli płatnych dni nie ma nigdy (D6, 17.10.2026).

Kadry nie ustawią puli zleceniu (``PUT …/entitlements`` = 422), ale zmiana formy
z umowy o pracę na zlecenie w trakcie roku zostawiała wiersz puli z UoP —
zgłoszenie dostawało dni płatne, a „Potwierdzenie godzin” (art. 8b) auto-wpisy
8 h za dni, których nie przepracowano. Reguła siedzi w polityce
(``leave_policy.pool_applies``): plan dni, saldo, podgląd, most do godzin
i import z Compassa liczą zlecenie jak osobę bez puli, a wiersz puli zostaje
w bazie jako historia. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import LeaveEntitlement
from app.services.hr.calendar import WorkCalendar
from app.services.hr.compass_import import leave as leave_import
from app.services.hr.leave_policy import PoolYear, plan_days, pool_applies
from tests.test_hr_compass_import_leave import (
    leave_row,
    make_bundle,
    make_person,
    run_import,
)
from tests.test_hr_time_support import (  # noqa: F401
    add_leave,
    grant,
    headers,
    make_user,
    time_on,
)

D = Decimal
MON, FRI = date(2091, 11, 12), date(2091, 11, 16)


def test_policy_ignores_pool_on_mandate_only() -> None:
    assert [pool_applies(form) for form in ("uop", "b2b", "zlecenie", None)] == [
        True,
        True,
        False,
        True,
    ]
    days = [(date(2091, 3, 5), D("1")), (date(2091, 3, 6), D("1"))]
    pools = {2091: PoolYear(2091, D("20"))}
    mandate = plan_days(
        leave_type="vacation", employment_type="zlecenie", days=days, pools=pools
    )
    assert (mandate.paid, mandate.unpaid) == (D("0"), D("2"))
    assert [day.paid for day in mandate.days] == [False, False]
    assert mandate.years[0].has_pool is False
    assert mandate.years[0].remaining_before is None
    contractor = plan_days(
        leave_type="vacation", employment_type="b2b", days=days, pools=pools
    )
    assert (contractor.paid, contractor.unpaid) == (D("2"), D("0"))


@pytest.mark.asyncio
async def test_mandate_after_form_change_gets_no_paid_days_from_uop_pool(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        person = await make_user(
            db, "employee", employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()

    put = await app_client.put(
        f"/api/hr/admin/profiles/{person.id}/entitlements/2091",
        json={"entitlement_days": 20},
        headers=headers(hr),
    )
    assert put.status_code == 200, put.text
    patch = await app_client.patch(
        f"/api/hr/admin/profiles/{person.id}",
        json={"employment_type": "zlecenie"},
        headers=headers(hr),
    )
    assert patch.status_code == 200, patch.text

    report = {
        "leave_type": "vacation",
        "start_date": MON.isoformat(),
        "end_date": FRI.isoformat(),
    }
    preview = await app_client.post(
        "/api/hr/leave/preview", json=report, headers=headers(person)
    )
    assert preview.status_code == 200, preview.text
    assert (preview.json()["paid_days"], preview.json()["unpaid_days"]) == (
        "0.0",
        "5.0",
    )
    assert preview.json()["years"][0]["has_pool"] is False

    created = await app_client.post(
        "/api/hr/leave/requests", json=report, headers=headers(person)
    )
    assert created.status_code == 201, created.text
    assert (created.json()["paid_days"], created.json()["unpaid_days"]) == (
        "0.0",
        "5.0",
    )

    month = await app_client.get("/api/hr/time/me/2091/11", headers=headers(person))
    assert month.status_code == 200, month.text
    assert float(month.json()["totals"]["leave_paid_hours"]) == 0.0

    balance = await app_client.get(
        "/api/hr/leave/balance?year=2091", headers=headers(person)
    )
    assert balance.status_code == 200, balance.text
    body = balance.json()
    assert body["has_pool"] is False and body["has_paid_pool"] is False
    assert body["entitlement_days"] is None and body["remaining_days"] is None
    assert body["planned_days"] == "5.0"

    # Wiersz puli z czasu umowy o pracę zostaje jako historia.
    async with AsyncSessionLocal() as db:
        kept = await db.scalar(
            select(LeaveEntitlement.entitlement_days).where(
                LeaveEntitlement.user_id == person.id, LeaveEntitlement.year == 2091
            )
        )
    assert kept == D("20")


@pytest.mark.asyncio
async def test_paid_days_booked_before_form_change_give_mandate_no_hours(
    app_client,
    time_on,  # noqa: F811
) -> None:
    """Dzień z flagą ``paid`` z czasu umowy o pracę blokuje dzień zlecenia jak
    nieobecność bez wynagrodzenia — bez auto-wpisu 8 h."""

    async with AsyncSessionLocal() as db:
        person = await make_user(db, "employee", employment_type="zlecenie")
        await add_leave(db, person.id, [date(2091, 12, 4)], paid=True)
        await db.commit()

    month = await app_client.get("/api/hr/time/me/2091/12", headers=headers(person))
    assert month.status_code == 200, month.text
    assert float(month.json()["totals"]["leave_paid_hours"]) == 0.0
    blocked = await app_client.post(
        "/api/hr/time/me/2091/12/entries",
        json={"work_date": "2091-12-04", "hours": "8", "description": "Praca"},
        headers=headers(person),
    )
    assert blocked.status_code == 422, blocked.text
    filled = await app_client.post(
        "/api/hr/time/me/2091/12/entries",
        json={"work_date": "2091-12-05", "hours": "8", "description": "Praca"},
        headers=headers(person),
    )
    assert filled.status_code == 201, filled.text
    month = await app_client.get("/api/hr/time/me/2091/12", headers=headers(person))
    assert float(month.json()["totals"]["leave_paid_hours"]) == 0.0


def test_compass_import_gives_mandate_no_paid_days() -> None:
    days = leave_import.plan_request_days(
        WorkCalendar(),
        start=date(2026, 3, 9),
        end=date(2026, 3, 11),
        half_day=None,
        leave_type="vacation",
        employment_type="zlecenie",
        compass_paid_days=D("2"),
    )
    assert [paid for _, _, paid in days] == [False, False, False]


@pytest.mark.asyncio
async def test_compass_import_reports_dropped_mandate_paid_days() -> None:
    async with AsyncSessionLocal() as db:
        try:
            _, z_id, z_row = await make_person(
                db, f"{uuid.uuid4().hex[:8]}-zl", employment_type="zlecenie"
            )
            pending = leave_row(
                z_id,
                "2026-06-08",
                "2026-06-09",
                status="pending",
                decided_at=None,
                paid_days=2,
            )
            accepted = leave_row(z_id, "2026-06-15", "2026-06-15", paid_days=1)
            bundle = make_bundle(
                {"profiles": [z_row], "leave_requests": [pending, accepted]}
            )
            _, report, written = await run_import(db, "leave", bundle)
            assert written["requests_created"] == 2
            dropped = sum(
                count
                for reason, count in report["reasons"].items()
                if leave_import.MANDATE_PAID_DROPPED in reason
            )
            assert dropped == 2
            for row in (pending, accepted):
                request = await db.get(LeaveRequest, uuid.UUID(row["id"]))
                assert request.status == "approved"
                assert request.paid_days == D("0")
                paid = list(
                    await db.scalars(
                        select(LeaveRequestDay.paid).where(
                            LeaveRequestDay.leave_request_id == request.id
                        )
                    )
                )
                assert paid and not any(paid)
        finally:
            await db.rollback()
