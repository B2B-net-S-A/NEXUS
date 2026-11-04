"""Haki urlopów: akceptacja wniosku czyści godziny z pełnych dni urlopu
i skraca do 4 h ręczne godziny dni z połową urlopu.

Test integracyjny z modułem „leave”: wnioski zakładane surowym SQL-em na
kolumnach z kontraktu (``leave_requests``, ``leave_request_days``); po
integracji moduł urlopów woła ``on_leave_approved`` w swojej akceptacji —
wtedy ten sam scenariusz warto powtórzyć przez jego API.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr.time_entries import entries_of, hash_of, plan_half_day_trim
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
    assert result["trimmed_entries"] == 1
    assert result["timesheets_touched"] == 1
    assert result["sent_changed"] == ["2031-05"]

    async with AsyncSessionLocal() as db:
        timesheet = await db.get(Timesheet, ts_id)
        entries = await entries_of(db, ts_id)
        hours = sorted((entry.work_date.day, float(entry.hours)) for entry in entries)
        # Pół dnia: drugą połowę wolno przepracować, ale najwyżej 4 h
        # (decyzja Artura 28.10.2026 — akceptujący widział 8 h + pół dnia).
        assert hours == [(5, 8.0), (7, 4.0)]
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
    assert "leave_hours_trimmed" in actions
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


async def _draft_with(app_client, *, employment_type: str, entries: list[float]):
    """Szkic z ręcznymi wpisami jednego dnia (5.05) w kolejności dodania."""

    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type=employment_type)
        await db.commit()
    ts_id = None
    for hours in entries:
        response = await app_client.post(
            f"{BASE}/entries",
            json={"work_date": f"{Y}-05-05", "hours": hours, "description": "Praca"},
            headers=headers(worker),
        )
        assert response.status_code == 201, response.text
        async with AsyncSessionLocal() as db:
            ts_id = (await db.get(TimesheetEntry, response.json()["id"])).timesheet_id
    return worker, ts_id


async def _day_rows(ts_id: int) -> list[tuple[str, float]]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(TimesheetEntry)
            .where(
                TimesheetEntry.timesheet_id == ts_id,
                TimesheetEntry.work_date == date(Y, M, 5),
            )
            .order_by(TimesheetEntry.id)
        )
        return [(row.source, float(row.hours)) for row in rows]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_half_day_trims_latest_entries_first(app_client) -> None:
    worker, ts_id = await _draft_with(app_client, employment_type="uop", entries=[5, 3])
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 5)], fraction=0.5)
        result = await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    # Najpóźniej dodany wpis (3 h) schodzi do zera i znika, 5 h → 4 h.
    assert await _day_rows(ts_id) == [("manual", 4.0)]
    assert result["trimmed_entries"] == 2
    assert result["sent_changed"] == []  # szkic — bez dzwonka koordynatora
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(HrAuditEvent.details).where(
                HrAuditEvent.entity_type == "timesheet",
                HrAuditEvent.entity_id == str(ts_id),
                HrAuditEvent.action == "leave_hours_trimmed",
            )
        )
    assert details["days"] == [
        {"day": f"{Y}-05-05", "hours_before": "8", "hours_after": "4"}
    ]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_half_day_is_idempotent_on_repeat(app_client) -> None:
    # Edycja wniosku (leave_edit) woła hak ponownie na tych samych dniach.
    worker, ts_id = await _draft_with(app_client, employment_type="uop", entries=[8])
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 5)], fraction=0.5)
        await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    async with AsyncSessionLocal() as db:
        again = await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    assert again["trimmed_entries"] == 0
    assert again["timesheets_touched"] == 0
    assert await _day_rows(ts_id) == [("manual", 4.0)]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_b2b_paid_half_day_keeps_four_manual_hours_plus_auto_entry(
    app_client,
) -> None:
    worker, ts_id = await _draft_with(app_client, employment_type="b2b", entries=[8])
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 5)], fraction=0.5)
        await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    # Pula B2B: 4 h ręcznie + auto-wpis 4 h („Praca standardowa”) = 8 h.
    assert sorted(await _day_rows(ts_id)) == [("leave_paid", 4.0), ("manual", 4.0)]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_payroll_locked_half_day_is_reported_not_trimmed(app_client) -> None:
    worker, ts_id = await _draft_with(app_client, employment_type="uop", entries=[8])
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE timesheets SET payroll_locked = true WHERE id = :id"),
            {"id": ts_id},
        )
        await add_leave(db, worker.id, [date(Y, M, 5)], fraction=0.5)
        result = await on_leave_approved(db, worker.id, [date(Y, M, 5)])
        await db.commit()
    assert result["locked_conflicts"] == ["2031-05"]
    assert result["trimmed_entries"] == 0
    assert await _day_rows(ts_id) == [("manual", 8.0)]


# ── Plan skrócenia (bez bazy) ─────────────────────────────────────────────────


def _entry(entry_id: int, hours: str, **values) -> TimesheetEntry:
    return TimesheetEntry(
        id=entry_id,
        work_date=values.pop("work_date", date(Y, M, 5)),
        hours=Decimal(hours),
        description="Praca",
        source=values.pop("source", "manual"),
        is_overtime=values.pop("is_overtime", False),
        **values,
    )


def test_trim_plan_cuts_from_the_latest_entry() -> None:
    plan = plan_half_day_trim(
        [_entry(1, "5"), _entry(2, "3")], {date(Y, M, 5): Decimal("4")}
    )
    assert plan == {2: Decimal("0"), 1: Decimal("4")}


def test_trim_plan_leaves_days_within_the_limit() -> None:
    plan = plan_half_day_trim(
        [_entry(1, "3.5"), _entry(2, "8", work_date=date(Y, M, 6))],
        {date(Y, M, 5): Decimal("4")},
    )
    assert plan == {}


def test_trim_plan_skips_auto_entries_and_overtime() -> None:
    # Auto-wpis puli B2B liczy się sam; nadgodzina (z uzasadnieniem, ponad
    # 8 h sumy dnia) zostaje — limit dnia dotyczy zwykłych godzin.
    plan = plan_half_day_trim(
        [
            _entry(1, "4", source="leave_paid"),
            _entry(2, "8"),
            _entry(3, "2", is_overtime=True, overtime_reason="Wdrożenie"),
        ],
        {date(Y, M, 5): Decimal("4")},
    )
    assert plan == {2: Decimal("4")}
