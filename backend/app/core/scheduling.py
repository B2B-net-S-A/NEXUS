"""
Timezone-aware scheduling helpers for Phase 13 notification triggers.

Pure stdlib (`zoneinfo`, `datetime`) — no 3rd-party deps.

Wszystkie funkcje są bezstanowe, deterministyczne dla danego `now`, więc łatwe
do testowania z `freezegun`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Europe/Warsaw"


def local_now(tz: str = DEFAULT_TZ) -> datetime:
    """Timezone-aware "now" in the given zone. UTC on storage, local for gates."""
    return datetime.now(ZoneInfo(tz))


@dataclass(frozen=True)
class DayBounds:
    """UTC-aware start/end of a single local-calendar day in the given zone.

    Start = 00:00:00 local, end = 23:59:59.999999 local, both converted to UTC.
    Używane do filtrowania rekordów „z dzisiaj" (np. Call.created_at).
    """

    start_utc: datetime
    end_utc: datetime


def local_day_bounds(now: datetime, tz: str = DEFAULT_TZ) -> DayBounds:
    """Granice lokalnego dnia kalendarzowego przeliczone do UTC.

    Bezpieczne na DST: używamy `ZoneInfo`, który zwraca poprawny offset dla danego
    punktu w czasie (nie ma potrzeby ręcznej korekty o 1h).
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    today = local.date()
    start_local = datetime.combine(today, time.min, tzinfo=zone)
    end_local = datetime.combine(today, time.max, tzinfo=zone)
    return DayBounds(
        start_utc=start_local.astimezone(timezone.utc),
        end_utc=end_local.astimezone(timezone.utc),
    )


def is_business_day(moment: datetime, tz: str = DEFAULT_TZ) -> bool:
    """Mon–Fri, weekends off. MVP — polskie święta poza scope (TODO: `holidays`)."""
    zone = ZoneInfo(tz)
    local = moment.astimezone(zone) if moment.tzinfo else moment.replace(tzinfo=zone)
    return local.weekday() < 5


def is_within_window(
    now: datetime,
    *,
    hour: int,
    minute: int,
    window_minutes: int = 5,
    tz: str = DEFAULT_TZ,
) -> bool:
    """Czy `now` mieści się w oknie `[target - window, target + window]` lokalnie?

    Triggery z ostrym czasem (KPI 11:45, Client feedback 16:30) odpalamy tylko
    wtedy, gdy pętla trafia w okno. Reszta iteracji tego triggera jest pomijana.
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = abs((local - target).total_seconds())
    return delta <= window_minutes * 60


def seconds_until_local_time(
    now: datetime,
    hour: int,
    minute: int,
    tz: str = DEFAULT_TZ,
) -> float:
    """Ile sekund zostało do następnego wystąpienia `hour:minute` lokalnie.

    Jeśli cel minął już dziś → zwraca czas do jutra o tej samej porze.
    """
    zone = ZoneInfo(tz)
    local = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target = target + timedelta(days=1)
    return (target - local).total_seconds()


__all__ = [
    "DEFAULT_TZ",
    "DayBounds",
    "is_business_day",
    "is_within_window",
    "local_day_bounds",
    "local_now",
    "seconds_until_local_time",
]
