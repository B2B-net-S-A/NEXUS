"""Kalendarz zespołu: praca zdalna i delegacja z wyjątków obecności.

Tylko wiersze ``attendance_days`` (zdalnie, delegacja), bez dnia w biurze
i bez notatki; bez modułu czasu nic się nie pokazuje. Dane fikcyjne, 2093.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.core.database import AsyncSessionLocal
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import AttendanceDay
from app.models.user import User, UserRole
from app.services.hr.leave_calendar import team_calendar
from app.services.hr.leave_policy import Actor


async def _person(db) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"presence-{marker}@example.com",
        name=f"Osoba Obecność {marker}",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, department=f"Dział {marker}"))
    await db.flush()
    return user


async def test_calendar_shows_remote_and_business_trip_without_notes() -> None:
    async with AsyncSessionLocal() as db:
        person = await _person(db)
        db.add_all(
            [
                AttendanceDay(
                    user_id=person.id,
                    day=date(2093, 3, 2),
                    status="active",
                    location="remote",
                    note="z domu, hydraulik",
                ),
                AttendanceDay(
                    user_id=person.id,
                    day=date(2093, 3, 3),
                    status="business_trip",
                    location=None,
                ),
                AttendanceDay(
                    user_id=person.id,
                    day=date(2093, 3, 4),
                    status="active",
                    location="onsite",
                ),
            ]
        )
        await db.commit()
        viewer = Actor(user_id=-1)
        shown = await team_calendar(
            db,
            viewer=viewer,
            year=2093,
            month=3,
            today=date(2093, 3, 1),
            with_presence=True,
        )
        hidden = await team_calendar(
            db, viewer=viewer, year=2093, month=3, today=date(2093, 3, 1)
        )

    row = next(p for p in shown["people"] if p["user_id"] == person.id)
    assert shown["presence_shown"] is True
    assert row["presence"] == [
        {"date": "2093-03-02", "kind": "remote"},
        {"date": "2093-03-03", "kind": "business_trip"},
    ]
    assert "hydraulik" not in str(shown)
    row_hidden = next(p for p in hidden["people"] if p["user_id"] == person.id)
    assert hidden["presence_shown"] is False
    assert row_hidden["presence"] == []
