"""Nieobecność ustawiona w Outlooku bez wniosku → wniosek (uzgadnianie o 7:00).

Na ``FakeMailboxOps`` (bez sieci): umowa o pracę dostaje wniosek do decyzji
przełożonego, B2B przyjęte zgłoszenie z informacją do koordynatora i Kadr;
bez operacji Microsoft 365, bez duplikatów, bez ponownego założenia po
odrzuceniu; autoodpowiedź bez dat zostaje tylko na liście Kadr; wyłączony
moduł urlopów niczego nie zakłada. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest_asyncio
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_leave import HrM365MailboxState, LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.services.hr.m365 import reconcile
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr.fakes import FakeMailboxOps
from tests.hr.m365_helpers import (
    at,
    make_leave,
    make_user,
    operations,
    reset_reconcile_runs,
)

D = date
MON, FRI = D(2026, 11, 16), D(2026, 11, 20)


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
    return previous


@pytest_asyncio.fixture
async def leave_on():
    previous = await _modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def leave_closed():
    previous = await _modules({**{key: True for key in HR_MODULE_KEYS}, "leave": False})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _own_oof(start: date, end: date) -> dict:
    """Własna autoodpowiedź osoby: od północy pierwszego dnia do północy po ostatnim."""

    return {
        "status": "scheduled",
        "scheduledStartDateTime": {
            "dateTime": f"{start.isoformat()}T00:00:00",
            "timeZone": "Europe/Warsaw",
        },
        "scheduledEndDateTime": {
            "dateTime": f"{date.fromordinal(end.toordinal() + 1).isoformat()}T00:00:00",
            "timeZone": "Europe/Warsaw",
        },
        "internalReplyMessage": "<p>Jestem na urlopie</p>",
        "externalReplyMessage": "<p>Jestem na urlopie</p>",
    }


async def _person(db, *, form: str, manager=None):
    user = await make_user(db, manager_user_id=manager.id if manager else None)
    await db.execute(
        update(EmployeeProfile)
        .where(EmployeeProfile.user_id == user.id)
        .values(employment_type=form)
    )
    await db.flush()
    return user


async def _requests(db, user_id: int) -> list[LeaveRequest]:
    rows = await db.scalars(
        select(LeaveRequest)
        .where(LeaveRequest.user_id == user_id)
        .order_by(LeaveRequest.start_date)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _bells(db, user_id: int, ntype: NotificationType) -> list[Notification]:
    rows = await db.scalars(
        select(Notification).where(
            Notification.user_id == user_id, Notification.notification_type == ntype
        )
    )
    return list(rows.all())


async def _run(db, fake, user_ids, day=MON, hour=7, minute=30):
    await reset_reconcile_runs(db)
    return await reconcile.run_once(
        db, ops=fake, mode="live", now=at(day, hour, minute), user_ids=user_ids
    )


async def test_uop_own_oof_becomes_pending_request_for_the_manager(leave_on) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        manager = await make_user(db)
        person = await _person(db, form="uop", manager=manager)
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))

        counts = await _run(db, fake, [person.id, manager.id])
        (request,) = await _requests(db, person.id)
        days = list(
            await db.scalars(
                select(LeaveRequestDay.day).where(
                    LeaveRequestDay.leave_request_id == request.id
                )
            )
        )
        bells = await _bells(db, manager.id, NotificationType.hr_leave_requested)
        ops = await operations(db, person.id)
        state = await db.get(HrM365MailboxState, person.id)

    assert counts["oof_request_created"] == 1
    assert request.status == "pending"
    assert request.source == "outlook_oof"
    assert request.leave_type == "vacation"
    assert request.created_by is None and request.decided_by is None
    assert (request.start_date, request.end_date) == (MON, FRI)
    assert request.note.startswith(
        "Wykryte z autoodpowiedzi w Outlooku (16.11–20.11.2026)"
    )
    assert len(days) == 5
    assert len(bells) == 1
    assert ops == []  # osoba ma własną autoodpowiedź — żadnych operacji M365
    assert state.custom_oof_detected is True
    assert fake.writes == []


async def test_b2b_own_oof_is_accepted_report_with_info_for_coordinator_and_hr(
    leave_on,
) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        coordinator = await make_user(db)
        person = await _person(db, form="b2b", manager=coordinator)
        kadry = await make_user(db, profile=False)
        db.add(
            UserActionOverride(user_id=kadry.id, action="people_admin", access="manage")
        )
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))

        await _run(db, fake, [person.id])
        (request,) = await _requests(db, person.id)
        coordinator_bells = await _bells(
            db, coordinator.id, NotificationType.hr_absence_reported
        )
        hr_bells = await _bells(db, kadry.id, NotificationType.hr_absence_reported)
        ops = await operations(db, person.id)

    assert request.status == "approved"
    assert request.decided_by is None and request.decided_at is not None
    assert "zgłoszenie przyjęte" in request.note
    assert len(coordinator_bells) == 1
    assert len(hr_bells) == 1
    assert "L4" not in hr_bells[0].message and "urlop" not in hr_bells[0].message
    assert ops == []


async def test_next_runs_do_not_duplicate_and_rejection_is_final(leave_on) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        manager = await make_user(db)
        person = await _person(db, form="uop", manager=manager)
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))

        await _run(db, fake, [person.id])
        again = await _run(db, fake, [person.id], day=D(2026, 11, 17))
        (request,) = await _requests(db, person.id)
        assert again.get("oof_request_created", 0) == 0
        assert again["custom_oof_covered"] == 1

        # Przełożony odrzuca — dni wniosku przestają być aktywne.
        await db.execute(
            update(LeaveRequest)
            .where(LeaveRequest.id == request.id)
            .values(status="rejected", decided_by=manager.id, decision_note="Nie")
        )
        await db.execute(
            update(LeaveRequestDay)
            .where(LeaveRequestDay.leave_request_id == request.id)
            .values(active=False)
        )
        await db.commit()
        after_reject = await _run(db, fake, [person.id], day=D(2026, 11, 18))
        rows = await _requests(db, person.id)

    assert after_reject.get("oof_request_created", 0) == 0
    assert [row.status for row in rows] == ["rejected"]


async def test_partly_covered_window_gets_only_the_missing_days(leave_on) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        person = await _person(db, form="uop")
        # Wniosek na środę — autoodpowiedź na cały tydzień.
        await make_leave(db, person, D(2026, 11, 18), D(2026, 11, 18))
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))

        await _run(db, fake, [person.id])
        rows = [r for r in await _requests(db, person.id) if r.source == "outlook_oof"]

    assert [(r.start_date, r.end_date) for r in rows] == [
        (D(2026, 11, 16), D(2026, 11, 17)),
        (D(2026, 11, 19), D(2026, 11, 20)),
    ]


async def test_oof_without_dates_and_closed_module_create_nothing(leave_on) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        person = await _person(db, form="uop")
        await db.commit()
        fake.set_oof(
            person.email,
            {"status": "alwaysEnabled", "internalReplyMessage": "<p>Mój</p>"},
        )
        counts = await _run(db, fake, [person.id])
        rows = await _requests(db, person.id)
        state = await db.get(HrM365MailboxState, person.id)

    assert rows == []
    assert counts["custom_oof_without_dates"] == 1
    assert state.custom_oof_detected is True  # zostaje na liście dla Kadr


async def test_closed_leave_module_creates_no_request(leave_closed) -> None:
    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        person = await _person(db, form="uop")
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))
        await _run(db, fake, [person.id])
        rows = await _requests(db, person.id)

    assert rows == []


async def test_approving_outlook_request_adds_no_m365_operations(
    leave_on, app_client
) -> None:
    from app.core.security import create_access_token

    fake = FakeMailboxOps()
    async with AsyncSessionLocal() as db:
        manager = await make_user(db)
        person = await _person(db, form="uop", manager=manager)
        await db.commit()
        fake.set_oof(person.email, _own_oof(MON, FRI))
        await _run(db, fake, [person.id])
        (request,) = await _requests(db, person.id)

    token = create_access_token(subject=manager.id, role=manager.role.value)
    response = await app_client.post(
        f"/api/hr/leave/approvals/{request.id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "outlook_oof"
    async with AsyncSessionLocal() as db:
        assert await operations(db, person.id) == []
