"""Haki urlopów: akceptacja wniosku czyści godziny z pełnych dni urlopu.

Test integracyjny z modułem „leave”: wnioski zakładane surowym SQL-em na
kolumnach z kontraktu (``leave_requests``, ``leave_request_days``); po
integracji moduł urlopów woła ``on_leave_approved`` w swojej akceptacji —
wtedy ten sam scenariusz warto powtórzyć przez jego API.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr.time_entries import entries_of, hash_of
from app.services.hr.time_hooks import on_leave_approved, on_leave_cancelled
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    headers,
    make_user,
    set_leave_status,
    time_on,
)

Y, M = 2031, 5
BASE = f"/api/hr/time/me/{Y}/{M}"


async def _approved_month(app_client, *, employment_type: str):
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        worker = await make_user(
            db, "employee", manager_user_id=boss.id, employment_type=employment_type
        )
        await db.commit()
    h = headers(worker)
    for day in (5, 6, 7):
        response = await app_client.post(
            f"{BASE}/entries",
            json={"work_date": f"{Y}-05-0{day}", "hours": 8, "description": "Praca"},
            headers=h,
        )
        assert response.status_code == 201, response.text
    ts_id = (await app_client.post(f"{BASE}/submit", headers=h)).json()["id"]
    approved = await app_client.post(
        f"/api/hr/time/timesheets/{ts_id}/approve", headers=headers(boss)
    )
    assert approved.status_code == 200
    return worker, ts_id, approved.json()["pdf_hash"]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_approved_leave_removes_hours_from_approved_timesheet_and_rehashes(
    app_client,
) -> None:
    worker, ts_id, old_hash = await _approved_month(app_client, employment_type="uop")
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 6)])
        await add_leave(db, worker.id, [date(Y, M, 7)], fraction=0.5)
        result = await on_leave_approved(db, worker.id, [date(Y, M, 6), date(Y, M, 7)])
        await db.commit()
    assert result["removed_entries"] == 1
    assert result["timesheets_touched"] == 1

    async with AsyncSessionLocal() as db:
        timesheet = await db.get(Timesheet, ts_id)
        entries = await entries_of(db, ts_id)
        days = sorted(entry.work_date.day for entry in entries)
        assert days == [5, 7]  # połówki nie ruszamy
        assert timesheet.status == "approved"
        assert timesheet.pdf_hash != old_hash
        assert timesheet.pdf_hash == hash_of(entries)
        actions = list(
            await db.scalars(
                select(HrAuditEvent.action).where(
                    HrAuditEvent.entity_type == "timesheet",
                    HrAuditEvent.entity_id == str(ts_id),
                )
            )
        )
    assert "leave_hours_removed" in actions
    # PDF dalej się pobiera — legalna zmiana przeliczyła sumę.
    pdf = await app_client.get(f"{BASE}/pdf", headers=headers(worker))
    assert pdf.status_code == 200


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_contractor_paid_leave_replaces_hours_with_standard_work(
    app_client,
) -> None:
    worker, ts_id, _ = await _approved_month(app_client, employment_type="b2b")
    async with AsyncSessionLocal() as db:
        leave_id = await add_leave(db, worker.id, [date(Y, M, 6)])
        await on_leave_approved(db, worker.id, [date(Y, M, 6)])
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(TimesheetEntry).where(
                    TimesheetEntry.timesheet_id == ts_id,
                    TimesheetEntry.work_date == date(Y, M, 6),
                )
            )
        )
        assert [(row.source, float(row.hours)) for row in rows] == [("leave_paid", 8.0)]
        timesheet = await db.get(Timesheet, ts_id)
        assert timesheet.pdf_hash == hash_of(await entries_of(db, ts_id))

    async with AsyncSessionLocal() as db:
        await set_leave_status(db, leave_id, "cancelled")
        result = await on_leave_cancelled(db, worker.id, [date(Y, M, 6)])
        await db.commit()
    assert result["timesheets_touched"] == 1
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            text(
                "SELECT count(*) FROM timesheet_entries "
                "WHERE timesheet_id = :id AND source = 'leave_paid'"
            ),
            {"id": ts_id},
        )
    assert left == 0


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_payroll_locked_month_is_reported_not_changed(app_client) -> None:
    worker, ts_id, old_hash = await _approved_month(app_client, employment_type="uop")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE timesheets SET payroll_locked = true WHERE id = :id"),
            {"id": ts_id},
        )
        await add_leave(db, worker.id, [date(Y, M, 5)])
        result = await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    assert result["locked_conflicts"] == ["2031-05"]
    assert result["removed_entries"] == 0
    async with AsyncSessionLocal() as db:
        timesheet = await db.get(Timesheet, ts_id)
        assert timesheet.pdf_hash == old_hash
        assert len(await entries_of(db, ts_id)) == 3


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_auto_entry_change_marks_the_draft_as_changed_in_nexus(
    app_client,
) -> None:
    # Audyt 19.10.2026 (zgłoszenie A4): odwołanie płatnego urlopu B2B kasowało
    # auto-wpis bez podbicia `timesheets.updated_at`, więc ponowny import
    # z Compassa brał szkic za niezmieniony i przywracał 8 h z odwołanego
    # wniosku. Każda zmiana auto-wpisów to zmiana w NEXUSIE (jak usunięcie wpisu).
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type="b2b")
        await db.commit()
    h = headers(worker)
    added = await app_client.post(
        f"{BASE}/entries",
        json={"work_date": f"{Y}-05-05", "hours": 8, "description": "Praca"},
        headers=h,
    )
    assert added.status_code == 201, added.text
    async with AsyncSessionLocal() as db:
        ts_id = (await db.get(TimesheetEntry, added.json()["id"])).timesheet_id
        await db.execute(
            text(
                "UPDATE timesheets SET updated_at = now() - interval '2 days' "
                "WHERE id = :id"
            ),
            {"id": ts_id},
        )
        await db.commit()
        before = (await db.get(Timesheet, ts_id)).updated_at

    async with AsyncSessionLocal() as db:
        leave_id = await add_leave(db, worker.id, [date(Y, M, 6)])
        await on_leave_approved(db, worker.id, [date(Y, M, 6)])
        await db.commit()
    async with AsyncSessionLocal() as db:
        after_approve = (await db.get(Timesheet, ts_id)).updated_at
        await db.execute(
            text(
                "UPDATE timesheets SET updated_at = now() - interval '2 days' "
                "WHERE id = :id"
            ),
            {"id": ts_id},
        )
        await db.commit()
        reset = (await db.get(Timesheet, ts_id)).updated_at
        await set_leave_status(db, leave_id, "cancelled")
        await on_leave_cancelled(db, worker.id, [date(Y, M, 6)])
        await db.commit()
    async with AsyncSessionLocal() as db:
        after_cancel = (await db.get(Timesheet, ts_id)).updated_at
        auto = list(
            await db.scalars(
                select(TimesheetEntry).where(
                    TimesheetEntry.timesheet_id == ts_id,
                    TimesheetEntry.source == "leave_paid",
                )
            )
        )
    assert after_approve > before
    assert auto == []
    assert after_cancel > reset
