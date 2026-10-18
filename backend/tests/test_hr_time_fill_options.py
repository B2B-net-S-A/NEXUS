"""„Wypełnij miesiąc” z oknem (luka z Compassa, 18.10.2026).

Godziny dziennie (domyślnie 8, najwyżej 8), opis z szablonu albo domyślny
roli, „nadpisz istniejące wpisy” bez ruszania auto-wpisów płatnej puli.
Część bez bazy: walidacja godzin. Miesiąc testowy: marzec 2031 (21 dni
roboczych, bez świąt). Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.services.hr import time_fill
from app.services.hr.time_entries import TimeError
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    headers,
    make_user,
    time_on,
)

Y, M = 2031, 3
BASE = f"/api/hr/time/me/{Y}/{M}"


def test_fill_hours_default_and_limits():
    assert time_fill.fill_hours(None) == Decimal("8")
    assert time_fill.fill_hours(Decimal("6.5")) == Decimal("6.50")
    for bad in (Decimal("0"), Decimal("-1"), Decimal("8.25"), Decimal("12")):
        with pytest.raises(TimeError):
            time_fill.fill_hours(bad)
    with pytest.raises(TimeError, match="nadgodziny"):
        time_fill.fill_hours(Decimal("9"))


async def _worker(**profile):
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        worker = await make_user(db, "employee", manager_user_id=boss.id, **profile)
        await db.commit()
    return worker


async def _days(app_client, worker) -> dict[str, dict]:
    month = (await app_client.get(BASE, headers=headers(worker))).json()
    return {day["date"]: day for day in month["days"]}


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_fill_with_hours_per_day_and_half_day_leave(app_client) -> None:
    worker = await _worker(employment_type="uop")
    async with AsyncSessionLocal() as db:
        await add_leave(db, worker.id, [date(Y, M, 5)], fraction=0.5)
        await db.commit()
    h = headers(worker)
    filled = await app_client.post(
        f"{BASE}/fill",
        json={"hours_per_day": 6, "project": "Beta", "description": "Wdrożenie"},
        headers=h,
    )
    assert filled.status_code == 200, filled.text
    body = filled.json()
    assert body["inserted"] == 21 and body["hours_per_day"] == 6
    assert body["removed"] == 0
    days = await _days(app_client, worker)
    assert days["2031-03-03"]["hours"] == 6
    assert days["2031-03-03"]["entries"][0]["project"] == "Beta"
    # Pół dnia urlopu: zostaje 4 h, wypełnianie nie robi nadgodzin.
    assert days["2031-03-05"]["hours"] == 4
    too_much = await app_client.post(
        f"{BASE}/fill", json={"hours_per_day": 9}, headers=h
    )
    assert too_much.status_code == 422


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_overwrite_replaces_entries_but_keeps_paid_pool(app_client) -> None:
    worker = await _worker(employment_type="b2b")
    async with AsyncSessionLocal() as db:
        # Płatny dzień puli B2B = auto-wpis `leave_paid`, którego nikt nie kasuje.
        await add_leave(db, worker.id, [date(Y, M, 6)])
        await db.commit()
    h = headers(worker)
    manual = await app_client.post(
        f"{BASE}/entries",
        json={"work_date": "2031-03-03", "hours": 3, "description": "Szkolenie"},
        headers=h,
    )
    assert manual.status_code == 201, manual.text
    template = await app_client.post(
        "/api/hr/time/me/templates",
        json={
            "name": "Projekt Gamma",
            "description": "Gamma: rozwój",
            "project": "Gamma",
        },
        headers=h,
    )
    assert template.status_code == 201, template.text

    kept = await app_client.post(f"{BASE}/fill", json={}, headers=h)
    assert kept.status_code == 200
    assert kept.json()["skipped_existing"] == 1
    days = await _days(app_client, worker)
    assert days["2031-03-03"]["hours"] == 3

    replaced = await app_client.post(
        f"{BASE}/fill",
        json={"overwrite": True, "template_id": template.json()["id"]},
        headers=h,
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    # 19 dni z poprzedniego wypełnienia + 1 ręczny; auto-wpis 6.03 zostaje.
    assert body["removed"] == 20
    assert body["inserted"] == 20
    assert body["description"] == "Gamma: rozwój" and body["project"] == "Gamma"
    days = await _days(app_client, worker)
    assert days["2031-03-03"]["hours"] == 8
    assert days["2031-03-03"]["entries"][0]["description"] == "Gamma: rozwój"
    paid = days["2031-03-06"]["entries"]
    assert [entry["source"] for entry in paid] == ["leave_paid"]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_template_crud_is_per_person(app_client) -> None:
    worker = await _worker()
    other = await _worker()
    h = headers(worker)
    created = await app_client.post(
        "/api/hr/time/me/templates",
        json={"name": "Code review", "description": "Przegląd kodu", "sort_order": 2},
        headers=h,
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    duplicate = await app_client.post(
        "/api/hr/time/me/templates",
        json={"name": "Code review", "description": "Inny opis"},
        headers=h,
    )
    assert duplicate.status_code == 422
    foreign = await app_client.patch(
        f"/api/hr/time/me/templates/{template_id}",
        json={"name": "Cudzy"},
        headers=headers(other),
    )
    assert foreign.status_code == 404
    moved = await app_client.patch(
        f"/api/hr/time/me/templates/{template_id}",
        json={"sort_order": 0, "description": "Przegląd kodu i testy"},
        headers=h,
    )
    assert moved.status_code == 200
    assert moved.json()["sort_order"] == 0
    listed = (await app_client.get("/api/hr/time/me/templates", headers=h)).json()
    assert [item["name"] for item in listed["items"]] == ["Code review"]
    removed = await app_client.delete(
        f"/api/hr/time/me/templates/{template_id}", headers=h
    )
    assert removed.status_code == 204
