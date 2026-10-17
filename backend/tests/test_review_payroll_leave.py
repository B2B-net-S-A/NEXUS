"""Poprawki po przeglądzie płac, czasu i urlopów (16.10.2026, B4–B10, D18).

* B4 — koniec stawki z Compassa jest wyłączny (1. dzień kolejnej stawki),
  w NEXUSIE to ostatni dzień; raport bierze najnowszą stawkę deterministycznie,
* B5 — ponowny import nie nadpisuje decyzji podjętych w NEXUSIE,
* B6 — urlop w zamkniętym miesiącu płac: ostrzeżenie w odpowiedzi, dzwonek
  i ślad dla Płac,
* B7 — zamknięcie miesiąca i akceptacje (timesheet, premia) nie mijają się,
* B8 — cofnięcie zakończenia przywraca premię także z zamkniętego miesiąca,
* B9 — pół dnia urlopu zajmuje 4 h normy także w nadgodzinach płac,
* B10 — dzień wolny firmy przelicza dni aktywnych wniosków,
* D18 — wniosek jedynej osoby z Kadr bez przełożonego trafia do adminów.

Dane fikcyjne (repo publiczne), daty w przyszłości albo w dalekiej
przeszłości (zamknięcie miesiąca wymaga miesiąca, który się skończył).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract import ContractStatus
from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import EmployeeRate, HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import CompanyDayOff, EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.hr import (
    compass_import,
    leave_service,
    payroll_bonuses,
    payroll_close,
    payroll_periods,
    payroll_report,
    payroll_time_bridge,
    placement_bonuses,
    recipients,
    time_flow,
)
from app.services.hr.compass_import import leave as leave_import
from app.services.hr.compass_import import time as time_import
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_errors import PayrollConflict
from app.services.hr.payroll_periods import add_months
from app.services.hr.time_access import Actor
from app.services.hr.time_entries import TimeConflict
from app.services.hr.time_month import month_view
from tests.test_hr_bonus_automation import (  # noqa: F401
    _bonuses,
    _placement,
    _reconcile,
    _update_contract,
    payroll_on,
)
from tests.test_hr_compass_import_leave import (
    leave_row,
    make_bundle,
    make_person,
    run_import,
)
from tests.hr_settlements_seed import delete_settlement_rows
from tests.test_hr_leave_api import (  # noqa: F401
    _body,
    _grant,
    _headers,
    _user,
    modules_on,
)

LEAVE = "/api/hr/leave"
DAYS_OFF = "/api/hr/admin/days-off"


def _ts_actor(user: User) -> Actor:
    return Actor(
        user=user, profile=None, is_admin=True, people_admin=False, payroll=False
    )


async def _apply_bundle(module: str, bundle) -> dict:
    """Na sucho + zapis w jednej transakcji, commit (jak wiersz poleceń)."""

    async with AsyncSessionLocal() as db:
        batch, report, _written = await run_import(db, module, bundle)
        await db.commit()
        return report


async def _dry_run(module: str, bundle) -> dict:
    importer = compass_import.IMPORTERS[module]
    async with AsyncSessionLocal() as db:
        batch, _ = await compass_import.dry_run(
            db, module=module, bundle=bundle, planner=importer.plan, actor_user_id=None
        )
        report = batch.report["dry_run"]
        await db.rollback()
        return report


# ── B4: stawki ───────────────────────────────────────────────────────────────


def _rate_row(person: str, start: str, end, rate: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "hourly_rate": rate,
        "currency": "PLN",
        "effective_from": start,
        "effective_to": end,
        "reason": "Podwyżka roczna",
        "set_by": None,
        "created_at": "2092-01-01T08:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_compass_rate_end_is_exclusive_and_lands_as_last_day() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            person, p_id, p_row = await make_person(db, f"{tag}-rate")
            older = _rate_row(p_id, "2092-01-01", "2092-04-01", "111.00")
            newer = _rate_row(p_id, "2092-04-01", None, "122.00")
            bundle = make_bundle({"profiles": [p_row], "user_rates": [older, newer]})
            await run_import(db, "payroll", bundle)
            rates = list(
                await db.scalars(
                    select(EmployeeRate)
                    .where(EmployeeRate.user_id == person.id)
                    .order_by(EmployeeRate.effective_from)
                )
            )
            assert [(r.effective_from, r.effective_to) for r in rates] == [
                (date(2092, 1, 1), date(2092, 3, 31)),
                (date(2092, 4, 1), None),
            ]
            # W miesiącu podwyżki raport ma jedną stawkę — nową.
            people = await payroll_report.compute_live(db, 2092, 4)
            mine = next(p for p in people if p.user_id == person.id)
            assert [line.hourly_rate for line in mine.lines] == [Decimal("122.00")]
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_report_takes_newest_rate_when_two_rates_cover_the_day() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        try:
            person, _, _ = await make_person(db, f"{tag}-overlap")
            # Dane sprzed poprawki: stara stawka „do 1. dnia kolejnej” —
            # obie obejmują 1 maja. Nowsza zapisana pierwsza (kolejność w tabeli).
            db.add(
                EmployeeRate(
                    user_id=person.id,
                    hourly_rate=Decimal("130.00"),
                    effective_from=date(2092, 5, 1),
                )
            )
            await db.flush()
            db.add(
                EmployeeRate(
                    user_id=person.id,
                    hourly_rate=Decimal("120.00"),
                    effective_from=date(2092, 1, 1),
                    effective_to=date(2092, 5, 1),
                )
            )
            await db.flush()
            people = await payroll_report.compute_live(db, 2092, 5)
            mine = next(p for p in people if p.user_id == person.id)
            assert [line.hourly_rate for line in mine.lines] == [Decimal("130.00")]
        finally:
            await db.rollback()


# ── B5: ponowny import a decyzje NEXUSA ──────────────────────────────────────


@pytest.mark.asyncio
async def test_reimport_keeps_leave_cancelled_in_nexus() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        worker, w_id, w_row = await make_person(db, f"{tag}-worker")
        admin, _, _ = await make_person(db, f"{tag}-admin", role=UserRole.admin)
        await db.commit()
    row = leave_row(w_id, "2092-06-02", "2092-06-04", paid_days=3)
    bundle = make_bundle({"profiles": [w_row], "leave_requests": [row]})
    first = await _apply_bundle("leave", bundle)
    assert first["counts"] == {"create": 1}
    request_id = uuid.UUID(row["id"])

    # Kadry anulują urlop w NEXUSIE.
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, admin.id)
        await leave_service.cancel_as_approver(
            db, actor=actor, request_id=request_id, today=business_today()
        )
        await db.commit()

    again = await _dry_run("leave", bundle)
    assert again["counts"] == {"conflict": 1}
    assert again["reasons"] == {leave_import.CHANGED_IN_NEXUS: 1}
    await _apply_bundle("leave", bundle)
    async with AsyncSessionLocal() as db:
        request = await db.get(LeaveRequest, request_id)
        assert request.status == "cancelled"
        active = await db.scalars(
            select(LeaveRequestDay.active).where(
                LeaveRequestDay.leave_request_id == request_id
            )
        )
        assert set(active) == {False}

    # Compass też anulował — zgodne wersje, bez konfliktu.
    same = make_bundle(
        {"profiles": [w_row], "leave_requests": [{**row, "status": "cancelled"}]}
    )
    agreed = await _dry_run("leave", same)
    assert agreed["counts"] in ({"unchanged": 1}, {"conflict": 1})
    assert agreed["counts"] != {"update": 1}


def _sheet_row(person: str, year: int, month: int, **values) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": person,
        "year": year,
        "month": month,
        "status": "submitted",
        "submitted_at": "2092-08-01T08:00:00+00:00",
        "approved_by": None,
        "approved_at": None,
        "rejection_note": None,
        "pdf_hash": None,
        "created_at": "2092-07-01T08:00:00+00:00",
        **values,
    }


def _entry_row(sheet: dict, day: str, hours, description: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timesheet_id": sheet["id"],
        "work_date": day,
        "hours": hours,
        "project": None,
        "description": description,
        "source": "manual",
        "is_overtime_override": False,
        "override_reason": None,
        "override_by": None,
    }


@pytest.mark.asyncio
async def test_reimport_keeps_timesheet_approved_or_locked_in_nexus() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        worker, w_id, w_row = await make_person(db, f"{tag}-worker")
        other, o_id, o_row = await make_person(db, f"{tag}-other")
        admin, _, _ = await make_person(db, f"{tag}-admin", role=UserRole.admin)
        await db.commit()
    approved_here = _sheet_row(w_id, 2092, 7)
    locked_here = _sheet_row(o_id, 2092, 7)
    entries = [
        _entry_row(approved_here, "2092-07-01", 8, "Praca nad wdrożeniem"),
        _entry_row(locked_here, "2092-07-01", 8, "Praca nad wdrożeniem"),
    ]
    bundle = make_bundle(
        {
            "profiles": [w_row, o_row],
            "timesheets": [approved_here, locked_here],
            "timesheet_entries": entries,
        }
    )
    first = await _apply_bundle("time", bundle)
    assert first["counts"] == {"create": 2}

    async with AsyncSessionLocal() as db:
        sheet = await db.scalar(select(Timesheet).where(Timesheet.user_id == worker.id))
        actor = _ts_actor(await db.get(User, admin.id))
        await time_flow.approve(db, timesheet_id=sheet.id, actor=actor)
        await payroll_time_bridge.set_payroll_lock(db, 2092, 7, [other.id], locked=True)
        await db.commit()

    # W Compassie ktoś dopisał godziny — paczka różni się od NEXUSA.
    changed = make_bundle(
        {
            "profiles": [w_row, o_row],
            "timesheets": [approved_here, locked_here],
            "timesheet_entries": [
                *entries,
                _entry_row(approved_here, "2092-07-02", 8, "Dopisane później"),
                _entry_row(locked_here, "2092-07-02", 8, "Dopisane później"),
            ],
        }
    )
    plan = await _dry_run("time", changed)
    assert plan["counts"] == {"conflict": 2}
    assert plan["reasons"] == {
        time_import.CHANGED_IN_NEXUS: 1,
        time_import.LOCKED_IN_PAYROLL: 1,
    }
    await _apply_bundle("time", changed)
    async with AsyncSessionLocal() as db:
        sheets = {
            s.user_id: s
            for s in await db.scalars(
                select(Timesheet).where(Timesheet.user_id.in_([worker.id, other.id]))
            )
        }
        assert sheets[worker.id].status == "approved"
        assert sheets[worker.id].approved_by == admin.id
        assert sheets[other.id].payroll_locked is True
        counts = dict(
            (
                await db.execute(
                    select(TimesheetEntry.timesheet_id, func.count())
                    .where(
                        TimesheetEntry.timesheet_id.in_([s.id for s in sheets.values()])
                    )
                    .group_by(TimesheetEntry.timesheet_id)
                )
            ).all()
        )
        assert set(counts.values()) == {1}


# ── B6: urlop w zamkniętym miesiącu płac ─────────────────────────────────────


@pytest.mark.asyncio
async def test_leave_in_closed_payroll_month_warns_and_tells_payroll(
    app_client,
    modules_on,  # noqa: F811
) -> None:
    day = date(2092, 3, 4)  # wtorek
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "head_of_recruitment", profile=True)
        worker = await _user(
            db,
            "recruiter",
            profile=True,
            manager_user_id=boss.id,
            employment_type="uop",
        )
        finance = await _user(db, "recruiter")
        await _grant(db, finance, "payroll")
        sheet = Timesheet(
            user_id=worker.id,
            year=day.year,
            month=day.month,
            status="approved",
            payroll_locked=True,
        )
        db.add(sheet)
        await db.flush()
        db.add(
            TimesheetEntry(
                timesheet_id=sheet.id,
                work_date=day,
                hours=Decimal("8"),
                description="Praca",
            )
        )
        await db.commit()

    created = await app_client.post(
        f"{LEAVE}/requests",
        json=_body(start=day, end=day),
        headers=_headers(worker),
    )
    assert created.status_code == 201, created.text
    assert created.json()["payroll_locked_months"] == []
    assert created.json()["payroll_warning"] is None
    request_id = created.json()["id"]

    approved = await app_client.post(
        f"{LEAVE}/approvals/{request_id}/approve", json={}, headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["payroll_locked_months"] == ["2092-03"]
    assert "zamknięty" in approved.json()["payroll_warning"]

    async with AsyncSessionLocal() as db:
        bells = list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == finance.id,
                    Notification.notification_type
                    == NotificationType.hr_timesheet_decided,
                )
            )
        )
        assert len(bells) == 1
        assert bells[0].link == "/people/payroll/2092-03"
        # D6: Płace nie widzą rodzaju nieobecności.
        assert "wypoczynk" not in (bells[0].title + bells[0].message).lower()
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id == worker.id,
                    HrAuditEvent.action == "leave_in_closed_payroll_month",
                )
            )
        )
        assert [e.sensitivity for e in trail] == ["payroll"]
        assert trail[0].details["months"] == ["2092-03"]
        assert "leave_type" not in trail[0].details
        # Zamknięty miesiąc nietknięty: godziny zostają do korekty przez Płace.
        kept = await db.scalar(
            select(func.count())
            .select_from(TimesheetEntry)
            .where(TimesheetEntry.timesheet_id == sheet.id)
        )
        assert kept == 1

    cancelled = await app_client.post(
        f"{LEAVE}/requests/{request_id}/cancel", json={}, headers=_headers(worker)
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["payroll_locked_months"] == ["2092-03"]


# ── B7: zamknięcie miesiąca a równoległe akceptacje ──────────────────────────

CLOSE_TODAY = date(2026, 10, 16)


async def _cleanup_month(year: int, month: int, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        period = await db.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.year == year, PayrollPeriod.month == month
            )
        )
        if period is not None:
            await delete_settlement_rows(db, period.id)
            await db.execute(
                delete(PayrollLine).where(PayrollLine.period_id == period.id)
            )
            await db.delete(period)
        await db.execute(delete(HrBonus).where(HrBonus.recipient_user_id.in_(user_ids)))
        await db.execute(delete(Timesheet).where(Timesheet.user_id.in_(user_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_close_waits_for_running_timesheet_approval_and_counts_it() -> None:
    year, month = 2021, 2
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        finance = await _user(db, "recruiter")
        worker = await _user(db, "recruiter", profile=True, employment_type="uop")
        sheet = Timesheet(user_id=worker.id, year=year, month=month, status="submitted")
        db.add(sheet)
        await db.flush()
        db.add(
            TimesheetEntry(
                timesheet_id=sheet.id,
                work_date=date(year, month, 1),
                hours=Decimal("8"),
                description="Praca",
            )
        )
        await db.commit()
    try:
        approver = AsyncSessionLocal()
        actor = _ts_actor(await approver.get(User, admin.id))
        await time_flow.approve(approver, timesheet_id=sheet.id, actor=actor)

        async def close() -> None:
            async with AsyncSessionLocal() as db:
                await payroll_close.close_month(
                    db,
                    year=year,
                    month=month,
                    actor_id=finance.id,
                    acknowledge_warnings=True,
                    today=CLOSE_TODAY,
                )
                await db.commit()

        closing = asyncio.create_task(close())
        await asyncio.sleep(0.5)
        assert not closing.done()  # czeka na akceptację w toku
        await approver.commit()
        await approver.close()
        await asyncio.wait_for(closing, timeout=20)

        async with AsyncSessionLocal() as db:
            hours = await db.scalar(
                select(PayrollLine.hours)
                .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
                .where(
                    PayrollPeriod.year == year,
                    PayrollPeriod.month == month,
                    PayrollLine.user_id == worker.id,
                )
            )
            assert hours == Decimal("8")
    finally:
        await _cleanup_month(year, month, [worker.id])


@pytest.mark.asyncio
async def test_bonus_change_waits_for_running_close_and_is_refused() -> None:
    year, month = 2021, 3
    async with AsyncSessionLocal() as db:
        finance = await _user(db, "recruiter")
        worker = await _user(db, "recruiter", profile=True, employment_type="uop")
        bonus = HrBonus(
            recipient_user_id=worker.id,
            proposed_by=finance.id,
            amount=Decimal("500.00"),
            currency="PLN",
            category="custom",
            period_year=year,
            period_month=month,
            status="assigned",
            source="manual",
            assigned_by=finance.id,
            assigned_at=datetime.now(timezone.utc),
        )
        db.add(bonus)
        await db.commit()
    viewer = PayrollViewer(
        user_id=finance.id, payroll=True, admin=False, report_ids=frozenset()
    )
    try:
        closer = AsyncSessionLocal()
        await payroll_close.close_month(
            closer,
            year=year,
            month=month,
            actor_id=finance.id,
            acknowledge_warnings=True,
            today=CLOSE_TODAY,
        )

        async def cancel() -> str:
            async with AsyncSessionLocal() as db:
                try:
                    await payroll_bonuses.cancel_bonus(
                        db, viewer, bonus.id, note="Pomyłka"
                    )
                except PayrollConflict:
                    await db.rollback()
                    return "refused"
                await db.commit()
                return "cancelled"

        cancelling = asyncio.create_task(cancel())
        await asyncio.sleep(0.5)
        assert not cancelling.done()  # czeka na zamknięcie w toku
        await closer.commit()
        await closer.close()
        assert await asyncio.wait_for(cancelling, timeout=20) == "refused"
        async with AsyncSessionLocal() as db:
            assert (await db.get(HrBonus, bonus.id)).status == "assigned"
    finally:
        await _cleanup_month(year, month, [worker.id])


@pytest.mark.asyncio
async def test_timesheet_approval_after_close_is_refused_even_off_the_list() -> None:
    year, month = 2021, 4
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        finance = await _user(db, "recruiter")
        # Odeszła przed miesiącem — nie ma jej na liście płac, timesheet bez blokady.
        gone = await _user(
            db,
            "recruiter",
            profile=True,
            employment_status="exited",
            last_working_day=date(2021, 1, 29),
        )
        sheet = Timesheet(user_id=gone.id, year=year, month=month, status="submitted")
        db.add(sheet)
        await db.flush()
        db.add(
            TimesheetEntry(
                timesheet_id=sheet.id,
                work_date=date(year, month, 1),
                hours=Decimal("8"),
                description="Praca",
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            await payroll_close.close_month(
                db,
                year=year,
                month=month,
                actor_id=finance.id,
                acknowledge_warnings=True,
                today=CLOSE_TODAY,
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            actor = _ts_actor(await db.get(User, admin.id))
            with pytest.raises(TimeConflict):
                await time_flow.approve(db, timesheet_id=sheet.id, actor=actor)
            await db.rollback()
    finally:
        await _cleanup_month(year, month, [gone.id])


# ── B8: cofnięcie zakończenia a zamknięty miesiąc premii ─────────────────────


@pytest.mark.asyncio
async def test_undo_end_restores_bonus_whose_month_was_closed(
    payroll_on,  # noqa: F811
) -> None:
    world = await _placement(started_days_ago=3)
    await _reconcile(world["contract"])
    start = business_today() - timedelta(days=3)
    before = await _bonuses(world["contract"])
    period = (before["dl"].period_year, before["dl"].period_month)

    await _update_contract(
        world["contract"], status=ContractStatus.ended, end_date=start + timedelta(5)
    )
    ended = await _reconcile(world["contract"])
    assert ended["cancelled"] == 2

    # Płace zamknęły miesiąc premii, zanim ktoś cofnął zakończenie. Wiersz
    # okresu mógł już założyć automat (wybiera miesiąc pod blokadą okresu).
    async with AsyncSessionLocal() as db:
        closed = await payroll_periods.lock_period(db, *period)
        closed.status = "closed"
        closed.closed_at = datetime.now(timezone.utc)
        await db.commit()

    await _update_contract(
        world["contract"], status=ContractStatus.active, end_date=None
    )
    async with AsyncSessionLocal() as db:
        from app.models.contract import Contract

        contract = await db.get(Contract, world["contract"])
        undone = await placement_bonuses.on_contract_end_undone(db, contract)
        await db.commit()
    assert undone["restored"] == 2
    after = await _bonuses(world["contract"])
    shifted = add_months(period[0], period[1], 1)
    for bonus in after.values():
        assert bonus.status == "proposed"
        assert bonus.cancel_reason is None
        assert (bonus.period_year, bonus.period_month) == shifted
        assert bonus.rule_snapshot["restored_from_closed_period"] == (
            f"{period[0]}-{period[1]:02d}"
        )


# ── B9: nadgodziny przy pół dnia urlopu ──────────────────────────────────────


@pytest.mark.asyncio
async def test_half_day_leave_counts_four_hours_toward_overtime_everywhere() -> None:
    day = date(2092, 9, 9)  # wtorek
    async with AsyncSessionLocal() as db:
        try:
            worker = await _user(db, "recruiter", profile=True, employment_type="uop")
            profile = await db.scalar(
                select(EmployeeProfile).where(EmployeeProfile.user_id == worker.id)
            )
            request = LeaveRequest(
                id=uuid.uuid4(),
                user_id=worker.id,
                leave_type="vacation",
                status="approved",
                start_date=day,
                end_date=day,
                half_day="morning",
                paid_days=Decimal("0.5"),
                source="self",
            )
            db.add(request)
            await db.flush()
            db.add(
                LeaveRequestDay(
                    leave_request_id=request.id,
                    user_id=worker.id,
                    day=day,
                    fraction=Decimal("0.5"),
                    paid=True,
                    active=True,
                )
            )
            sheet = Timesheet(
                user_id=worker.id, year=day.year, month=day.month, status="approved"
            )
            db.add(sheet)
            await db.flush()
            db.add(
                TimesheetEntry(
                    timesheet_id=sheet.id,
                    work_date=day,
                    hours=Decimal("6"),
                    description="Praca nad wdrożeniem",
                    is_overtime=True,
                    overtime_reason="Wdrożenie u klienta po godzinach",
                )
            )
            await db.flush()

            view = await month_view(
                db,
                subject_user=worker,
                subject=profile,
                year=day.year,
                month=day.month,
                show_leave_type=True,
            )
            on_day = next(d for d in view["days"] if d["date"] == day.isoformat())
            assert on_day["overtime_hours"] == 2.0

            hours = await payroll_time_bridge.approved_hours(db, day.year, day.month)
            assert hours[worker.id].hours == Decimal("6")
            assert hours[worker.id].overtime_hours == Decimal("2")
        finally:
            await db.rollback()


# ── B10: dzień wolny firmy a złożone wnioski ─────────────────────────────────


@pytest.mark.asyncio
async def test_company_day_off_recounts_active_leave_both_ways(
    app_client,
    modules_on,  # noqa: F811
) -> None:
    mon = date(2093, 3, 9)  # poniedziałek
    fri = mon + timedelta(days=4)
    wed = mon + timedelta(days=2)
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        boss = await _user(db, "head_of_recruitment", profile=True)
        worker = await _user(
            db,
            "recruiter",
            profile=True,
            manager_user_id=boss.id,
            employment_type="uop",
        )
        waiting = await _user(
            db,
            "recruiter",
            profile=True,
            manager_user_id=boss.id,
            employment_type="b2b",
        )
        await db.commit()
    try:
        approved = await app_client.post(
            f"{LEAVE}/requests",
            json=_body(start=mon, end=fri),
            headers=_headers(worker),
        )
        assert approved.status_code == 201, approved.text
        approved_id = uuid.UUID(approved.json()["id"])
        decided = await app_client.post(
            f"{LEAVE}/approvals/{approved_id}/approve",
            json={},
            headers=_headers(boss),
        )
        assert decided.status_code == 200, decided.text
        pending = await app_client.post(
            f"{LEAVE}/requests",
            json=_body(start=wed, end=wed),
            headers=_headers(waiting),
        )
        assert pending.status_code == 201, pending.text
        pending_id = uuid.UUID(pending.json()["id"])

        async def ops_count() -> int:
            async with AsyncSessionLocal() as db:
                return int(
                    await db.scalar(
                        select(func.count())
                        .select_from(HrM365Operation)
                        .where(HrM365Operation.leave_request_id == approved_id)
                    )
                )

        ops_before = await ops_count()
        added = await app_client.post(
            DAYS_OFF,
            json={"day": wed.isoformat(), "name": "Dzień firmy", "kind": "company"},
            headers=_headers(admin),
        )
        assert added.status_code == 201, added.text

        async with AsyncSessionLocal() as db:
            request = await db.get(LeaveRequest, approved_id)
            assert request.paid_days == Decimal("4")
            days = list(
                await db.scalars(
                    select(LeaveRequestDay.day)
                    .where(LeaveRequestDay.leave_request_id == approved_id)
                    .order_by(LeaveRequestDay.day)
                )
            )
            assert wed not in days and len(days) == 4
            waiting_days = list(
                await db.scalars(
                    select(LeaveRequestDay.day).where(
                        LeaveRequestDay.leave_request_id == pending_id
                    )
                )
            )
            assert waiting_days == []
            bells = list(
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == worker.id,
                        Notification.message.contains("krótszy o 1 dzień"),
                    )
                )
            )
            assert len(bells) == 1
            trail = await db.scalar(
                select(func.count())
                .select_from(HrAuditEvent)
                .where(
                    HrAuditEvent.entity_id == str(approved_id),
                    HrAuditEvent.action == "leave_days_recounted",
                )
            )
            assert trail == 1
        assert await ops_count() == ops_before  # okno urlopu w M365 bez zmian

        removed = await app_client.delete(
            f"{DAYS_OFF}/{added.json()['id']}", headers=_headers(admin)
        )
        assert removed.status_code == 204, removed.text
        async with AsyncSessionLocal() as db:
            request = await db.get(LeaveRequest, approved_id)
            assert request.paid_days == Decimal("5")
            count = await db.scalar(
                select(func.count())
                .select_from(LeaveRequestDay)
                .where(
                    LeaveRequestDay.leave_request_id == approved_id,
                    LeaveRequestDay.active.is_(True),
                )
            )
            assert count == 5
            waiting_days = list(
                await db.scalars(
                    select(LeaveRequestDay.day).where(
                        LeaveRequestDay.leave_request_id == pending_id
                    )
                )
            )
            assert waiting_days == [wed]
            longer = await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == worker.id,
                    Notification.message.contains("dłuższy o 1 dzień"),
                )
            )
            assert longer == 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CompanyDayOff).where(CompanyDayOff.day == wed))
            await db.commit()


# ── D18: jedyna osoba z Kadr bez przełożonego ────────────────────────────────


@pytest.mark.asyncio
async def test_only_people_admin_without_manager_goes_to_admins(
    app_client,
    monkeypatch,
    modules_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter", profile=True, employment_type="uop")
        await _grant(db, hr, "people_admin")
        admin = await _user(db, "admin")
        await db.commit()

    async def only_hr(_db) -> list[int]:
        return [hr.id]

    monkeypatch.setattr(recipients, "people_admin_ids", only_hr)
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == hr.id)
        )
        approvers = (await recipients.supervisor_of(db, profile)).user_ids
    assert hr.id not in approvers
    assert admin.id in approvers

    created = await app_client.post(
        f"{LEAVE}/requests",
        json=_body(start=date(2093, 5, 4), end=date(2093, 5, 5)),
        headers=_headers(hr),
    )
    assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == admin.id,
                Notification.notification_type == NotificationType.hr_leave_requested,
            )
        )
    assert bell == 1
