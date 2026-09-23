"""„X/dzień" w Wyścigu Rekomendacji (plan PR3, decyzja 23.09.2026).

Mianownik = dni robocze od 1. dnia miesiąca do dziś (polskie święta) minus
zatwierdzony urlop z COMPASSA, gdy go znamy. Bez COMPASSA plakietka dostaje
liczbę kalendarzową ze źródłem ``calendar`` (front: „bez urlopów"). Pola są
dopisywane do rankingu PO `_format`, nie do `extras` — nie mogą trafić do
zamrożonej historii.

Testy na żywym Postgresie: każdy zakłada WŁASNE konto, więc wiersze
`user_workday_periods` innych testów nie mają wpływu.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.user_workday_period import UserWorkdayPeriod
from app.services import competitions
from app.services.insights_workdays import race_workdays_to_date

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    user = User(
        email=f"race-perday-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("x"),
        name="Wyścig dzień",
        role=UserRole.recruiter,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _compass(user_id: int, start: date, end: date, *, working: float, absent: float):
    return UserWorkdayPeriod(
        user_id=user_id,
        period_start=start,
        period_end=end,
        business_days=int(working + absent),
        absence_days=absent,
        working_days=working,
    )


async def _attach(db, monkeypatch, *, today: date, period: str, rows: list[dict]):
    monkeypatch.setattr(competitions, "business_today", lambda: today)
    await competitions._attach_per_day(db, rows, period)
    return rows


async def test_first_business_day_of_month_counts_today(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        rows = [{"user_id": user.id, "verifications": 3}]
        await _attach(
            db, monkeypatch, today=date(2026, 9, 1), period="2026-09", rows=rows
        )
    assert rows[0]["workdays"] == 1.0
    assert rows[0]["workdays_source"] == "calendar"
    assert rows[0]["per_day"] == 3.0


async def test_first_of_month_on_a_holiday_gives_no_per_day(monkeypatch) -> None:
    """1 stycznia to święto — zero dni roboczych, a dzielenie przez zero nie jest oceną."""
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        rows = [{"user_id": user.id, "verifications": 2}]
        await _attach(
            db, monkeypatch, today=date(2026, 1, 1), period="2026-01", rows=rows
        )
    assert rows[0]["workdays"] == 0.0
    assert rows[0]["per_day"] is None
    assert rows[0]["workdays_source"] == "calendar"


async def test_public_holiday_mid_month_is_not_a_workday(monkeypatch) -> None:
    """11 listopada wypada w środę: 2–13.11.2026 to 9 dni roboczych, nie 10."""
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        rows = [{"user_id": user.id, "verifications": 36}]
        await _attach(
            db, monkeypatch, today=date(2026, 11, 13), period="2026-11", rows=rows
        )
    assert rows[0]["workdays"] == 9.0
    assert rows[0]["per_day"] == 4.0


async def test_without_compass_every_entry_gets_calendar_source(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        a, b = await _user(db), await _user(db)
        rows = [
            {"user_id": a.id, "verifications": 10},
            {"user_id": b.id, "verifications": 0},
        ]
        await _attach(
            db, monkeypatch, today=date(2026, 6, 5), period="2026-06", rows=rows
        )
    assert [r["workdays_source"] for r in rows] == ["calendar", "calendar"]
    # 1–5.06.2026: pon–pt, 4.06 Boże Ciało (czwartek) → 4 dni.
    assert [r["workdays"] for r in rows] == [4.0, 4.0]
    assert rows[1]["per_day"] == 0.0


async def test_closed_month_uses_compass_working_days() -> None:
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        db.add(
            _compass(user.id, date(2026, 8, 1), date(2026, 8, 31), working=15, absent=5)
        )
        await db.flush()
        out = await race_workdays_to_date(
            db,
            [user.id],
            month_start=date(2026, 8, 1),
            month_end=date(2026, 8, 31),
            today=date(2026, 9, 3),
            calendar_elapsed=20,
        )
        await db.rollback()
    assert out[user.id] == (15.0, "compass")


async def test_current_month_with_leave_falls_back_to_calendar() -> None:
    """Wiersz miesięczny opisuje CAŁY miesiąc — urlop może być dopiero przed nami.

    Odjęcie go od dni, które już minęły, zaniżałoby mianownik za dni, które
    jeszcze nie nadeszły. Plakietka dostaje więc kalendarz i dopisek „bez urlopów".
    """
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        db.add(
            _compass(user.id, date(2026, 9, 1), date(2026, 9, 30), working=17, absent=5)
        )
        await db.flush()
        out = await race_workdays_to_date(
            db,
            [user.id],
            month_start=date(2026, 9, 1),
            month_end=date(2026, 9, 30),
            today=date(2026, 9, 10),
            calendar_elapsed=8,
        )
        await db.rollback()
    assert out[user.id] == (8.0, "calendar")


async def test_current_month_without_leave_is_confirmed_by_compass() -> None:
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        db.add(
            _compass(user.id, date(2026, 9, 1), date(2026, 9, 30), working=22, absent=0)
        )
        await db.flush()
        out = await race_workdays_to_date(
            db,
            [user.id],
            month_start=date(2026, 9, 1),
            month_end=date(2026, 9, 30),
            today=date(2026, 9, 10),
            calendar_elapsed=8,
        )
        await db.rollback()
    assert out[user.id] == (8.0, "compass")


async def test_per_day_is_not_stored_in_extras(monkeypatch) -> None:
    """`extras` trafia do `frozen_snapshot` — mianownik zmienia się po fakcie."""
    ranked = competitions.RankedUser(
        user_id=1, name="x", metric_value=1, extras={"verifications": 4}
    )
    row = {**ranked.to_dict()}
    async with AsyncSessionLocal() as db:
        user = await _user(db)
        row["user_id"] = user.id
        await _attach(
            db, monkeypatch, today=date(2026, 9, 1), period="2026-09", rows=[row]
        )
    assert "per_day" in row
    assert "per_day" not in ranked.extras
    assert "workdays" not in ranked.extras
