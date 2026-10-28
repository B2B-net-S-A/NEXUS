"""Dni pracy osoby — staty i cele liczone bez dni nieobecności (28.10.2026).

Pierwsza część to czyste funkcje (bez bazy). Druga zakłada fikcyjne osoby
i nieobecności na Postgresie, każdy test kończy się rollbackiem.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services import competitions, person_workdays
from app.services.hr import availability_local
from app.services.insights_workdays import race_workdays_to_date
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import WARSAW, period_dates, target_on_workdays
from app.services.person_workdays import (
    business_days,
    prorated_target,
    worked_days,
)

OCT_1 = date(2026, 10, 1)
OCT_28 = date(2026, 10, 28)
OCT_31 = date(2026, 10, 31)


# ── Czyste funkcje ──────────────────────────────────────────────────────────


def test_business_days_skip_weekends_and_holidays() -> None:
    # Październik 2026 do 28.: 20 dni roboczych (1.10 to czwartek).
    assert len(business_days(OCT_1, OCT_28)) == 20
    # 11.11 (Święto Niepodległości) w środę nie jest dniem roboczym.
    assert date(2026, 11, 11) not in business_days(
        date(2026, 11, 9), date(2026, 11, 13)
    )


def test_worked_days_subtract_absence_on_business_days_only() -> None:
    business = business_days(OCT_1, OCT_28)
    absence = {
        date(2026, 10, 1): 1.0,
        date(2026, 10, 2): 1.0,
        date(2026, 10, 3): 1.0,  # sobota — nic nie odejmuje
        date(2026, 10, 5): 0.5,
    }
    assert worked_days(business, absence) == 17.5


def test_worked_days_never_go_below_zero_and_cap_a_day_at_one() -> None:
    business = [date(2026, 10, 1)]
    assert worked_days(business, {date(2026, 10, 1): 1.5}) == 0.0
    assert worked_days([], {}) == 0.0


@pytest.mark.parametrize(
    ("target", "business", "worked", "expected"),
    [
        (4, 20, 15, 3),  # 3.0 dokładnie — nie 4 przez błąd zmiennoprzecinkowy
        (4, 20, 16, 4),  # 3.2 → w górę
        (2, 22, 22, 2),  # bez nieobecności bez zmian
        (5, 5, 0, 0),  # cały tydzień nieobecności
        (3, 0, 0, 3),  # okres bez dni roboczych — bez proporcji
        (0, 20, 10, 0),
    ],
)
def test_prorated_target(
    target: int, business: int, worked: float, expected: int
) -> None:
    assert prorated_target(target, business, worked) == expected


# Środa 28.10.2026, południe w Warszawie.
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=WARSAW)


def test_period_dates_cover_the_whole_period() -> None:
    assert period_dates(KpiPeriod.day, NOW) == (OCT_28, OCT_28)
    assert period_dates(KpiPeriod.week, NOW) == (date(2026, 10, 26), date(2026, 11, 1))
    assert period_dates(KpiPeriod.month, NOW) == (OCT_1, OCT_31)


def test_kpi_target_follows_workdays_of_the_period() -> None:
    two_days_off = {date(2026, 10, 26): 1.0, date(2026, 10, 27): 1.0}
    assert target_on_workdays(20, KpiPeriod.week, NOW, two_days_off) == 12
    assert target_on_workdays(4, KpiPeriod.day, NOW, {OCT_28: 1.0}) == 0
    assert target_on_workdays(4, KpiPeriod.day, NOW, {OCT_28: 0.5}) == 2
    assert target_on_workdays(80, KpiPeriod.month, NOW, {}) == 80


# ── Na bazie ────────────────────────────────────────────────────────────────


async def _person(db, tag: str) -> User:
    user = User(
        email=f"workdays-{tag}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Osoba {tag}",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _absence(
    db,
    user: User,
    start: date,
    end: date,
    *,
    status: str = "approved",
    fraction: float = 1.0,
) -> None:
    leave_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO leave_requests (id, user_id, leave_type, status, start_date,
                end_date, half_day, decided_at)
            VALUES (:id, :user_id, 'vacation', :status, :start, :end, :half_day,
                :decided_at)
            """
        ),
        {
            "id": leave_id,
            "user_id": user.id,
            "status": status,
            "start": start,
            "end": end,
            "half_day": "morning" if fraction < 1 else None,
            "decided_at": datetime.now(timezone.utc),
        },
    )
    day = start
    while day <= end:
        if day.weekday() < 5:
            await db.execute(
                text(
                    """
                    INSERT INTO leave_request_days (leave_request_id, user_id, day,
                        fraction, paid, active)
                    VALUES (:leave_id, :user_id, :day, :fraction, false, :active)
                    """
                ),
                {
                    "leave_id": leave_id,
                    "user_id": user.id,
                    "day": day,
                    "fraction": fraction,
                    "active": status in ("pending", "approved"),
                },
            )
        day += timedelta(days=1)


