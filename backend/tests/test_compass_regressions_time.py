"""Błędy Compassa w czasie pracy — każdy z testem, który by go złapał.

1. Flaga nadgodzin liczona z godzin JEDNEGO wpisu: 5 h + 5 h przechodziło
   bez uzasadnienia (``resolveOvertimeColumns(ctx, input.hours, …)``).
2. Kontrola sumy dnia nie była atomowa — dwa równoległe zapisy po 5 h
   przechodziły razem (komentarz przy ``assertDailyHoursWithinLimit``).
3. Admin zatwierdzał własny timesheet (brak blokady samozatwierdzenia).
4. Powiadomienie o wysłanym timesheecie bez przełożonego szło do wszystkich
   adminów, także tych, którzy odeszli (``internal-timesheet.ts:1869``).
5. Skasowanie wiersza obecności odblokowywało godziny w dniu urlopu
   (``deleteAttendanceDay``) — dwa źródła prawdy.
6. Martwy status ``rejected`` (zwrot i tak wracał do ``draft``).
7. Ręczna edycja auto-wpisu płatnego urlopu osierocała godziny (HF-03).

Przypomnienia (role i osoby po odejściu) — ``test_hr_time_reminders.py``;
wektor sumy kontrolnej — ``test_hr_time_hash.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.hr_time import Timesheet
from app.services.hr.time_access import approval_recipients
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    grant,
    headers,
    make_user,
    time_on,
)

Y, M = 2031, 7
BASE = f"/api/hr/time/me/{Y}/{M}"


def _entry(day: int, hours: float, **extra) -> dict:
    return {
        "work_date": date(Y, M, day).isoformat(),
        "hours": hours,
        "description": "Praca nad rekrutacjami",
        **extra,
    }


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_overtime_is_decided_by_the_day_sum_not_one_entry(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", can_log_overtime=True)
        await db.commit()
    h = headers(worker)
    assert (
        await app_client.post(f"{BASE}/entries", json=_entry(1, 5), headers=h)
    ).status_code == 201
    silent = await app_client.post(f"{BASE}/entries", json=_entry(1, 5), headers=h)
    assert silent.status_code == 422
    # Osoba na B2B (forma domyślna): opis godzin ponad 8 h, bez „nadgodzin” (21.10.2026).
    assert "czego dotyczyły godziny ponad 8 h" in silent.json()["detail"]
    justified = await app_client.post(
        f"{BASE}/entries",
        json=_entry(1, 5, overtime_reason="Wdrożenie kandydata u klienta"),
        headers=h,
    )
    assert justified.status_code == 201
    assert justified.json()["is_overtime"] is True


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_parallel_entries_cannot_both_pass_the_day_limit(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee")
        await db.commit()
    h = headers(worker)
    # Najpierw szkic, żeby oba żądania stanęły w kolejce na tym samym wierszu.
    await app_client.post(f"{BASE}/entries", json=_entry(2, 1), headers=h)
    first, second = await asyncio.gather(
        app_client.post(f"{BASE}/entries", json=_entry(3, 5), headers=h),
        app_client.post(f"{BASE}/entries", json=_entry(3, 5), headers=h),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 403]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_admin_cannot_approve_own_timesheet(app_client) -> None:
    async with AsyncSessionLocal() as db:
        admin = await make_user(db, "admin")
        await db.commit()
    h = headers(admin)
    await app_client.post(f"{BASE}/entries", json=_entry(7, 8), headers=h)
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]
    response = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=h
    )
    assert response.status_code == 403
    async with AsyncSessionLocal() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    "UPDATE timesheets SET status = 'approved', approved_by = user_id "
                    "WHERE id = :id"
                ),
                {"id": ts_id},
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_submit_notice_without_live_manager_goes_to_hr_not_leavers() -> None:
    async with AsyncSessionLocal() as db:
        gone_manager = await make_user(db, "recruiter", employment_status="exited")
        worker = await make_user(db, "employee", manager_user_id=gone_manager.id)
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        retired_hr = await make_user(db, "recruiter", profile=False)
        await grant(db, retired_hr, "people_admin")
        retired_hr.is_active = False
        await db.commit()
    async with AsyncSessionLocal() as db:
        recipients = await approval_recipients(db, worker.id)
    assert hr.id in recipients
    assert gone_manager.id not in recipients
    assert retired_hr.id not in recipients
    assert worker.id not in recipients


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_attendance_cannot_unblock_a_leave_day(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type="uop")
        await add_leave(
            db, worker.id, [date(Y, M, 8)], leave_type="sick_leave", paid=False
        )
        await db.commit()
    h = headers(worker)
    attendance = await app_client.put(
        f"/api/hr/time/me/attendance/{Y}-07-08",
        json={"status": "active", "location": "onsite"},
        headers=h,
    )
    assert attendance.status_code == 422
    hours = await app_client.post(f"{BASE}/entries", json=_entry(8, 8), headers=h)
    assert hours.status_code == 422
    async with AsyncSessionLocal() as db:
        statuses = await db.scalar(
            text(
                "SELECT count(*) FROM attendance_days WHERE user_id = :u AND day = :d"
            ),
            {"u": worker.id, "d": date(Y, M, 8)},
        )
    assert statuses == 0  # urlop nie ma kopii w obecności


@pytest.mark.asyncio
async def test_rejected_status_does_not_exist() -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee")
        db.add(Timesheet(user_id=worker.id, year=Y, month=M, status="rejected"))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_paid_leave_entry_cannot_be_moved_or_deleted_by_hand(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type="b2b")
        await add_leave(db, worker.id, [date(Y, M, 9)])
        await db.commit()
    h = headers(worker)
    # Auto-wpis jest wierszem od pierwszego zapisu miesiąca (odczyt nie zapisuje).
    first = await app_client.post(f"{BASE}/entries", json=_entry(14, 8), headers=h)
    assert first.status_code == 201, first.text
    month = (await app_client.get(BASE, headers=h)).json()
    auto = next(d for d in month["days"] if d["date"] == f"{Y}-07-09")["entries"][0]
    assert auto["source"] == "leave_paid"
    moved = await app_client.patch(
        f"/api/hr/time/me/entries/{auto['id']}",
        json={"work_date": f"{Y}-07-10"},
        headers=h,
    )
    assert moved.status_code == 409
    deleted = await app_client.delete(
        f"/api/hr/time/me/entries/{auto['id']}", headers=h
    )
    assert deleted.status_code == 409
