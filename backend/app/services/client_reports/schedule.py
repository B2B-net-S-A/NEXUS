"""Okresy, terminy i stany raportów klienta — czyste funkcje, bez bazy.

Kalendarz „co i komu w tym miesiącu” liczy się przy odczycie: definicja
(rytm + reguła terminu) × okresy, a stan z historii wysyłek. Dlatego nie ma
tabeli wystąpień do pilnowania.

Klucz okresu (``period_key``) jest tekstem, bo trafia do adresu i do historii:
``2026-W47`` (tydzień ISO), ``2026-10``, ``2026-Q3``, ``2026-H2``, ``2026``,
a rok umowy to data jego początku, np. ``2026-02-27``.

Reguła terminu (``due_rule``):

* ``{"type": "day_of_month", "day": 5}`` — 5. dzień miesiąca po końcu okresu
  (BNP: do 5. dnia następnego miesiąca),
* ``{"type": "business_days_after", "days": 5}`` — dni robocze po końcu okresu
  (kalendarz firmy: weekendy i polskie święta),
* ``{"type": "days_after", "days": 15}`` — dni kalendarzowe po końcu okresu,
* ``{"type": "fixed", "month": 1, "day": 21}`` — pierwszy taki dzień po końcu
  okresu (raport roczny do 21 stycznia),
* ``{"type": "end_of_period"}`` — ostatni dzień okresu (zestawienie „na koniec
  kwartału”),
* ``{"type": "none"}`` albo brak — termin do ustalenia.

Rok umowy bierze początek z ``due_rule["anchor"]`` (``"MM-DD"``) albo z daty
„obowiązuje od” definicji.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Optional

from app.core.scheduling import _polish_holidays

CALENDAR_RHYTHMS: frozenset[str] = frozenset(
    {"weekly", "monthly", "quarterly", "semiannual", "annual", "contract_year"}
)
DUE_RULE_TYPES: tuple[str, ...] = (
    "none",
    "day_of_month",
    "business_days_after",
    "days_after",
    "fixed",
    "end_of_period",
)
MAX_OFFSET_DAYS = 120

MONTHS_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
QUARTERS_PL = ("I", "II", "III", "IV")


@dataclass(frozen=True)
class Period:
    key: str
    start: date
    end: date
    label: str


class ScheduleError(ValueError):
    """Zły klucz okresu albo reguła terminu — komunikat dla użytkownika."""


# ---------------------------------------------------------------- dni robocze


def is_workday(day: date) -> bool:
    return day.weekday() < 5 and day not in _polish_holidays(day.year)


def add_workdays(day: date, days: int) -> date:
    current = day
    left = days
    while left > 0:
        current += timedelta(days=1)
        if is_workday(current):
            left -= 1
    return current


# --------------------------------------------------------------------- okresy


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _anchor(due_rule: Mapping[str, Any], valid_from: Optional[date]) -> tuple[int, int]:
    raw = due_rule.get("anchor")
    if isinstance(raw, str) and re.fullmatch(
        r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", raw
    ):
        month, day = (int(part) for part in raw.split("-"))
        return month, min(day, 28) if month == 2 else day
    if valid_from is not None:
        return valid_from.month, min(
            valid_from.day, 28
        ) if valid_from.month == 2 else valid_from.day
    raise ScheduleError(
        "Rok umowy potrzebuje daty początku (np. 02-27) albo daty „obowiązuje od”."
    )


def _safe_date(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def period_containing(
    rhythm: str,
    day: date,
    due_rule: Mapping[str, Any] | None = None,
    valid_from: Optional[date] = None,
) -> Period:
    """Okres danego rytmu, w którym leży ``day``."""
    rule = due_rule or {}
    if rhythm == "weekly":
        iso_year, iso_week, _ = day.isocalendar()
        start = day - timedelta(days=day.weekday())
        return Period(
            f"{iso_year}-W{iso_week:02d}",
            start,
            start + timedelta(days=6),
            f"tydzień {iso_week} ({start:%d.%m}–{start + timedelta(days=6):%d.%m.%Y})",
        )
    if rhythm == "monthly":
        return Period(
            f"{day.year}-{day.month:02d}",
            date(day.year, day.month, 1),
            _month_end(day.year, day.month),
            f"{MONTHS_PL[day.month - 1]} {day.year}",
        )
    if rhythm == "quarterly":
        quarter = (day.month - 1) // 3
        start_month = quarter * 3 + 1
        return Period(
            f"{day.year}-Q{quarter + 1}",
            date(day.year, start_month, 1),
            _month_end(day.year, start_month + 2),
            f"{QUARTERS_PL[quarter]} kwartał {day.year}",
        )
    if rhythm == "semiannual":
        half = 0 if day.month <= 6 else 1
        start_month = 1 + half * 6
        return Period(
            f"{day.year}-H{half + 1}",
            date(day.year, start_month, 1),
            _month_end(day.year, start_month + 5),
            f"{'I' if half == 0 else 'II'} półrocze {day.year}",
        )
    if rhythm == "annual":
        return Period(
            str(day.year),
            date(day.year, 1, 1),
            date(day.year, 12, 31),
            f"rok {day.year}",
        )
    if rhythm == "contract_year":
        month, dom = _anchor(rule, valid_from)
        start = _safe_date(day.year, month, dom)
        if start > day:
            start = _safe_date(day.year - 1, month, dom)
        next_start = _safe_date(start.year + 1, month, dom)
        end = next_start - timedelta(days=1)
        return Period(
            start.isoformat(),
            start,
            end,
            f"rok umowy {start:%d.%m.%Y}–{end:%d.%m.%Y}",
        )
    raise ScheduleError("Ten rytm nie ma okresów (zdarzeniowo albo na żądanie).")


def period_from_key(
    rhythm: str,
    key: str,
    due_rule: Mapping[str, Any] | None = None,
    valid_from: Optional[date] = None,
) -> Period:
    """Okres z klucza w adresie; klucz musi pasować do rytmu definicji."""
    patterns = {
        "weekly": r"(\d{4})-W(0[1-9]|[1-4]\d|5[0-3])",
        "monthly": r"(\d{4})-(0[1-9]|1[0-2])",
        "quarterly": r"(\d{4})-Q([1-4])",
        "semiannual": r"(\d{4})-H([12])",
        "annual": r"(\d{4})",
        "contract_year": r"(\d{4})-(\d{2})-(\d{2})",
    }
    pattern = patterns.get(rhythm)
    match = re.fullmatch(pattern, key) if pattern else None
    if not match:
        raise ScheduleError("Okres nie pasuje do rytmu raportu.")
    year = int(match.group(1))
    if not 2000 <= year <= 2100:
        raise ScheduleError("Rok okresu poza zakresem.")
    if rhythm == "weekly":
        try:
            probe = date.fromisocalendar(year, int(match.group(2)), 1)
        except ValueError as exc:
            raise ScheduleError("Nie ma takiego tygodnia w tym roku.") from exc
    elif rhythm == "monthly":
        probe = date(year, int(match.group(2)), 1)
    elif rhythm == "quarterly":
        probe = date(year, (int(match.group(2)) - 1) * 3 + 1, 1)
    elif rhythm == "semiannual":
        probe = date(year, 1 if match.group(2) == "1" else 7, 1)
    elif rhythm == "annual":
        probe = date(year, 1, 1)
    else:
        try:
            probe = date.fromisoformat(key)
        except ValueError as exc:
            raise ScheduleError("Zła data początku roku umowy.") from exc
    period = period_containing(rhythm, probe, due_rule, valid_from)
    if period.key != key:
        raise ScheduleError("Okres nie pasuje do początku roku umowy.")
    return period


def previous_period(
    rhythm: str,
    period: Period,
    due_rule: Mapping[str, Any] | None = None,
    valid_from: Optional[date] = None,
) -> Period:
    return period_containing(
        rhythm, period.start - timedelta(days=1), due_rule, valid_from
    )


def recent_periods(
    rhythm: str,
    today: date,
    count: int,
    due_rule: Mapping[str, Any] | None = None,
    valid_from: Optional[date] = None,
) -> list[Period]:
    """Bieżący okres i ``count - 1`` poprzednich, od najnowszego."""
    if rhythm not in CALENDAR_RHYTHMS:
        return []
    current = period_containing(rhythm, today, due_rule, valid_from)
    out = [current]
    while len(out) < count:
        out.append(previous_period(rhythm, out[-1], due_rule, valid_from))
    return out


# --------------------------------------------------------------------- terminy


def validate_due_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
    """Normalizuje regułę terminu z formularza; zły kształt = ScheduleError."""
    kind = rule.get("type") or "none"
    if kind not in DUE_RULE_TYPES:
        raise ScheduleError("Nieznany rodzaj terminu.")
    out: dict[str, Any] = {"type": kind}
    if kind == "day_of_month":
        day = rule.get("day")
        if not isinstance(day, int) or not 1 <= day <= 31:
            raise ScheduleError("Dzień miesiąca musi być od 1 do 31.")
        out["day"] = day
    elif kind in ("business_days_after", "days_after"):
        days = rule.get("days")
        if not isinstance(days, int) or not 0 <= days <= MAX_OFFSET_DAYS:
            raise ScheduleError(f"Liczba dni musi być od 0 do {MAX_OFFSET_DAYS}.")
        out["days"] = days
    elif kind == "fixed":
        month, day = rule.get("month"), rule.get("day")
        if not isinstance(month, int) or not 1 <= month <= 12:
            raise ScheduleError("Miesiąc terminu musi być od 1 do 12.")
        if (
            not isinstance(day, int)
            or not 1 <= day <= calendar.monthrange(2024, month)[1]
        ):
            raise ScheduleError("Dzień terminu nie istnieje w tym miesiącu.")
        out.update(month=month, day=day)
    anchor = rule.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, str) or not re.fullmatch(
            r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", anchor
        ):
            raise ScheduleError("Początek roku umowy w formacie MM-DD, np. 02-27.")
        out["anchor"] = anchor
    return out


def due_date(rule: Mapping[str, Any] | None, period: Period) -> Optional[date]:
    """Termin raportu za okres; ``None`` = do ustalenia."""
    kind = (rule or {}).get("type") or "none"
    if kind == "day_of_month":
        year, month = _shift_month(period.end.year, period.end.month, 1)
        return _safe_date(year, month, int(rule["day"]))
    if kind == "business_days_after":
        return add_workdays(period.end, int(rule["days"]))
    if kind == "days_after":
        return period.end + timedelta(days=int(rule["days"]))
    if kind == "fixed":
        month, day = int(rule["month"]), int(rule["day"])
        candidate = _safe_date(period.end.year, month, day)
        if candidate <= period.end:
            candidate = _safe_date(period.end.year + 1, month, day)
        return candidate
    if kind == "end_of_period":
        return period.end
    return None


def describe_due_rule(rule: Mapping[str, Any] | None) -> str:
    kind = (rule or {}).get("type") or "none"
    if kind == "day_of_month":
        return f"do {rule['day']}. dnia następnego miesiąca"
    if kind == "business_days_after":
        return f"{rule['days']} dni roboczych po okresie"
    if kind == "days_after":
        return f"{rule['days']} dni po okresie"
    if kind == "fixed":
        return f"do {int(rule['day']):02d}.{int(rule['month']):02d}"
    if kind == "end_of_period":
        return "na koniec okresu"
    return "termin do ustalenia"


def report_state(due: Optional[date], sent: bool, today: date) -> str:
    """``sent`` > ``no_date`` > ``overdue`` / ``today`` / ``todo``."""
    if sent:
        return "sent"
    if due is None:
        return "no_date"
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    return "todo"
