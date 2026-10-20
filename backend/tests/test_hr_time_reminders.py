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
    grant,
    headers,
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


# ── „Przypomnij” z ekranu (Płace, Akceptacje) ─────────────────────────────────


def _remind_url(user_id: int, year: int, month: int) -> str:
    return f"/api/hr/time/remind/{user_id}/{year}/{month}"


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_manual_reminder_goes_to_person_once_a_day(app_client) -> None:
    async with AsyncSessionLocal() as db:
        finance = await make_user(db, "recruiter", profile=False)
        await grant(db, finance, "payroll")
        person = await make_user(db, "employee", employment_type="b2b")
        await db.commit()

    first = await app_client.post(
        _remind_url(person.id, 2035, 3), headers=headers(finance)
    )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "target": "person",
        "status": "missing",
        "sent": True,
        "already_today": False,
    }
    bells = await notifications_of(person.id, "hr_timesheet_reminder")
    assert len(bells) == 1
    # Słowa formy (B2B = raport godzin), miesiąc i termin.
    assert "raport godzin" in bells[0][0]
    assert "marzec 2035" in bells[0][1] and "5.04" in bells[0][1]

    again = await app_client.post(
        _remind_url(person.id, 2035, 3), headers=headers(finance)
    )
    assert again.status_code == 200
    assert again.json()["already_today"] is True
    assert again.json()["sent"] is False
    assert len(await notifications_of(person.id, "hr_timesheet_reminder")) == 1


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_manual_reminder_for_submitted_goes_to_the_approver(app_client) -> None:
    async with AsyncSessionLocal() as db:
        finance = await make_user(db, "recruiter", profile=False)
        await grant(db, finance, "payroll")
        boss = await make_user(db, "recruiter", employment_type="uop")
        person = await make_user(
            db, "employee", manager_user_id=boss.id, employment_type="uop"
        )
        db.add(Timesheet(user_id=person.id, year=2035, month=4, status="submitted"))
        await db.commit()

    sent = await app_client.post(
        _remind_url(person.id, 2035, 4), headers=headers(finance)
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["target"] == "approver"
    assert sent.json()["status"] == "submitted"
    bells = await notifications_of(boss.id, "hr_timesheet_submitted")
    assert len(bells) == 1
    assert bells[0][0].startswith("Przypomnienie")
    assert "kwiecień 2035" in bells[0][1]
    assert await notifications_of(person.id, "hr_timesheet_reminder") == []

    # Przełożony nie ponagla sam siebie.
    own = await app_client.post(_remind_url(person.id, 2035, 4), headers=headers(boss))
    assert own.status_code == 409
    assert "Akceptacje" in own.json()["detail"]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_manual_reminder_refusals(app_client) -> None:
    async with AsyncSessionLocal() as db:
        stranger = await make_user(db, "recruiter")
        boss = await make_user(db, "recruiter")
        person = await make_user(db, "employee", manager_user_id=boss.id)
        other = await make_user(db, "employee")
        no_report = await make_user(
            db, "employee", manager_user_id=boss.id, timesheet_required=False
        )
        db.add(Timesheet(user_id=person.id, year=2035, month=5, status="approved"))
        await db.commit()

    # Bez Płac, Kadr i bez ludzi do akceptacji — bramka.
    denied = await app_client.post(
        _remind_url(person.id, 2035, 6), headers=headers(stranger)
    )
    assert denied.status_code == 403
    # Przełożony spoza zespołu osoby — 404 (bez zdradzania, że jest).
    outside = await app_client.post(
        _remind_url(other.id, 2035, 6), headers=headers(boss)
    )
    assert outside.status_code == 404
    # Przyjęty raport i osoba bez obowiązku raportu — 409.
    approved = await app_client.post(
        _remind_url(person.id, 2035, 5), headers=headers(boss)
    )
    assert approved.status_code == 409
    exempt = await app_client.post(
        _remind_url(no_report.id, 2035, 6), headers=headers(boss)
    )
    assert exempt.status_code == 409
    # Przełożony przypomina swojemu człowiekowi o szkicu.
    ok = await app_client.post(_remind_url(person.id, 2035, 6), headers=headers(boss))
    assert ok.status_code == 200
    assert ok.json()["target"] == "person"


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_manual_reminder_refuses_closed_payroll_month_without_timesheet(
    app_client,
) -> None:
    """Audyt 21.10.2026: brak timesheetu w miesiącu zamkniętym w płacach to też
    409 — założonego tam raportu i tak nie da się wypełnić (``payroll_locked``)."""

    from sqlalchemy import delete

    from app.core.scheduling import local_now
    from app.models.hr_payroll import PayrollPeriod

    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        person = await make_user(db, "employee", manager_user_id=boss.id)
        db.add(
            PayrollPeriod(year=2035, month=7, status="closed", closed_at=local_now())
        )
        await db.commit()
    try:
        closed = await app_client.post(
            _remind_url(person.id, 2035, 7), headers=headers(boss)
        )
        assert closed.status_code == 409, closed.text
        assert "zamknięty w płacach" in closed.json()["detail"]
        assert await notifications_of(person.id, "hr_timesheet_reminder") == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PayrollPeriod).where(
                    PayrollPeriod.year == 2035, PayrollPeriod.month == 7
                )
            )
            await db.commit()
