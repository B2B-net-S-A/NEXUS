"""Audyt wydajności 17.10.2026: zbiorcze odczyty kolejki, licznika i salda.

Każda nowa funkcja zbiorcza daje TO SAMO co stara funkcja per wiersz/osoba:

* ``leave_service.pending_count`` == ``len(pending_queue)`` (przełożony, Kadry,
  zastępca nieobecnego przełożonego; zgłoszenia z B2B i zlecenia się nie liczą),
* ``leave_context.department_absences_many`` / ``work_summaries`` ==
  ``department_absences`` / ``work_in_period`` (bez listy wydarzeń) dla kilku
  wierszy z różnymi oknami,
* ``leave_balance.balances_for`` == ``balance_payload`` per osoba (UoP z pulą,
  B2B z pulą, zlecenie bez puli).

Dane fikcyjne, daty w 2091; każdy test kończy się rollbackiem.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.effective_access import resolve_effective_access
from app.services.hr import leave_balance, leave_context, leave_service

TODAY = date(2091, 11, 14)


async def _user(db, *, profile: bool = True, role: str = "recruiter", **values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"batch-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
        await db.flush()
    return user


async def _request(
    db, user: User, start: date, end: date, *, status: str, paid: bool = True, **extra
) -> LeaveRequest:
    request = LeaveRequest(
        id=uuid.uuid4(),
        user_id=user.id,
        leave_type=extra.pop("leave_type", "vacation"),
        status=status,
        start_date=start,
        end_date=end,
        source="self",
        **extra,
    )
    db.add(request)
    await db.flush()
    day = start
    while day <= end:
        if day.weekday() < 5:
            db.add(
                LeaveRequestDay(
                    leave_request_id=request.id,
                    user_id=user.id,
                    day=day,
                    fraction=Decimal("1.0"),
                    paid=paid,
                    active=status in ("pending", "approved"),
                )
            )
        day += timedelta(days=1)
    await db.flush()
    return request


@pytest.mark.asyncio
async def test_pending_count_equals_queue_length_for_manager_hr_and_stand_in() -> None:
    async with AsyncSessionLocal() as db:
        try:
            hr = await _user(db, profile=False)
            db.add(
                UserActionOverride(
                    user_id=hr.id, action="people_admin", access="manage"
                )
            )
            boss = await _user(db, employment_type="uop")
            stand_in = await _user(db, employment_type="uop")
            first = await _user(db, employment_type="uop", manager_user_id=boss.id)
            second = await _user(db, employment_type="uop", manager_user_id=boss.id)
            contractor = await _user(db, employment_type="b2b", manager_user_id=boss.id)
            await db.flush()
            # Przełożony na urlopie dziś — zastępca widzi kolejkę jego ludzi.
            await _request(
                db,
                boss,
                TODAY - timedelta(days=1),
                TODAY + timedelta(days=3),
                status="approved",
                substitute_user_id=stand_in.id,
            )
            await _request(
                db, first, date(2091, 12, 3), date(2091, 12, 4), status="pending"
            )
            await _request(
                db, second, date(2091, 12, 10), date(2091, 12, 10), status="pending"
            )
            # Zgłoszenie z B2B (D5) — od razu zatwierdzone, poza licznikiem.
            await _request(
                db, contractor, date(2091, 12, 3), date(2091, 12, 5), status="approved"
            )
            await resolve_effective_access(db, [hr, boss, stand_in])

            for actor in (boss, stand_in, hr):
                queue = await leave_service.pending_queue(db, actor=actor, today=TODAY)
                count = await leave_service.pending_count(db, actor=actor, today=TODAY)
                # Lista ma limit 300 wierszy, licznik — nie.
                assert min(count, 300) == len(queue), actor
            mine = await leave_service.pending_count(db, actor=boss, today=TODAY)
            assert mine == 2
            assert (
                await leave_service.pending_count(db, actor=stand_in, today=TODAY) == 2
            )
            outsider = await _user(db, employment_type="uop")
            assert (
                await leave_service.pending_count(db, actor=outsider, today=TODAY) == 0
            )
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_batched_queue_context_equals_per_row_context() -> None:
    department = f"Dział batch {uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        try:
            person = await _user(db, department=department)
            colleague = await _user(db, department=department)
            other = await _user(db, department=department)
            elsewhere = await _user(db, department=f"{department} inny")
            gone = await _user(db, department=department, employment_status="exited")
            await _request(
                db, colleague, date(2091, 11, 19), date(2091, 11, 23), status="approved"
            )
            await _request(
                db, other, date(2091, 12, 4), date(2091, 12, 5), status="pending"
            )
            await _request(
                db, elsewhere, date(2091, 11, 19), date(2091, 11, 19), status="approved"
            )
            await _request(
                db, gone, date(2091, 11, 20), date(2091, 11, 20), status="approved"
            )
            # Własna nieobecność osoby w oknie nie liczy się do „nieobecnych z działu”.
            await _request(
                db, person, date(2091, 11, 30), date(2091, 11, 30), status="approved"
            )
            for when, kind in (
                (
                    datetime(2091, 11, 19, 9, tzinfo=timezone.utc),
                    EventType.client_interview,
                ),
                (
                    datetime(2091, 11, 20, 22, 30, tzinfo=timezone.utc),
                    EventType.screening,
                ),
                (
                    datetime(2091, 12, 1, 10, tzinfo=timezone.utc),
                    EventType.client_interview,
                ),
                (datetime(2091, 12, 1, 12, tzinfo=timezone.utc), EventType.prep_call),
            ):
                db.add(
                    CalendarEvent(
                        title="Rozmowa testowa",
                        event_type=kind,
                        start_time=when,
                        status=EventStatus.scheduled,
                        created_by=person.id,
                        operational_owner_id=person.id,
                    )
                )
            await db.flush()

            windows = [
                leave_context.RequestWindow(
                    person.id, department, date(2091, 11, 19), date(2091, 11, 21)
                ),
                leave_context.RequestWindow(
                    person.id, department, date(2091, 11, 28), date(2091, 12, 5)
                ),
                leave_context.RequestWindow(
                    colleague.id, department, date(2091, 11, 17), date(2091, 12, 5)
                ),
                leave_context.RequestWindow(
                    person.id, None, date(2091, 11, 19), date(2091, 11, 19)
                ),
                leave_context.RequestWindow(
                    elsewhere.id,
                    f"{department} inny",
                    date(2091, 11, 1),
                    date(2091, 11, 30),
                ),
            ]
            absent = await leave_context.department_absences_many(db, windows)
            work = await leave_context.work_summaries(db, windows)
            for index, window in enumerate(windows):
                assert absent[index] == await leave_context.department_absences(
                    db,
                    user_id=window.user_id,
                    department=window.department,
                    start=window.start,
                    end=window.end,
                ), index
                single = await leave_context.work_in_period(
                    db, user_id=window.user_id, start=window.start, end=window.end
                )
                assert work[index] == {
                    "total": single["total"],
                    "by_kind": single["by_kind"],
                }, index
            # Okna naprawdę się różnią (test nie porównuje samych pustych list).
            assert [len(rows) for rows in absent] == [1, 1, 2, 0, 0]
            assert [item["total"] for item in work] == [2, 2, 0, 1, 0]
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_team_balances_equal_single_balances() -> None:
    today = date(2091, 6, 15)
    async with AsyncSessionLocal() as db:
        try:
            uop = await _user(db, employment_type="uop")
            b2b = await _user(db, employment_type="b2b")
            mandate = await _user(db, employment_type="zlecenie")
            empty = await _user(db, employment_type="b2b")
            db.add_all(
                [
                    LeaveEntitlement(
                        user_id=uop.id,
                        year=2091,
                        entitlement_days=Decimal("26"),
                        carried_over_days=Decimal("2"),
                        used_initial_days=Decimal("3"),
                    ),
                    LeaveEntitlement(
                        user_id=b2b.id, year=2091, entitlement_days=Decimal("10")
                    ),
                ]
            )
            await db.flush()
            await _request(
                db, uop, date(2091, 3, 5), date(2091, 3, 7), status="approved"
            )
            await _request(
                db, uop, date(2091, 8, 6), date(2091, 8, 8), status="approved"
            )
            await _request(
                db, uop, date(2091, 9, 3), date(2091, 9, 3), status="pending"
            )
            await _request(
                db,
                uop,
                date(2091, 4, 3),
                date(2091, 4, 3),
                status="approved",
                leave_type="on_demand",
            )
            await _request(
                db,
                uop,
                date(2091, 5, 2),
                date(2091, 5, 2),
                status="approved",
                leave_type="childcare",
                paid=False,
            )
            await _request(
                db, b2b, date(2091, 2, 6), date(2091, 2, 10), status="approved"
            )
            await _request(
                db,
                b2b,
                date(2091, 7, 2),
                date(2091, 7, 3),
                status="approved",
                paid=False,
            )
            await _request(
                db,
                mandate,
                date(2091, 1, 9),
                date(2091, 1, 11),
                status="approved",
                paid=False,
            )
            await _request(
                db,
                mandate,
                date(2091, 10, 1),
                date(2091, 10, 2),
                status="approved",
                paid=False,
            )
            # Dzień z poprzedniego roku nie wchodzi do salda 2091.
            await _request(
                db, b2b, date(2090, 12, 28), date(2090, 12, 28), status="approved"
            )

            forms = {
                uop.id: "uop",
                b2b.id: "b2b",
                mandate.id: "zlecenie",
                empty.id: "b2b",
            }
            batch = await leave_balance.balances_for(db, forms, year=2091, today=today)
            assert set(batch) == set(forms)
            for user_id, form in forms.items():
                single = await leave_balance.balance_payload(
                    db, user_id=user_id, year=2091, employment_type=form, today=today
                )
                assert batch[user_id] == single, form
            assert batch[uop.id]["remaining_days"] == "17.0"
            assert batch[mandate.id]["has_pool"] is False
            assert batch[mandate.id]["planned_days"] == "2.0"
            assert (
                await leave_balance.balances_for(db, {}, year=2091, today=today) == {}
            )
        finally:
            await db.rollback()
