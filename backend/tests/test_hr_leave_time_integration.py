"""Urlop ↔ „Mój miesiąc” przez prawdziwe API obu modułów.

Akceptacja urlopu zdejmuje godziny z pełnych dni urlopu (hak
``time_hooks.on_leave_approved`` wołany z ``leave_service``), anulowanie
zatwierdzonego oddaje dni do pracy. Dane fikcyjne, daty w 2091.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.database import AsyncSessionLocal
from tests.test_hr_leave_api import MON, _body, _headers, _user, modules_on  # noqa: F401

TIME = "/api/hr/time"
LEAVE = "/api/hr/leave"


def _days(month_payload: dict) -> dict[str, dict]:
    return {day["date"]: day for day in month_payload["days"]}


@pytest.mark.asyncio
async def test_approved_leave_clears_hours_and_cancel_frees_the_day(
    app_client,
    modules_on,  # noqa: F811
) -> None:
    tue = MON + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "head_of_recruitment", profile=True)
        worker = await _user(
            db,
            "recruiter",
            profile=True,
            manager_user_id=boss.id,
            employment_type="uop",
        )
        await db.commit()

    for day in (MON, tue):
        added = await app_client.post(
            f"{TIME}/me/{MON.year}/{MON.month}/entries",
            json={"work_date": day.isoformat(), "hours": "8", "description": "Praca"},
            headers=_headers(worker),
        )
        assert added.status_code == 201, added.text

    created = await app_client.post(
        f"{LEAVE}/requests", json=_body(start=MON, end=MON), headers=_headers(worker)
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    approved = await app_client.post(
        f"{LEAVE}/approvals/{request_id}/approve", json={}, headers=_headers(boss)
    )
    assert approved.status_code == 200, approved.text

    month = await app_client.get(
        f"{TIME}/me/{MON.year}/{MON.month}", headers=_headers(worker)
    )
    assert month.status_code == 200, month.text
    days = _days(month.json())
    assert not days[MON.isoformat()]["entries"]
    assert [entry["hours"] for entry in days[tue.isoformat()]["entries"]] in (
        ["8"],
        ["8.00"],
        [8],
        [8.0],
    )

    cancelled = await app_client.post(
        f"{LEAVE}/approvals/{request_id}/cancel", json={}, headers=_headers(boss)
    )
    assert cancelled.status_code == 200, cancelled.text
    again = await app_client.post(
        f"{TIME}/me/{MON.year}/{MON.month}/entries",
        json={"work_date": MON.isoformat(), "hours": "8", "description": "Praca"},
        headers=_headers(worker),
    )
    assert again.status_code == 201, again.text
