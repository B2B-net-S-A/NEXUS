"""Sprawdzenie fragmentów (kopia w kontenerze): zastępca przez API timesheetów."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from tests.test_hr_leave_substitute import _team
from tests.test_hr_time_support import headers, make_user, time_on  # noqa: F401


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_substitute_timesheet_api(app_client) -> None:
    boss, stand_in, worker = await _team()
    async with AsyncSessionLocal() as db:
        other_boss = await make_user(db, "delivery_lead")
        other = await make_user(db, "employee", manager_user_id=other_boss.id)
        await db.commit()
    ids = {}
    for person in (worker, other):
        base = "/api/hr/time/me/2031/3"
        await app_client.post(
            f"{base}/entries",
            json={"work_date": "2031-03-03", "hours": 8, "description": "Sourcing"},
            headers=headers(person),
        )
        sent = await app_client.post(f"{base}/submit", headers=headers(person))
        ids[person.id] = sent.json()["id"]
    team = await app_client.get("/api/hr/time/team/2031/3", headers=headers(stand_in))
    assert team.status_code == 200, team.text
    names = {item["user_id"] for item in team.json()["items"]}
    assert worker.id in names and other.id not in names
    month = await app_client.get(
        f"/api/hr/time/team/{worker.id}/2031/3", headers=headers(stand_in)
    )
    assert month.status_code == 200, month.text
    ok = await app_client.post(
        f"/api/hr/time/timesheets/{ids[worker.id]}/approve", headers=headers(stand_in)
    )
    assert ok.status_code == 200, ok.text
    denied = await app_client.post(
        f"/api/hr/time/timesheets/{ids[other.id]}/approve", headers=headers(stand_in)
    )
    assert denied.status_code == 404
    async with AsyncSessionLocal() as db:
        trace = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.action == "timesheet_approved",
                HrAuditEvent.subject_user_id == worker.id,
            )
        )
    assert trace.details["as_substitute_for_user_id"] == boss.id
