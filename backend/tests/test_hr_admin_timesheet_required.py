"""Hurtowa flaga „Składa raport godzin” z katalogu (18.10.2026).

``POST /api/hr/admin/profiles/timesheet-required`` — Kadry i admin, ślad
``profile_updated`` per zmieniona osoba, brak kartoteki = 404 bez zmian,
osoba z „nie” wypada z przypomnienia 1.–5. Dane fikcyjne.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.services.hr import time_reminders
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

PATH = "/api/hr/admin/profiles/timesheet-required"


async def _flags(user_ids: list[int]) -> dict[int, bool]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(EmployeeProfile.user_id, EmployeeProfile.timesheet_required).where(
                EmployeeProfile.user_id.in_(user_ids)
            )
        )
        return {user_id: flag for user_id, flag in rows.all()}


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_hr_sets_the_flag_for_many_people_with_a_trail(app_client) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        first = await make_user(db, "employee", employment_type="b2b")
        second = await make_user(db, "employee", employment_type="b2b")
        already = await make_user(db, "employee", timesheet_required=False)
        await db.commit()
    ids = [first.id, second.id, already.id]
    response = await app_client.post(
        PATH, json={"user_ids": ids, "required": False}, headers=headers(hr)
    )
    assert response.status_code == 200, response.text
    assert sorted(response.json()["changed"]) == sorted([first.id, second.id])
    assert response.json()["unchanged"] == [already.id]
    assert await _flags(ids) == {first.id: False, second.id: False, already.id: False}
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id.in_(ids),
                    HrAuditEvent.action == "profile_updated",
                )
            )
        )
    assert {event.subject_user_id for event in trail} == {first.id, second.id}
    assert all(
        event.details["fields"] == ["timesheet_required"]
        and event.details["source"] == "directory"
        and event.actor_user_id == hr.id
        for event in trail
    )

    back = await app_client.post(
        PATH, json={"user_ids": [first.id], "required": True}, headers=headers(hr)
    )
    assert back.status_code == 200
    assert (await _flags([first.id]))[first.id] is True


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_only_hr_and_admin_and_missing_profile_changes_nothing(
    app_client,
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        worker = await make_user(db, "employee", manager_user_id=boss.id)
        admin = await make_user(db, "admin", profile=False)
        no_profile = await make_user(db, "recruiter", profile=False)
        await db.commit()
    body = {"user_ids": [worker.id], "required": False}
    for refused in (boss, worker):
        denied = await app_client.post(PATH, json=body, headers=headers(refused))
        assert denied.status_code == 403
    missing = await app_client.post(
        PATH,
        json={"user_ids": [worker.id, no_profile.id], "required": False},
        headers=headers(admin),
    )
    assert missing.status_code == 404
    assert (await _flags([worker.id]))[worker.id] is True
    empty = await app_client.post(
        PATH, json={"user_ids": [], "required": False}, headers=headers(admin)
    )
    assert empty.status_code == 422
    ok = await app_client.post(PATH, json=body, headers=headers(admin))
    assert ok.status_code == 200
    assert ok.json()["changed"] == [worker.id]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_person_without_report_gets_no_reminder(app_client) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        contractor = await make_user(
            db, "employee", employment_type="b2b", employment_status="active"
        )
        colleague = await make_user(
            db, "employee", employment_type="uop", employment_status="active"
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        before = await time_reminders.eligible_user_ids(db, 2031, 3)
    assert {contractor.id, colleague.id} <= set(before)
    switched = await app_client.post(
        PATH,
        json={"user_ids": [contractor.id], "required": False},
        headers=headers(hr),
    )
    assert switched.status_code == 200
    async with AsyncSessionLocal() as db:
        due = set(await time_reminders.eligible_user_ids(db, 2031, 3))
    assert contractor.id not in due and colleague.id in due
