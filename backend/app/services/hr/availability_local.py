"""Dostępność i dni robocze z urlopów NEXUSA zamiast z Compassa (krok 6).

Kontrakt danych zostaje ten sam, który dawał Compass, więc konsumenci (zastępstwa
w 23 miejscach, wyścigi Insights, przydział rekrutacji) nie wiedzą o zmianie:

* ``build_local_snapshot`` → ``AvailabilitySnapshot`` (osoby z kartoteką,
  zatwierdzone CAŁODNIOWE nieobecności w oknie 30 dni, zastępca),
* ``local_workdays_payload`` → ta sama odpowiedź co ``/api/internal/workdays``
  Compassa (dni robocze minus zatwierdzony urlop; pół dnia = 0,5),

Źródło przełącza admin przy przełączeniu urlopów (runbook, krok „źródło
dostępności local”): ``app_settings['hr_availability_source']`` = ``local``.
Osobny klucz, a nie sam moduł ``leave``, bo zastępstwa przejmują pracę w 23
miejscach NEXUSA — przełączenie ma być świadome i dopiero po imporcie kartotek.
Stan przełącznika jest trzymany w pamięci procesu i odświeżany najwyżej co
minutę (``refresh_source``), bo miejsca, które pytają „czy dostępność działa”,
są synchroniczne. Rodzaj nieobecności nigdy nie wychodzi poza moduł urlopów.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_date
from app.models.app_setting import AppSetting
from app.services.hr.calendar import load_calendar

SOURCE_SETTING = "hr_availability_source"
WINDOW_DAYS = 30
REFRESH_SECONDS = 60
EXPECTED_WORKDAYS_BASIS = "business_days_minus_approved_leave"

_SOURCE: dict[str, Any] = {"local": False, "checked": None}


def availability_enabled() -> bool:
    """Czy działa jakiekolwiek źródło dostępności (Compass albo NEXUS)."""
    return bool(settings.COMPASS_AVAILABILITY_ENABLED or _SOURCE["local"])


def local_source_active() -> bool:
    return bool(_SOURCE["local"])


def reset_source_cache(local: bool = False) -> None:
    """Dla testów i startu procesu."""
    _SOURCE.update(local=local, checked=None)


async def refresh_source(db: AsyncSession, *, force: bool = False) -> bool:
    """Odśwież stan przełącznika z ``app_settings`` (najwyżej raz na minutę)."""
    checked = _SOURCE["checked"]
    now = time.monotonic()
    if not force and checked is not None and now - checked < REFRESH_SECONDS:
        return bool(_SOURCE["local"])
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SOURCE_SETTING)
    )
    # Wyłączony program „Ludzi w NEXUSIE” nie przełącza dostępności na urlopy NEXUSA.
    local = bool(settings.HR_PROGRAM_ENABLED) and value == "local"
    _SOURCE.update(local=local, checked=now)
    return bool(_SOURCE["local"])


def _version(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


async def build_local_snapshot(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """Snapshot w kształcie ``AvailabilitySnapshot`` (walidacja po stronie wołającego).

    Pusta kartoteka daje pustą listę osób — walidacja snapshotu ją odrzuci
    i ostatni dobry snapshot zostaje (tak samo jak przy awarii Compassa).
    """
    today = business_date(now)
    window_end = today + timedelta(days=WINDOW_DAYS)
    working_day = (await load_calendar(db, today, today)).is_working_day(today)

    people_rows = (
        await db.execute(
            text(
                """
                SELECT p.user_id, p.public_id, p.employment_status, u.email
                FROM employee_profiles p
                JOIN users u ON u.id = p.user_id
                WHERE u.is_active
                ORDER BY p.user_id
                """
            )
        )
    ).all()
    public_ids = {row.user_id: row.public_id for row in people_rows}

    # Pół dnia jednego dnia nie jest nieobecnością całodniową — osoba pracuje
    # drugą połowę i nie oddaje pracy zastępcy (podstawa jak w Compassie).
    absence_rows = (
        await db.execute(
            text(
                """
                SELECT id, user_id, start_date, end_date, substitute_user_id
                FROM leave_requests
                WHERE status = 'approved'
                  AND half_day IS NULL
                  AND end_date >= :today
                  AND start_date <= :window_end
                ORDER BY start_date, id
                """
            ),
            {"today": today, "window_end": window_end},
        )
    ).all()
    absences: dict[int, list[dict[str, Any]]] = {}
    for row in absence_rows:
        absences.setdefault(row.user_id, []).append(
            {
                "id": str(row.id),
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "substitute_id": (
                    str(public_ids[row.substitute_user_id])
                    if row.substitute_user_id in public_ids
                    else None
                ),
            }
        )

    people = []
    for row in people_rows:
        own = absences.get(row.user_id, [])
        absent_today = any(
            date.fromisoformat(item["start_date"])
            <= today
            <= date.fromisoformat(item["end_date"])
            for item in own
        )
        people.append(
            {
                "id": str(row.public_id),
                "email": row.email,
                "employment_status": row.employment_status,
                "available": bool(
                    working_day
                    and row.employment_status in {"active", "offboarding"}
                    and not absent_today
                ),
                "absences": own,
            }
        )
    body = {
        "date": today.isoformat(),
        "working_day": working_day,
        "window_end": window_end.isoformat(),
        "people": people,
    }
    return {
        "schema_version": 1,
        "basis": "calendar_full_day_approved_absences",
        "complete": True,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "count": len(people),
        "snapshot_version": _version(body),
        **body,
    }


def _buckets(date_from: date, date_to: date, bucket: str) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    if bucket == "week":
        start = date_from - timedelta(days=date_from.weekday())
        while start <= date_to:
            out.append((start, start + timedelta(days=6)))
            start += timedelta(days=7)
        return out
    start = date_from.replace(day=1)
    while start <= date_to:
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append((start, nxt - timedelta(days=1)))
        start = nxt
    return out


async def local_workdays_payload(
    db: AsyncSession, date_from: date, date_to: date, bucket: str = "month"
) -> dict[str, Any]:
    """Odpowiedź w kształcie ``/api/internal/workdays`` Compassa, z danych NEXUSA."""
    periods = _buckets(date_from, date_to, bucket)
    if not periods:
        return {"basis": EXPECTED_WORKDAYS_BASIS, "people": []}
    first, last = periods[0][0], periods[-1][1]
    calendar = await load_calendar(db, first, last)
    people_rows = (
        await db.execute(
            text(
                """
                SELECT p.user_id, u.email
                FROM employee_profiles p JOIN users u ON u.id = p.user_id
                WHERE u.is_active
                """
            )
        )
    ).all()
    leave_rows = (
        await db.execute(
            text(
                """
                SELECT d.user_id, d.day, d.fraction
                FROM leave_request_days d
                JOIN leave_requests r ON r.id = d.leave_request_id
                WHERE r.status = 'approved' AND d.active
                  AND d.day BETWEEN :first AND :last
                """
            ),
            {"first": first, "last": last},
        )
    ).all()
    absent: dict[tuple[int, date], float] = {}
    for row in leave_rows:
        if calendar.is_working_day(row.day):
            key = (row.user_id, row.day)
            absent[key] = min(1.0, absent.get(key, 0.0) + float(row.fraction))

    people = []
    for start, end in periods:
        business = calendar.working_days(start, end)
        for person in people_rows:
            absence = sum(absent.get((person.user_id, day), 0.0) for day in business)
            people.append(
                {
                    "email": person.email,
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "business_days": len(business),
                    "absence_days": round(absence, 1),
                    "working_days": round(len(business) - absence, 1),
                }
            )
    return {"basis": EXPECTED_WORKDAYS_BASIS, "people": people}


async def days_off_for(
    db: AsyncSession, user_id: int, start: date, end: date
) -> frozenset[date]:
    """Dni pełnej nieobecności osoby (zatwierdzony urlop) — dla tempa celów KPI.

    Pół dnia nie zdejmuje dnia z mianownika (tempo nie umie liczyć połówek).
    """
    rows = await db.execute(
        text(
            """
            SELECT d.day
            FROM leave_request_days d
            JOIN leave_requests r ON r.id = d.leave_request_id
            WHERE r.status = 'approved' AND d.active AND d.user_id = :user_id
              AND d.fraction >= 1 AND d.day BETWEEN :start AND :end
            """
        ),
        {"user_id": user_id, "start": start, "end": end},
    )
    return frozenset(row[0] for row in rows)


SOURCES = ("compass", "local")


async def current_source(db: AsyncSession) -> str:
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SOURCE_SETTING)
    )
    return "local" if value == "local" else "compass"


async def set_source(db: AsyncSession, value: str, *, actor_user_id: int) -> str:
    """Przełączenie źródła urlopów dla zastępstw (runbook: po imporcie kartotek)."""
    if value not in SOURCES:
        raise ValueError(value)
    from sqlalchemy.dialects.postgresql import insert

    from app.services.hr import audit

    previous = await current_source(db)
    statement = insert(AppSetting).values(key=SOURCE_SETTING, value=value)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": value}
        )
    )
    audit.record(
        db,
        actor_user_id=actor_user_id,
        subject_user_id=None,
        entity_type="hr_settings",
        entity_id=SOURCE_SETTING,
        action="availability_source_changed",
        details={"from": previous, "to": value},
    )
    reset_source_cache(local=value == "local")
    return value
