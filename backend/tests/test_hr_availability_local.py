"""Dostępność, dni robocze i tempo celów z urlopów NEXUSA (krok 6).

Lokalne źródło oddaje ten sam kontrakt co Compass: snapshot przechodzi
walidację ``AvailabilitySnapshot``, zastępstwo rozstrzyga się jak dotąd,
a wiersze dni roboczych mają kształt odpowiedzi ``/api/internal/workdays``.
Dane fikcyjne; każdy test kończy się rollbackiem.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_profile import CompanyDayOff, EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import availability_local as local
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import expected_progress_ratio
from app.services.workforce_availability import (
    AvailabilitySnapshot,
    resolve_workforce,
)

WARSAW = ZoneInfo("Europe/Warsaw")
# Środa, dzień roboczy bez świąt — snapshot liczony „na ten dzień”.
WEDNESDAY = date(2026, 10, 21)


def _noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=WARSAW)


async def _person(db, tag: str, role: UserRole = UserRole.recruiter) -> User:
    user = User(
        email=f"avail-{tag}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Osoba {tag}",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, employment_type="uop"))
    await db.flush()
    return user


async def _leave(
    db,
    user: User,
    start: date,
    end: date,
    *,
    status: str = "approved",
    half_day: str | None = None,
    substitute: User | None = None,
    decider: User | None = None,
) -> None:
    leave_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO leave_requests (id, user_id, leave_type, status, start_date,
                end_date, half_day, substitute_user_id, decided_by, decided_at)
            VALUES (:id, :user_id, 'vacation', :status, :start, :end, :half_day,
                :substitute, :decider, :decided_at)
            """
        ),
        {
            "id": leave_id,
            "user_id": user.id,
            "status": status,
            "start": start,
            "end": end,
            "half_day": half_day,
            "substitute": substitute.id if substitute else None,
            "decider": decider.id if decider else None,
            "decided_at": datetime.now(timezone.utc) if decider else None,
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
                    VALUES (:leave_id, :user_id, :day, :fraction, true, :active)
                    """
                ),
                {
                    "leave_id": leave_id,
                    "user_id": user.id,
                    "day": day,
                    "fraction": 0.5 if half_day else 1.0,
                    "active": status in ("pending", "approved"),
                },
            )
        day += timedelta(days=1)


@pytest.mark.asyncio
async def test_snapshot_validates_and_delegates_to_the_substitute() -> None:
    async with AsyncSessionLocal() as db:
        try:
            boss = await _person(db, "boss", UserRole.head_of_recruitment)
            away = await _person(db, "away")
            cover = await _person(db, "cover")
            half = await _person(db, "half")
            pending = await _person(db, "pending")
            await _leave(
                db,
                away,
                WEDNESDAY - timedelta(days=2),
                WEDNESDAY + timedelta(days=2),
                substitute=cover,
                decider=boss,
            )
            await _leave(
                db, half, WEDNESDAY, WEDNESDAY, half_day="morning", decider=boss
            )
            await _leave(db, pending, WEDNESDAY, WEDNESDAY, status="pending")

            raw = await local.build_local_snapshot(db, _noon(WEDNESDAY))
            snapshot = AvailabilitySnapshot.model_validate(raw)
            people = {person.email: person for person in snapshot.people}

            assert snapshot.working_day is True
            assert people[away.email].available is False
            (absence,) = people[away.email].absences
            assert absence.substitute_id == people[cover.email].id
            # Pół dnia i wniosek oczekujący nie są nieobecnością całodniową.
            assert people[half.email].available is True
            assert people[half.email].absences == []
            assert people[pending.email].available is True

            context = resolve_workforce(
                snapshot,
                [boss, away, cover, half, pending],
                now=_noon(WEDNESDAY).astimezone(timezone.utc),
                last_success_at=_noon(WEDNESDAY).astimezone(timezone.utc),
            )
            assert context.delegations[away.id].performer_id == cover.id
            assert away.id not in context.available_ids
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_company_day_off_is_not_a_working_day() -> None:
    async with AsyncSessionLocal() as db:
        try:
            await _person(db, "solo")
            existing = await db.scalar(
                text("SELECT id FROM company_days_off WHERE day = :day"),
                {"day": WEDNESDAY},
            )
            if existing is None:
                db.add(CompanyDayOff(day=WEDNESDAY, name="Dzień firmy"))
                await db.flush()
            snapshot = AvailabilitySnapshot.model_validate(
                await local.build_local_snapshot(db, _noon(WEDNESDAY))
            )
            assert snapshot.working_day is False
            assert not any(person.available for person in snapshot.people)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_workdays_payload_matches_compass_shape() -> None:
    async with AsyncSessionLocal() as db:
        try:
            boss = await _person(db, "boss2", UserRole.head_of_recruitment)
            worker = await _person(db, "worker")
            await _leave(db, worker, date(2026, 10, 5), date(2026, 10, 5), decider=boss)
            await _leave(
                db,
                worker,
                date(2026, 10, 6),
                date(2026, 10, 6),
                half_day="afternoon",
                decider=boss,
            )
            await _leave(
                db, worker, date(2026, 10, 7), date(2026, 10, 7), status="pending"
            )

            payload = await local.local_workdays_payload(
                db, date(2026, 10, 1), date(2026, 10, 1), "month"
            )
            assert payload["basis"] == "business_days_minus_approved_leave"
            (row,) = [r for r in payload["people"] if r["email"] == worker.email]
            assert row["period_start"] == "2026-10-01"
            assert row["period_end"] == "2026-10-31"
            assert row["business_days"] == 22
            assert row["absence_days"] == 1.5
            assert row["working_days"] == 20.5

            weeks = await local.local_workdays_payload(
                db, date(2026, 10, 7), date(2026, 10, 7), "week"
            )
            (week,) = [r for r in weeks["people"] if r["email"] == worker.email]
            assert (week["period_start"], week["period_end"]) == (
                "2026-10-05",
                "2026-10-11",
            )
            assert week["absence_days"] == 1.5

            assert await local.days_off_for(
                db, worker.id, date(2026, 10, 1), date(2026, 10, 31)
            ) == frozenset({date(2026, 10, 5)})
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_source_switch_reads_its_own_setting() -> None:
    async with AsyncSessionLocal() as db:
        try:
            row = await db.get(AppSetting, local.SOURCE_SETTING)
            if row is None:
                db.add(AppSetting(key=local.SOURCE_SETTING, value="local"))
            else:
                row.value = "local"
            await db.flush()
            assert await local.refresh_source(db, force=True) is True
            assert local.availability_enabled() is True
        finally:
            await db.rollback()
            local.reset_source_cache()
    assert local.availability_enabled() is False


def test_week_of_leave_is_not_behind_pace() -> None:
    monday = date(2026, 10, 19)
    week = frozenset(monday + timedelta(days=i) for i in range(5))
    wednesday_noon = _noon(WEDNESDAY)
    assert expected_progress_ratio(KpiPeriod.week, wednesday_noon, week) == 0.0
    assert expected_progress_ratio(KpiPeriod.day, wednesday_noon, week) == 0.0
    # Bez urlopu w środę w południe tydzień jest w toku.
    assert 0.0 < expected_progress_ratio(KpiPeriod.week, wednesday_noon) < 1.0
    # Urlop w poniedziałek i wtorek: środa w południe to początek pracy w tym tygodniu.
    two_days = frozenset({monday, monday + timedelta(days=1)})
    partial = expected_progress_ratio(KpiPeriod.week, wednesday_noon, two_days)
    assert 0.0 < partial < 0.5


def test_buckets_follow_compass_boundaries() -> None:
    assert local._buckets(date(2026, 12, 15), date(2027, 1, 3), "month") == [
        (date(2026, 12, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 1, 31)),
    ]
    assert local._buckets(date(2026, 10, 21), date(2026, 10, 21), "week") == [
        (date(2026, 10, 19), date(2026, 10, 25))
    ]
