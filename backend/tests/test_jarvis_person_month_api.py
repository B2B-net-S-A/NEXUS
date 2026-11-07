"""Jarvis ``person_month`` przez prawdziwą trasę „Akceptacji” (z bazą).

Finanse pytały Jarvisa o raport godzin osoby z kontem pracownika (06.11.2026),
a Jarvis miał tylko ``my_month``. Narzędzie czyta
``GET /api/hr/time/team/{user_id}/{year}/{month}`` z uprawnieniami pytającego:

* „Raporty godzin” (``timesheets``) dostają miesiąc każdej osoby, ale bez
  rodzaju nieobecności (D6) — trasa daje „Nieobecność”, a kształt narzędzia
  nie przepuszcza ani dni, ani notatek;
* rekruter bez uprawnień z grupy „Ludzie” dostaje odmowę trasy, a narzędzia
  w ogóle nie widzi;
* same „Płace” trasa nie wpuszcza (nie akceptują raportów), więc narzędzie
  też ich nie dostaje.

Miesiąc testowy: marzec 2031. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.services.hr.time_month import NEUTRAL_ABSENCE
from app.services.jarvis.tools import TOOLS_BY_NAME, render_result
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    grant,
    headers,
    make_user,
    time_on,
)

Y, M = 2031, 3
SICK_LABEL = "Zwolnienie lekarskie"


async def _worker_with_sick_day_and_hours(app_client):
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee")
        await add_leave(db, worker.id, [date(Y, M, 4)], leave_type="sick_leave")
        await db.commit()
    created = await app_client.post(
        f"/api/hr/time/me/{Y}/{M}/entries",
        json={
            "work_date": date(Y, M, 3).isoformat(),
            "hours": 8,
            "description": "Wizyta u klienta testowego",
        },
        headers=headers(worker),
    )
    assert created.status_code == 201, created.text
    return worker


def _route(worker_id: int) -> str:
    spec = TOOLS_BY_NAME["person_month"].build(
        {"user_id": worker_id, "year": Y, "month": M}
    )
    assert spec.method == "GET"
    return spec.path


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_timesheets_holder_reads_month_without_leave_type(app_client) -> None:
    worker = await _worker_with_sick_day_and_hours(app_client)
    async with AsyncSessionLocal() as db:
        holder = await make_user(db, "employee")
        await grant(db, holder, "timesheets")
        await db.commit()

    response = await app_client.get(_route(worker.id), headers=headers(holder))
    assert response.status_code == 200, response.text
    data = response.json()
    sick_day = next(d for d in data["days"] if d["date"] == f"{Y}-03-04")
    assert sick_day["leave"]["label"] == NEUTRAL_ABSENCE
    assert SICK_LABEL not in response.text

    shaped = TOOLS_BY_NAME["person_month"].shape(data, {"user_id": worker.id})
    assert shaped["user_id"] == worker.id
    assert shaped["totals"]["work_hours"] == 8
    rendered = render_result(shaped)
    for secret in (SICK_LABEL, "sick_leave", NEUTRAL_ABSENCE, "Wizyta u klienta"):
        assert secret not in rendered, secret


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_people_admin_route_shows_type_but_tool_drops_it(app_client) -> None:
    """Kontrola testu: Kadry widzą rodzaj w trasie, a do modelu i tak nie idzie."""

    worker = await _worker_with_sick_day_and_hours(app_client)
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "employee")
        await grant(db, hr, "people_admin")
        await db.commit()

    response = await app_client.get(_route(worker.id), headers=headers(hr))
    assert response.status_code == 200, response.text
    assert SICK_LABEL in response.text
    rendered = render_result(
        TOOLS_BY_NAME["person_month"].shape(response.json(), {"user_id": worker.id})
    )
    assert SICK_LABEL not in rendered


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_recruiter_and_payroll_alone_are_refused(app_client) -> None:
    worker = await _worker_with_sick_day_and_hours(app_client)
    async with AsyncSessionLocal() as db:
        recruiter = await make_user(db, "recruiter", profile=False)
        payroll = await make_user(db, "employee")
        await grant(db, payroll, "payroll")
        await db.commit()

    denied = await app_client.get(_route(worker.id), headers=headers(recruiter))
    assert denied.status_code == 403
    assert SICK_LABEL not in denied.text
    payroll_only = await app_client.get(_route(worker.id), headers=headers(payroll))
    assert payroll_only.status_code == 403
