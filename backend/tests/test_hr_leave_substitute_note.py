"""Zastępca nieobecnego przełożonego nie widzi notatki wniosku (D6) — także
w odpowiedzi trasy, która zwraca jeden wiersz po decyzji albo kolizji.

Przegląd bezpieczeństwa 17.10.2026: kolejka maskowała notatkę, a odpowiedź
``/conflict``, ``/approve`` i ``/reject`` oddawała ją w całości.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_leave import LeaveRequest
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    headers,
    make_user,
    time_on,
)

BASE = "/api/hr/leave"
MON = date(2091, 11, 12)
FRI = date(2091, 11, 16)
SECRET = "Notatka tylko dla przełożonego i Kadr"


def _body(**extra) -> dict:
    return {
        "leave_type": "vacation",
        "start_date": MON.isoformat(),
        "end_date": FRI.isoformat(),
        **extra,
    }


async def _team(form: str):
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead")
        stand_in = await make_user(db, "recruiter")
        worker = await make_user(
            db, "recruiter", employment_type=form, manager_user_id=boss.id
        )
        db.add(
            LeaveRequest(
                id=uuid.uuid4(),
                user_id=boss.id,
                leave_type="vacation",
                status="approved",
                start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=3),
                substitute_user_id=stand_in.id,
                source="self",
                created_by=boss.id,
            )
        )
        await db.commit()
    return boss, stand_in, worker


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_substitute_does_not_get_the_note_back_from_conflict(app_client) -> None:
    boss, stand_in, worker = await _team("b2b")
    created = await app_client.post(
        BASE + "/requests", json=_body(note=SECRET), headers=headers(worker)
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    # Kolejka: zastępca nie widzi notatki (stan sprzed poprawki — zielony).
    pending = await app_client.get(
        BASE + "/approvals/pending", headers=headers(stand_in)
    )
    assert pending.status_code == 200, pending.text
    reported = [i for i in pending.json()["reported"] if i["id"] == rid]
    assert reported, pending.json()
    assert reported[0]["note"] is None

    resp = await app_client.post(
        f"{BASE}/{rid}/conflict",
        json={"note": "koliduje z projektem"},
        headers=headers(stand_in),
    )
    assert resp.status_code == 200
    assert resp.json().get("note") is None
    assert resp.json()["as_substitute_for"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_substitute_does_not_get_the_note_back_from_approve(app_client) -> None:
    boss, stand_in, worker = await _team("uop")
    created = await app_client.post(
        BASE + "/requests", json=_body(note=SECRET), headers=headers(worker)
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    resp = await app_client.post(
        f"{BASE}/approvals/{rid}/approve", headers=headers(stand_in)
    )
    assert resp.status_code == 200
    assert resp.json().get("note") is None
