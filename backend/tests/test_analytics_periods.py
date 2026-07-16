"""Unit-testy kanonicznych okresów Analytics v1 (plan PR 2).

Czysta logika — bez DB. Pokrywa: DST wiosna/jesień Warsaw, rok przestępny,
granice dnia/tygodnia/miesiąca/kwartału/roku, custom bez from/to,
custom > 366 dni, semantykę [start, end).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.analytics.periods import (
    ANALYTICS_TIMEZONE,
    MAX_CUSTOM_PERIOD_DAYS,
    Period,
    PeriodError,
    PeriodKind,
    resolve_period,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def _at(y: int, m: int, d: int, hh: int = 12) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=WARSAW)


# ── podstawowe granice kalendarzowe ──────────────────────────────────────────


def test_day_period_is_calendar_day_warsaw():
    p = resolve_period("day", now=_at(2026, 7, 16, 23))
    assert p.start == datetime(2026, 7, 16, 0, 0, tzinfo=WARSAW)
    assert p.end == datetime(2026, 7, 17, 0, 0, tzinfo=WARSAW)
    assert p.kind is PeriodKind.day
    assert p.timezone == ANALYTICS_TIMEZONE


def test_day_uses_warsaw_calendar_not_utc():
    # 2026-07-16 23:30 UTC == 2026-07-17 01:30 w Warszawie (CEST) —
    # dzień kalendarzowy musi być 17., nie 16.
    now_utc = datetime(2026, 7, 16, 23, 30, tzinfo=timezone.utc)
    p = resolve_period("day", now=now_utc)
    assert p.start == datetime(2026, 7, 17, 0, 0, tzinfo=WARSAW)


def test_week_starts_monday():
    # 2026-07-16 to czwartek → tydzień od poniedziałku 13. do 20. (excl.)
    p = resolve_period("week", now=_at(2026, 7, 16))
    assert p.start.date() == date(2026, 7, 13)
    assert p.end.date() == date(2026, 7, 20)
    assert p.start.weekday() == 0


def test_month_boundaries():
    p = resolve_period("month", now=_at(2026, 7, 16))
    assert p.start.date() == date(2026, 7, 1)
    assert p.end.date() == date(2026, 8, 1)


def test_month_december_rolls_year():
    p = resolve_period("month", now=_at(2026, 12, 31))
    assert p.start.date() == date(2026, 12, 1)
    assert p.end.date() == date(2027, 1, 1)


@pytest.mark.parametrize(
    "month,q_start,q_end",
    [
        (2, date(2026, 1, 1), date(2026, 4, 1)),
        (5, date(2026, 4, 1), date(2026, 7, 1)),
        (7, date(2026, 7, 1), date(2026, 10, 1)),
        (11, date(2026, 10, 1), date(2027, 1, 1)),
    ],
)
def test_quarter_boundaries(month: int, q_start: date, q_end: date):
    p = resolve_period("quarter", now=_at(2026, month, 15))
    assert p.start.date() == q_start
    assert p.end.date() == q_end


def test_year_boundaries():
    p = resolve_period("year", now=_at(2026, 7, 16))
    assert p.start.date() == date(2026, 1, 1)
    assert p.end.date() == date(2027, 1, 1)


# ── DST Warsaw ───────────────────────────────────────────────────────────────


def test_dst_spring_forward_day_has_23_hours():
    # 2026-03-29: przejście CET→CEST (2:00 → 3:00) — doba ma 23h.
    # UWAGA: odejmowanie aware-datetimes o WSPÓLNYM tzinfo jest w Pythonie
    # naiwne (ignoruje zmianę offsetu) — realny czas mierzymy przez UTC.
    p = resolve_period("day", now=_at(2026, 3, 29, 12))
    span = p.end.astimezone(timezone.utc) - p.start.astimezone(timezone.utc)
    assert span.total_seconds() == 23 * 3600
    # Offsety UTC różne po obu stronach przejścia.
    assert p.start.utcoffset().total_seconds() == 3600
    assert p.end.utcoffset().total_seconds() == 7200


def test_dst_fall_back_day_has_25_hours():
    # 2026-10-25: przejście CEST→CET — doba ma 25h.
    p = resolve_period("day", now=_at(2026, 10, 25, 12))
    span = p.end.astimezone(timezone.utc) - p.start.astimezone(timezone.utc)
    assert span.total_seconds() == 25 * 3600


def test_dst_spring_week_covers_transition():
    # Tydzień 2026-03-23..2026-03-30 zawiera przejście — 7 dni kalendarzowych,
    # ale 167h zegara.
    p = resolve_period("week", now=_at(2026, 3, 26))
    assert p.start.date() == date(2026, 3, 23)
    assert p.end.date() == date(2026, 3, 30)
    real = p.end.astimezone(timezone.utc) - p.start.astimezone(timezone.utc)
    assert real.total_seconds() == 167 * 3600


# ── rok przestępny ───────────────────────────────────────────────────────────


def test_leap_year_february():
    p = resolve_period("month", now=_at(2028, 2, 10))
    assert p.start.date() == date(2028, 2, 1)
    assert p.end.date() == date(2028, 3, 1)
    assert (p.end - p.start).days == 29


def test_leap_year_full_year_custom_allowed():
    # Rok przestępny = dokładnie 366 dni — mieści się w limicie.
    p = resolve_period("custom", date_from=date(2028, 1, 1), date_to=date(2028, 12, 31))
    assert (p.end - p.start).days == 366


# ── custom ───────────────────────────────────────────────────────────────────


def test_custom_requires_both_bounds():
    with pytest.raises(PeriodError):
        resolve_period("custom", date_from=date(2026, 1, 1))
    with pytest.raises(PeriodError):
        resolve_period("custom", date_to=date(2026, 1, 31))
    with pytest.raises(PeriodError):
        resolve_period("custom")


def test_custom_rejects_reversed_bounds():
    with pytest.raises(PeriodError):
        resolve_period("custom", date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))


def test_custom_rejects_over_366_days():
    with pytest.raises(PeriodError) as exc:
        resolve_period("custom", date_from=date(2026, 1, 1), date_to=date(2027, 1, 2))
    assert str(MAX_CUSTOM_PERIOD_DAYS) in str(exc.value)


def test_custom_is_inclusive_of_date_to():
    # Użytkownik podaje dni inclusive; [start, end) ⇒ end = date_to + 1.
    p = resolve_period("custom", date_from=date(2026, 7, 1), date_to=date(2026, 7, 1))
    assert p.start.date() == date(2026, 7, 1)
    assert p.end.date() == date(2026, 7, 2)


def test_unknown_kind_raises():
    with pytest.raises(PeriodError):
        resolve_period("fortnight")


# ── kontrakt payloadu ────────────────────────────────────────────────────────


def test_payload_shape():
    p = resolve_period("month", now=_at(2026, 7, 16))
    payload = p.as_payload()
    assert payload["kind"] == "month"
    assert payload["timezone"] == "Europe/Warsaw"
    assert payload["start"].startswith("2026-07-01T00:00:00")
    assert payload["end"].startswith("2026-08-01T00:00:00")


def test_period_is_timezone_aware_and_frozen():
    p = resolve_period("day", now=_at(2026, 7, 16))
    assert p.start.tzinfo is not None
    assert p.end.tzinfo is not None
    with pytest.raises(AttributeError):
        p.kind = PeriodKind.year  # type: ignore[misc]
    assert isinstance(p, Period)