@pytest.fixture
def local_source():
    availability_local.reset_source_cache(local=True)
    yield
    availability_local.reset_source_cache(local=False)


@pytest.mark.asyncio
async def test_approved_absence_reduces_workdays(local_source) -> None:
    async with AsyncSessionLocal() as db:
        away = await _person(db, "away")
        pending = await _person(db, "pending")
        present = await _person(db, "present")
        await _absence(db, away, date(2026, 10, 1), date(2026, 10, 7))
        await _absence(
            db, pending, date(2026, 10, 1), date(2026, 10, 7), status="pending"
        )
        days = await person_workdays.workdays_by_user(
            db, [away.id, pending.id, present.id], OCT_1, OCT_28
        )
        await db.rollback()
    assert days == {away.id: 15.0, pending.id: 20.0, present.id: 20.0}


@pytest.mark.asyncio
async def test_without_nexus_absences_everyone_has_full_business_days() -> None:
    availability_local.reset_source_cache(local=False)
    async with AsyncSessionLocal() as db:
        away = await _person(db, "compass")
        await _absence(db, away, date(2026, 10, 1), date(2026, 10, 7))
        days = await person_workdays.workdays_by_user(db, [away.id], OCT_1, OCT_28)
        await db.rollback()
    assert days == {away.id: 20.0}


@pytest.mark.asyncio
async def test_monthly_target_scales_with_planned_absence(local_source) -> None:
    async with AsyncSessionLocal() as db:
        away = await _person(db, "target")
        present = await _person(db, "full")
        # 22 dni robocze października; 11 dni nieobecności = połowa miesiąca.
        await _absence(db, away, date(2026, 10, 16), date(2026, 10, 30))
        targets = await person_workdays.prorated_targets(
            db, {away.id: 2, present.id: 2}, OCT_1, OCT_31
        )
        await db.rollback()
    assert targets == {away.id: 1, present.id: 2}


@pytest.mark.asyncio
async def test_race_per_day_counts_only_workdays_in_current_month(local_source) -> None:
    async with AsyncSessionLocal() as db:
        away = await _person(db, "race")
        half = await _person(db, "half")
        await _absence(db, away, date(2026, 10, 1), date(2026, 10, 7))
        await _absence(db, half, date(2026, 10, 14), date(2026, 10, 14), fraction=0.5)
        # Nieobecność po „dziś” nie zmniejsza dni, które już upłynęły.
        await _absence(db, half, date(2026, 10, 29), date(2026, 10, 30))
        denominators = await race_workdays_to_date(
            db,
            [away.id, half.id],
            month_start=OCT_1,
            month_end=OCT_31,
            today=OCT_28,
            calendar_elapsed=20,
        )
        await db.rollback()
    assert denominators == {away.id: (15.0, "nexus"), half.id: (19.5, "nexus")}


@pytest.mark.asyncio
async def test_race_threshold_is_per_person(local_source, monkeypatch) -> None:
    """Próg „4 × dni” liczy się z dni pracy osoby, nie z kalendarza."""
    monkeypatch.setattr(competitions, "business_today", lambda: OCT_28)
    async with AsyncSessionLocal() as db:
        away = await _person(db, "threshold")
        await _absence(db, away, date(2026, 10, 1), date(2026, 10, 7))
        required = await competitions.required_verifications_by_user(
            db, [away.id], year=2026, month=10, per_day=4, today=OCT_28
        )
        await db.rollback()
    assert required == {away.id: 60}


@pytest.mark.asyncio
async def test_my_panel_targets_follow_workdays(local_source) -> None:
    """Panel „Moje KPI” pokazuje te same cele co „/me/today” — bez dni nieobecności."""
    from app.services.kpi_panel import compute_my_panel

    async with AsyncSessionLocal() as db:
        away = await _person(db, "panel")
        present = await _person(db, "panel-full")
        await _absence(db, away, OCT_1, OCT_31)
        away_panel = await compute_my_panel(db, user=away, now=NOW)
        full_panel = await compute_my_panel(db, user=present, now=NOW)
        await db.rollback()
    assert away_panel.target_verifications_daily == 0
    assert away_panel.target_placements_monthly == 0
    assert full_panel.target_verifications_daily > 0
