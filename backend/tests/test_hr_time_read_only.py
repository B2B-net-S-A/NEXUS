"""„Mój miesiąc”: odczyt niczego nie zapisuje (fala poprawek 17.10.2026).

Do 17.10.2026 ``GET /api/hr/time/me/{rok}/{miesiąc}`` zakładał timesheet
i auto-wpisy płatnej puli kontraktora przy samym otwarciu miesiąca (kształt
z Compassa) — każde przejrzenie przyszłego miesiąca tworzyło szkic, a odczyt
brał blokadę wiersza. Teraz odczyt liczy widok bez zapisu („wirtualny”
szkic), a wiersz powstaje przy pierwszym zapisie (wpis, „Wypełnij miesiąc”,
wysyłka) — z tymi samymi auto-wpisami co dotąd. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.hr_time import Timesheet, TimesheetEntry
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    add_leave,
    headers,
    make_user,
    time_on,
)

Y, M = 2095, 6
BASE = f"/api/hr/time/me/{Y}/{M}"
FULL, HALF = date(Y, M, 6), date(Y, M, 7)


async def _rows(user_id: int) -> tuple[int, list[tuple[str, str, float]]]:
    async with AsyncSessionLocal() as db:
        sheets = await db.scalar(
            select(func.count(Timesheet.id)).where(Timesheet.user_id == user_id)
        )
        entries = (
            await db.execute(
                select(
                    TimesheetEntry.work_date,
                    TimesheetEntry.source,
                    TimesheetEntry.hours,
                )
                .join(Timesheet, Timesheet.id == TimesheetEntry.timesheet_id)
                .where(Timesheet.user_id == user_id)
                .order_by(TimesheetEntry.work_date, TimesheetEntry.id)
            )
        ).all()
    return int(sheets or 0), [(d.isoformat(), s, float(h)) for d, s, h in entries]


async def _contractor() -> object:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type="b2b")
        await add_leave(db, worker.id, [FULL])
        await add_leave(db, worker.id, [HALF], fraction=0.5)
        await db.commit()
    return worker


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_reading_a_month_writes_nothing_but_shows_the_paid_pool(
    app_client,
) -> None:
    worker = await _contractor()
    h = headers(worker)
    for _ in range(2):
        response = await app_client.get(BASE, headers=h)
        assert response.status_code == 200, response.text
    assert await _rows(worker.id) == (0, [])

    view = response.json()
    assert view["timesheet"] is None
    by_day = {day["date"]: day for day in view["days"]}
    assert by_day[FULL.isoformat()]["hours"] == 8
    assert by_day[FULL.isoformat()]["entries"] == []
    assert by_day[HALF.isoformat()]["hours"] == 4
    assert view["totals"]["leave_paid_hours"] == 12
    working = [day for day in view["days"] if day["working_day"]]
    # Dni z płatną pulą nie są „brakującymi” — wpisze je pierwszy zapis.
    assert view["totals"]["days_missing"] == len(working) - 2


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_first_write_creates_the_timesheet_with_the_same_auto_entries(
    app_client,
) -> None:
    worker = await _contractor()
    h = headers(worker)
    before = (await app_client.get(BASE, headers=h)).json()
    created = await app_client.post(
        f"{BASE}/entries",
        json={
            "work_date": date(Y, M, 8).isoformat(),
            "hours": 8,
            "description": "Praca nad rekrutacjami",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    sheets, entries = await _rows(worker.id)
    assert sheets == 1
    assert entries == [
        (FULL.isoformat(), "leave_paid", 8.0),
        (HALF.isoformat(), "leave_paid", 4.0),
        (date(Y, M, 8).isoformat(), "manual", 8.0),
    ]
    after = (await app_client.get(BASE, headers=h)).json()
    assert after["totals"]["leave_paid_hours"] == before["totals"]["leave_paid_hours"]
    full = next(day for day in after["days"] if day["date"] == FULL.isoformat())
    assert [(e["source"], e["hours"]) for e in full["entries"]] == [("leave_paid", 8.0)]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_month_of_paid_pool_alone_can_be_sent_without_opening_it(
    app_client,
) -> None:
    """Wysyłka jest pierwszym zapisem: szkic z auto-wpisami powstaje w niej."""

    worker = await _contractor()
    sent = await app_client.post(f"{BASE}/submit", headers=headers(worker))
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "submitted"
    sheets, entries = await _rows(worker.id)
    assert sheets == 1
    assert [source for _, source, _ in entries] == ["leave_paid", "leave_paid"]


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_empty_month_still_cannot_be_sent_and_leaves_no_row(app_client) -> None:
    async with AsyncSessionLocal() as db:
        worker = await make_user(db, "employee", employment_type="uop")
        await db.commit()
    sent = await app_client.post(f"{BASE}/submit", headers=headers(worker))
    assert sent.status_code == 422
    assert "co najmniej jeden wpis" in sent.json()["detail"]
    assert await _rows(worker.id) == (0, [])
