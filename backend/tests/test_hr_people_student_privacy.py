"""Przełożony widzi znacznik „student”, ale nie daty: koniec zwolnienia ze
składek (z niej da się policzyć wiek), „składki od”, staż i zaświadczenie ZUS
to sprawy osoby, Kadr i Płac (przegląd bezpieczeństwa 17.10.2026, D8–D9).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    headers,
    make_user,
    time_on,
)

HR_ONLY = (
    "contribution_exempt_until",
    "contributions_from",
    "leave_seniority_years",
    "zus_certificate_received_on",
)


async def _pair():
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead")
        student = await make_user(
            db,
            "recruiter",
            employment_type="zlecenie",
            manager_user_id=boss.id,
            student_contribution_exempt=True,
            contribution_exempt_until=date(2091, 6, 30),
        )
        await db.commit()
    return boss, student


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_manager_sees_the_student_flag_but_not_the_dates(app_client) -> None:
    boss, student = await _pair()

    card = await app_client.get(f"/api/hr/people/{student.id}", headers=headers(boss))
    assert card.status_code == 200, card.text
    assert card.json()["scope"] == "full"
    assert card.json()["student_contribution_exempt"] is True
    assert not set(HR_ONLY) & set(card.json())

    listing = await app_client.get("/api/hr/people", headers=headers(boss))
    row = next(i for i in listing.json()["items"] if i["user_id"] == student.id)
    assert not set(HR_ONLY) & set(row)

    team = await app_client.get("/api/hr/team", headers=headers(boss))
    assert team.status_code == 200, team.text
    member = next(p for p in team.json()["people"] if p["user_id"] == student.id)
    assert member["student"] is True
    assert "contributions_from" not in member


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_the_person_sees_own_dates(app_client) -> None:
    _, student = await _pair()

    own = await app_client.get(f"/api/hr/people/{student.id}", headers=headers(student))
    assert own.status_code == 200, own.text
    assert own.json()["contribution_exempt_until"] == "2091-06-30"
    assert own.json()["contributions_from"] == "2091-07-01"
