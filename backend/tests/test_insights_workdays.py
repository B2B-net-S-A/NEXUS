"""Zaciąganie dni roboczych z COMPASSA (D5) — kontrakt prywatności i mianownika.

Trzy rzeczy pod ochroną, każda z konkretnym kosztem przy złamaniu:
1. do NEXUSA trafiają WYŁĄCZNIE liczby dni — nigdy typ nieobecności ani notatka
   (`sick_leave`/`parental_leave` to dane o zdrowiu, `note` to wolny tekst medyczny),
2. brak danych o osobie NIE daje wartości domyślnej — podstawienie stałej to
   dokładnie ten defekt, dla którego cały ten moduł powstał,
3. niedopasowani są RAPORTOWANI w obie strony, nie pomijani po cichu.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.user_workday_period import UserWorkdayPeriod
from app.services import insights_workdays


async def _seed_user(email: str, active: bool = True) -> int:
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"WD {uuid.uuid4().hex[:6]}",
            password_hash=hash_password("T3st_workdays!x0"),
            role=UserRole.recruiter,
            is_active=active,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


@pytest.mark.asyncio
async def test_sync_writes_only_day_counts(monkeypatch):
    """Nawet gdy COMPASS przyśle więcej, do bazy trafiają same liczby dni."""
    email = f"wd-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    user_id = await _seed_user(email)

    async def fake_fetch(date_from, date_to, bucket="month"):
        return {
            "basis": "business_days_minus_approved_leave",
            "people": [
                {
                    "email": email,
                    "period_start": "2026-08-01",
                    "period_end": "2026-08-31",
                    "business_days": 21,
                    "absence_days": 2.5,
                    "working_days": 18.5,
                    # Gdyby kiedykolwiek zaczęły przychodzić — nie mogą wylądować w bazie.
                    "leave_type": "sick_leave",
                    "note": "zabieg w szpitalu",
                }
            ],
        }

    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_URL", "http://x")
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_SECRET", "s")
    monkeypatch.setattr(insights_workdays, "fetch_workdays", fake_fetch)

    async with AsyncSessionLocal() as db:
        result = await insights_workdays.sync_workdays(
            db, date(2026, 8, 1), date(2026, 8, 1)
        )
        assert result.rows_written == 1
        assert result.matched_users == 1

        from sqlalchemy import select

        row = (
            await db.execute(
                select(UserWorkdayPeriod).where(UserWorkdayPeriod.user_id == user_id)
            )
        ).scalar_one()

        assert float(row.working_days) == 18.5
        assert float(row.absence_days) == 2.5
        assert row.business_days == 21
        # Model NIE MA gdzie tego zapisać — i to jest zabezpieczenie, nie przypadek.
        assert not hasattr(row, "leave_type")
        assert not hasattr(row, "note")


@pytest.mark.asyncio
async def test_unmatched_are_reported_in_both_directions(monkeypatch):
    """Cicho pominięty niedopasowany daje mianownik, który wygląda kompletnie."""
    known = f"wd-known-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    await _seed_user(known)
    ghost = f"wd-ghost-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"

    async def fake_fetch(date_from, date_to, bucket="month"):
        return {
            "basis": "business_days_minus_approved_leave",
            "people": [
                {
                    "email": ghost,
                    "period_start": "2026-08-01",
                    "period_end": "2026-08-31",
                    "business_days": 21,
                    "absence_days": 0,
                    "working_days": 21,
                }
            ],
        }

    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_URL", "http://x")
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_SECRET", "s")
    monkeypatch.setattr(insights_workdays, "fetch_workdays", fake_fetch)

    async with AsyncSessionLocal() as db:
        result = await insights_workdays.sync_workdays(
            db, date(2026, 8, 1), date(2026, 8, 1)
        )

    assert ghost in result.unmatched_compass_emails
    assert known in result.nexus_users_without_compass
    payload = result.as_payload()
    assert payload["unmatched_compass_emails"]
    assert payload["nexus_users_without_compass"]


@pytest.mark.asyncio
async def test_basis_mismatch_aborts_instead_of_writing(monkeypatch):
    """Rozjazd znaczenia liczby jest gorszy niż jej brak.

    UI podpisałoby ją etykietą, której źródło już nie potwierdza.
    """

    async def fake_fetch(date_from, date_to, bucket="month"):
        return {"basis": "hours_worked", "people": []}

    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_URL", "http://x")
    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_SECRET", "s")
    monkeypatch.setattr(insights_workdays, "fetch_workdays", fake_fetch)

    async with AsyncSessionLocal() as db:
        result = await insights_workdays.sync_workdays(
            db, date(2026, 8, 1), date(2026, 8, 1)
        )
    assert result.error and "basis_mismatch" in result.error
    assert result.rows_written == 0


@pytest.mark.asyncio
async def test_disabled_switch_never_reaches_the_network(monkeypatch):
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("nie powinno wyjść na sieć")

    monkeypatch.setattr(insights_workdays.settings, "COMPASS_WORKDAYS_ENABLED", False)
    monkeypatch.setattr(insights_workdays, "fetch_workdays", boom)

    async with AsyncSessionLocal() as db:
        result = await insights_workdays.sync_workdays(
            db, date(2026, 8, 1), date(2026, 8, 1)
        )
    assert result.error == "disabled"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_missing_person_has_no_default_denominator():
    """Brak wpisu = brak klucza. Żadnej wartości domyślnej."""
    user_id = await _seed_user(f"wd-none-{uuid.uuid4().hex[:8]}@b2bnetwork.pl")
    async with AsyncSessionLocal() as db:
        got = await insights_workdays.working_days_for(
            db, [user_id], date(1999, 1, 1), date(1999, 1, 31)
        )
    assert got == {}
