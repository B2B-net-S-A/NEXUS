"""Zgłoszenie nieobecności a wysłany albo przyjęty raport godzin (17.10.2026).

Na B2B i zleceniu zgłoszenie wchodzi od razu, bez niczyjej decyzji (D5), a haki
godzin kasują ręczne godziny z dni nieobecności i liczą sumę kontrolną od nowa.
Zgłoszenie z datą wsteczną na dzień z raportu, który już leży u koordynatora
albo jest potwierdzony, przepisywało więc dokument bez niczyjej decyzji —
a koordynator nie mógł już zgłosić kolizji (409 „termin minął”) ani go cofnąć
(403). Decyzja koordynatora: takie zgłoszenie = 409, najpierw koordynator cofa
raport do szkicu. Umowa o pracę bez zmian (wniosek czeka na przełożonego).
Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.hr_leave import LeaveRequest
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.notification import Notification, NotificationType
from tests.test_hr_time_support import headers, make_user, time_on  # noqa: F401

Y, M = 2025, 3
D1, D2 = date(Y, M, 3), date(Y, M, 4)  # poniedziałek, wtorek


async def _sheet_with_hours(app_client, person, *, approve_by=None) -> dict:
    base = f"/api/hr/time/me/{Y}/{M}"
    for day in (D1, D2):
        added = await app_client.post(
            f"{base}/entries",
            json={"work_date": day.isoformat(), "hours": "8", "description": "Praca"},
            headers=headers(person),
        )
        assert added.status_code == 201, added.text
    sheet = await app_client.post(f"{base}/submit", headers=headers(person))
    assert sheet.status_code == 200, sheet.text
    if approve_by is None:
        return sheet.json()
    approved = await app_client.post(
        f"/api/hr/time/timesheets/{sheet.json()['id']}/approve",
        headers=headers(approve_by),
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _report(day: date = D1) -> dict:
    return {
        "leave_type": "vacation",
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
    }


async def _state(ts_id: int, user_id: int, boss_id: int):
    async with AsyncSessionLocal() as db:
        sheet = await db.get(Timesheet, ts_id)
        days = sorted(
            await db.scalars(
                select(TimesheetEntry.work_date).where(
                    TimesheetEntry.timesheet_id == ts_id
                )
            )
        )
        requests = await db.scalar(
            select(func.count(LeaveRequest.id)).where(LeaveRequest.user_id == user_id)
        )
        bells = await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == boss_id,
                Notification.notification_type == NotificationType.hr_absence_reported,
            )
        )
    return sheet, days, requests, bells


@pytest.mark.asyncio
async def test_backdated_b2b_report_on_confirmed_report_is_refused(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    approved = await _sheet_with_hours(app_client, person, approve_by=boss)

    expected = (
        "Raport godzin za marzec 2025 jest już potwierdzony. Żeby zgłosić "
        "przerwę w świadczeniu usług w tym miesiącu, koordynator musi najpierw "
        "cofnąć raport godzin do szkicu."
    )
    preview = await app_client.post(
        "/api/hr/leave/preview", json=_report(), headers=headers(person)
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["flow"] == "report"
    assert preview.json()["blocking_reason"] == expected

    created = await app_client.post(
        "/api/hr/leave/requests", json=_report(), headers=headers(person)
    )
    assert created.status_code == 409, created.text
    assert created.json()["detail"] == expected

    sheet, days, requests, bells = await _state(approved["id"], person.id, boss.id)
    assert sheet.status == "approved"
    assert sheet.pdf_hash == approved["pdf_hash"]
    assert days == [D1, D2]
    assert requests == 0
    assert bells == 0


@pytest.mark.asyncio
async def test_mandate_report_waits_until_coordinator_returns_confirmation(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="zlecenie", manager_user_id=boss.id
        )
        await db.commit()
    sent = await _sheet_with_hours(app_client, person)

    refused = await app_client.post(
        "/api/hr/leave/requests", json=_report(), headers=headers(person)
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == (
        "Potwierdzenie godzin za marzec 2025 jest już wysłane. Żeby zgłosić "
        "nieobecność w tym miesiącu, koordynator musi najpierw cofnąć "
        "potwierdzenie godzin do szkicu."
    )
    sheet, days, requests, _ = await _state(sent["id"], person.id, boss.id)
    assert (sheet.status, days, requests) == ("submitted", [D1, D2], 0)

    returned = await app_client.post(
        f"/api/hr/time/timesheets/{sent['id']}/return",
        json={"note": "Dopisz nieobecność z 3 marca"},
        headers=headers(boss),
    )
    assert returned.status_code == 200, returned.text

    created = await app_client.post(
        "/api/hr/leave/requests", json=_report(), headers=headers(person)
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "approved"
    sheet, days, requests, bells = await _state(sent["id"], person.id, boss.id)
    assert (sheet.status, days, requests, bells) == ("draft", [D2], 1, 1)


@pytest.mark.asyncio
async def test_report_spanning_two_months_names_each_sent_month(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="b2b", manager_user_id=boss.id
        )
        await db.commit()
    await _sheet_with_hours(app_client, person, approve_by=boss)
    april = "/api/hr/time/me/2025/4"
    added = await app_client.post(
        f"{april}/entries",
        json={"work_date": "2025-04-01", "hours": "8", "description": "Praca"},
        headers=headers(person),
    )
    assert added.status_code == 201, added.text
    assert (
        await app_client.post(f"{april}/submit", headers=headers(person))
    ).status_code == 200

    refused = await app_client.post(
        "/api/hr/leave/requests",
        json={
            "leave_type": "vacation",
            "start_date": "2025-03-31",
            "end_date": "2025-04-01",
        },
        headers=headers(person),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"].startswith(
        "Raport godzin za marzec 2025 jest już potwierdzony, a za kwiecień 2025 "
        "jest już wysłany."
    )


@pytest.mark.asyncio
async def test_uop_request_on_accepted_month_still_waits_for_supervisor(
    app_client,
    time_on,  # noqa: F811
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db, "employee", employment_type="uop", manager_user_id=boss.id
        )
        await db.commit()
    approved = await _sheet_with_hours(app_client, person, approve_by=boss)

    preview = await app_client.post(
        "/api/hr/leave/preview", json=_report(), headers=headers(person)
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["blocking_reason"] is None
    created = await app_client.post(
        "/api/hr/leave/requests", json=_report(), headers=headers(person)
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"
    sheet, days, _, _ = await _state(approved["id"], person.id, boss.id)
    assert (sheet.status, sheet.pdf_hash, days) == (
        "approved",
        approved["pdf_hash"],
        [D1, D2],
    )
