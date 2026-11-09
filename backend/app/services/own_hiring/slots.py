"""Wolne terminy i dni robocze: czyste funkcje, bez bazy i Microsoftu."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ, is_business_day

Interval = tuple[datetime, datetime]

_DAY_NAMES = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")
_MONTH_NAMES = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "windows": {
        "0": [["09:00", "11:00"]],
        "3": [["09:00", "14:30"]],
        "4": [["10:00", "12:00"]],
    },
    "slot_minutes": 30,
    "office_minutes": 60,
    "buffer_minutes": 15,
    "lead_hours": 24,
    "horizon_days": 14,
    "response_business_days": 3,
    "office_address": "",
}


@dataclass(frozen=True)
class SlotRules:
    windows: Mapping[str, Sequence[Sequence[str]]]
    minutes: int
    buffer_minutes: int
    lead_hours: int
    horizon_days: int

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any], *, kind: str) -> "SlotRules":
        merged = {**DEFAULT_SETTINGS, **settings}
        return cls(
            windows=merged["windows"],
            minutes=int(
                merged["office_minutes"] if kind == "office" else merged["slot_minutes"]
            ),
            buffer_minutes=int(merged["buffer_minutes"]),
            lead_hours=int(merged["lead_hours"]),
            horizon_days=int(merged["horizon_days"]),
        )


def _clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _overlaps(start: datetime, end: datetime, blocks: Sequence[Interval]) -> bool:
    return any(
        start < block_end and block_start < end for block_start, block_end in blocks
    )


def compute_slots(
    rules: SlotRules,
    *,
    now: datetime,
    busy: Sequence[Interval],
    tz: str = DEFAULT_TZ,
) -> list[datetime]:
    """Początki wolnych terminów, w UTC, rosnąco."""
    zone = ZoneInfo(tz)
    earliest = now + timedelta(hours=rules.lead_hours)
    buffer = timedelta(minutes=rules.buffer_minutes)
    length = timedelta(minutes=rules.minutes)
    today = now.astimezone(zone).date()
    out: list[datetime] = []
    for offset in range(rules.horizon_days + 1):
        day = today + timedelta(days=offset)
        noon = datetime.combine(day, time(12, 0), tzinfo=zone)
        if not is_business_day(noon, tz):
            continue
        for window in rules.windows.get(str(day.weekday()), ()):
            cursor = datetime.combine(day, _clock(window[0]), tzinfo=zone)
            limit = datetime.combine(day, _clock(window[1]), tzinfo=zone)
            while cursor + length <= limit:
                if cursor >= earliest and not _overlaps(
                    cursor - buffer, cursor + length + buffer, busy
                ):
                    out.append(cursor.astimezone(timezone.utc))
                cursor += length + buffer
    return out


def day_label(day: date) -> str:
    return f"{_DAY_NAMES[day.weekday()]} {day.day} {_MONTH_NAMES[day.month - 1]}"


def group_by_day(
    slots: Sequence[datetime], tz: str = DEFAULT_TZ
) -> list[dict[str, Any]]:
    zone = ZoneInfo(tz)
    days: dict[date, list[datetime]] = {}
    for slot in slots:
        days.setdefault(slot.astimezone(zone).date(), []).append(slot)
    return [
        {"date": day.isoformat(), "label": day_label(day), "slots": items}
        for day, items in sorted(days.items())
    ]


def response_deadline(
    sent_at: datetime, business_days: int, tz: str = DEFAULT_TZ
) -> datetime:
    """Koniec n-tego dnia roboczego po wysyłce, w kalendarzu firmy."""
    zone = ZoneInfo(tz)
    day = sent_at.astimezone(zone).date()
    counted = 0
    while counted < business_days:
        day += timedelta(days=1)
        if is_business_day(datetime.combine(day, time(12, 0), tzinfo=zone), tz):
            counted += 1
    end_of_day = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=zone)
    return end_of_day.astimezone(timezone.utc)
