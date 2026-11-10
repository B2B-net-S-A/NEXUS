"""Minimum porcji rośnie osobno dla każdego (decyzja Artura 08.11.2026).

Start od minimum z ustawień HoR. Kto w dniu roboczym zrobił swoje minimum,
następnego dnia roboczego ma o ``STEP`` więcej, aż do ``CAP``, i przy ``CAP``
zostaje do odwołania. Od 10.11.2026 poziom to też wielkość porcji osoby
(``review_batch_plan``), a liczy się sama decyzja, bez domknięcia screeningu. Kto nie zrobił, zostaje na swoim poziomie: poziom nie
spada. Stan siedzi w ``app_settings['review_batch_levels']``, a przelicza go
pierwszy tick nowego dnia (``new_column_autofill._batch_tick``), w tej samej
transakcji co plan dnia.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today, is_business_day, local_day_start_utc
from app.models.app_setting import AppSetting

LEVELS_KEY = "review_batch_levels"
STEP = 10
CAP = 50


def next_level(level: int, done: int) -> int:
    """Poziom na następny dzień roboczy po ``done`` decyzjach."""
    if done < level or level >= CAP:
        return level
    return min(level + STEP, CAP)


def level_of(stored: dict[int, int], user_id: int, base: int) -> int:
    """Minimum osoby: jej poziom, nigdy niższy niż minimum z ustawień HoR."""
    return max(stored.get(user_id, base), base)


def previous_business_day(day: date) -> date:
    tz = settings.BUSINESS_TZ
    day -= timedelta(days=1)
    while not is_business_day(datetime.combine(day, time(12), tzinfo=ZoneInfo(tz)), tz):
        day -= timedelta(days=1)
    return day


def _parse(value: object) -> dict[int, int]:
    users = value.get("users") if isinstance(value, dict) else None
    if not isinstance(users, dict):
        return {}
    out: dict[int, int] = {}
    for user_id, level in users.items():
        try:
            out[int(user_id)] = int(level)
        except (TypeError, ValueError):
            continue
    return out


async def read_levels(db: AsyncSession) -> dict[int, int]:
    row = await db.get(AppSetting, LEVELS_KEY)
    return _parse(row.value) if row is not None else {}


async def _advanced(
    db: AsyncSession, stored: dict[int, int], today: date, now: datetime
) -> dict[int, int]:
    """Poziomy po ostatnim dniu roboczym."""
    from app.services import review_batch as rb

    base = (await rb.read_settings(db)).minimum
    ids = [row["id"] for row in await rb.batch_recruiters(db)]
    day = previous_business_day(today)
    tz = settings.BUSINESS_TZ
    start = local_day_start_utc(day, tz)
    end = local_day_start_utc(day + timedelta(days=1), tz)
    # Od 10.11.2026 liczy się sama decyzja („Pasuje” albo „Nie pasuje” z powodem),
    # tak jak do porcji dnia. Termin na wynik screeningu dalej blokuje wyszukiwanie.
    decisions = await rb._decisions(db, ids, now=now, since=start)
    out = dict(stored)
    for user_id in ids:
        done = sum(
            1
            for decision in decisions.get(user_id, [])
            if start <= decision.moved_at < end
        )
        level = next_level(level_of(stored, user_id, base), done)
        if level > base:
            out[user_id] = level
    return out


async def roll_levels(
    db: AsyncSession, *, now: datetime, today: Optional[date] = None
) -> dict[int, int]:
    """Raz dziennie przelicza poziomy; pierwszy raz zaczyna od minimum z ustawień,
    bo dni sprzed włączenia porcji nie powinny nikomu podnosić poprzeczki."""
    day = (today or business_today()).isoformat()
    row = await db.get(AppSetting, LEVELS_KEY, with_for_update=True)
    state = row.value if row is not None and isinstance(row.value, dict) else None
    stored = _parse(state)
    if state is not None and state.get("day") == day:
        return stored
    if state is not None:
        stored = await _advanced(db, stored, date.fromisoformat(day), now)
    value = {"day": day, "users": {str(k): v for k, v in sorted(stored.items())}}
    if row is None:
        db.add(AppSetting(key=LEVELS_KEY, value=value))
    else:
        row.value = value
    await db.flush()
    return stored
