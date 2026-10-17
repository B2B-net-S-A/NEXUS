"""Przypomnienie o timesheecie (``run_once``): okno 1.–5., kogo, raz na miesiąc.

Każdy test ma własny, odległy miesiąc — rezerwacje w ``hr_job_runs`` żyją
między testami tak samo jak na produkcji między przebiegami.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.models.hr_time import Timesheet
from app.services.hr import time_reminders
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    make_user,
    notifications_of,
    time_off,
    time_on,
)


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_outside_window_sends_nothing() -> None:
    async with AsyncSessionLocal() as db:
        result = await time_reminders.run_once(db, today=date(2032, 2, 6))
    assert result == {"status": "outside_window", "sent": 0}


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_reminder_reaches_every_role_with_timesheet_and_skips_leavers() -> None:
    async with AsyncSessionLocal() as db:
        # Compass pomijał przełożonych, Finanse i TCM — oni też prowadzą timesheet.
        manager = await make_user(db, "head_of_recruitment")
        finance = await make_user(db, "finance")
        tcm = await make_user(db, "talent_community_manager")
        submitted = await make_user(db, "employee")
        draft = await make_user(db, "employee")
        exited = await make_user(db, "employee", employment_status="exited")
        left_before = await make_user(
            db, "employee", last_working_day=date(2032, 3, 31)
        )
        starts_after = await make_user(db, "employee", work_start_date=date(2032, 5, 4))
        not_required = await make_user(db, "employee", timesheet_required=False)
        inactive = await make_user(db, "employee")
        inactive.is_active = False
        db.add(Timesheet(user_id=submitted.id, year=2032, month=4, status="submitted"))
        db.add(Timesheet(user_id=draft.id, year=2032, month=4, status="draft"))
        await db.commit()

    async with AsyncSessionLocal() as db:
        result = await time_reminders.run_once(db, today=date(2032, 5, 3))
    assert result["status"] == "ok"
    assert result["period"] == "2032-04"

    for person in (manager, finance, tcm, draft):
        bells = await notifications_of(person.id, "hr_timesheet_reminder")
        assert len(bells) == 1, person.role
        assert "kwiecień 2032" in bells[0][1]
        assert "5.05" in bells[0][1]
    for person in (
        submitted,
        exited,
        left_before,
        starts_after,
        not_required,
        inactive,
    ):
        assert await notifications_of(person.id, "hr_timesheet_reminder") == []

    # Drugi przebieg w oknie (np. restart przy nocnym wdrożeniu) — bez dubli.
    async with AsyncSessionLocal() as db:
        again = await time_reminders.run_once(db, today=date(2032, 5, 5))
    assert again["already"] >= 4
    for person in (manager, finance, tcm, draft):
        assert len(await notifications_of(person.id, "hr_timesheet_reminder")) == 1


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_january_reminds_about_december_of_previous_year() -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db, "recruiter")
        await db.commit()
    async with AsyncSessionLocal() as db:
        result = await time_reminders.run_once(db, today=date(2033, 1, 2))
    assert result["period"] == "2032-12"
    bells = await notifications_of(person.id, "hr_timesheet_reminder")
    assert bells and "grudzień 2032" in bells[0][1]


@pytest.mark.usefixtures("time_off")
@pytest.mark.asyncio
async def test_switched_off_module_sends_nothing() -> None:
    async with AsyncSessionLocal() as db:
        await make_user(db, "recruiter")
        await db.commit()
    async with AsyncSessionLocal() as db:
        result = await time_reminders.run_once(db, today=date(2034, 3, 2))
    assert result == {"status": "disabled"}
