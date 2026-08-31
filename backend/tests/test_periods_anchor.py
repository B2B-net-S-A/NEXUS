"""Kotwica okresu (`resolve_period(..., offset=)`) — testy jednostkowe.

Bez kotwicy jedynym sposobem zaadresowania POPRZEDNIEGO miesiąca był `custom`
z ręcznie policzonymi datami — więc każdy konsument liczył granice miesiąca
u siebie i mylił się inaczej. Te testy pilnują arytmetyki w jednym miejscu,
ze szczególnym naciskiem na przejścia przez granicę roku i na DST (okresy są
w Europe/Warsaw, więc marzec i październik mają doby 23- i 25-godzinne).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.analytics.periods import (
    MAX_PERIOD_OFFSET,
    PeriodError,
    PeriodKind,
    resolve_period,
)

_TZ = ZoneInfo("Europe/Warsaw")


def _at(y: int, m: int, d: int, hh: int = 12) -> datetime:
    return datetime(y, m, d, hh, tzinfo=_TZ)


def _d(p) -> tuple[date, date]:
    return p.start.date(), p.end.date()


# ── offset=0 nie zmienia dotychczasowego zachowania ────────────────────────


@pytest.mark.parametrize("kind", ["day", "week", "month", "quarter", "year"])
def test_offset_zero_is_the_previous_default(kind: str):
    """Domyślny offset=0 musi dawać dokładnie to, co dawał kod bez kotwicy."""
    now = _at(2026, 8, 31)
    assert resolve_period(kind, now=now) == resolve_period(kind, offset=0, now=now)


# ── przesuwanie wstecz ─────────────────────────────────────────────────────


def test_month_offset_minus_one_is_previous_closed_month():
    p = resolve_period("month", offset=-1, now=_at(2026, 8, 31))
    assert _d(p) == (date(2026, 7, 1), date(2026, 8, 1))


def test_month_offset_crosses_year_boundary_backwards():
    """Styczeń − 1 miesiąc to grudzień ROKU POPRZEDNIEGO, nie grudzień tego."""
    p = resolve_period("month", offset=-1, now=_at(2026, 1, 15))
    assert _d(p) == (date(2025, 12, 1), date(2026, 1, 1))


def test_month_offset_minus_thirteen():
    p = resolve_period("month", offset=-13, now=_at(2026, 8, 31))
    assert _d(p) == (date(2025, 7, 1), date(2025, 8, 1))


def test_week_offset_minus_one_is_previous_monday_to_monday():
    # 2026-08-31 to poniedziałek → poprzedni tydzień zaczyna się 2026-08-24.
    p = resolve_period("week", offset=-1, now=_at(2026, 8, 31))
    assert _d(p) == (date(2026, 8, 24), date(2026, 8, 31))


def test_quarter_offset_crosses_year_boundary_backwards():
    """Q1 − 1 kwartał to Q4 roku poprzedniego."""
    p = resolve_period("quarter", offset=-1, now=_at(2026, 2, 10))
    assert _d(p) == (date(2025, 10, 1), date(2026, 1, 1))


def test_quarter_offset_minus_two_from_q3():
    p = resolve_period("quarter", offset=-2, now=_at(2026, 8, 31))
    assert _d(p) == (date(2026, 1, 1), date(2026, 4, 1))


def test_year_offset_minus_one():
    p = resolve_period("year", offset=-1, now=_at(2026, 8, 31))
    assert _d(p) == (date(2025, 1, 1), date(2026, 1, 1))


def test_day_offset_crosses_month_boundary_backwards():
    p = resolve_period("day", offset=-1, now=_at(2026, 9, 1))
    assert _d(p) == (date(2026, 8, 31), date(2026, 9, 1))


# ── przesuwanie naprzód ────────────────────────────────────────────────────


def test_month_offset_plus_one_crosses_year_boundary():
    p = resolve_period("month", offset=1, now=_at(2026, 12, 5))
    assert _d(p) == (date(2027, 1, 1), date(2027, 2, 1))


# ── DST: okresy zostają kalendarzowe, mimo dób 23h/25h ─────────────────────


def test_month_spanning_spring_dst_keeps_calendar_boundaries():
    """Marzec 2026 ma dobę 23-godzinną (zmiana czasu 29.03).

    Granice okresu to nadal kalendarzowe północe, a nie „start + 31×24h".
    """
    p = resolve_period("month", offset=-1, now=_at(2026, 4, 10))
    assert _d(p) == (date(2026, 3, 1), date(2026, 4, 1))
    assert p.start.utcoffset() != p.end.utcoffset()  # CET → CEST


def test_month_spanning_autumn_dst_keeps_calendar_boundaries():
    """Październik 2026 ma dobę 25-godzinną (zmiana czasu 25.10)."""
    p = resolve_period("month", offset=-1, now=_at(2026, 11, 10))
    assert _d(p) == (date(2026, 10, 1), date(2026, 11, 1))
    assert p.start.utcoffset() != p.end.utcoffset()  # CEST → CET


def test_leap_day_is_addressable():
    p = resolve_period("day", offset=0, now=_at(2024, 2, 29))
    assert _d(p) == (date(2024, 2, 29), date(2024, 3, 1))


# ── granice i błędy ────────────────────────────────────────────────────────


def test_offset_beyond_limit_is_rejected():
    with pytest.raises(PeriodError, match="offset poza zakresem"):
        resolve_period("month", offset=MAX_PERIOD_OFFSET + 1, now=_at(2026, 8, 31))


def test_negative_offset_beyond_limit_is_rejected():
    with pytest.raises(PeriodError, match="offset poza zakresem"):
        resolve_period("month", offset=-MAX_PERIOD_OFFSET - 1, now=_at(2026, 8, 31))


def test_offset_with_custom_is_rejected():
    """Cicho przesunięty custom dałby okno inne niż to, o które poproszono."""
    with pytest.raises(PeriodError, match="offset nie ma zastosowania"):
        resolve_period(
            "custom",
            offset=-1,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )


def test_custom_without_offset_still_works():
    p = resolve_period("custom", date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert p.kind is PeriodKind.custom
    assert _d(p) == (date(2026, 1, 1), date(2026, 2, 1))


def test_periods_remain_half_open_and_contiguous():
    """end jednego okresu == start następnego — bez dziur i bez zakładek."""
    now = _at(2026, 8, 31)
    prev = resolve_period("month", offset=-1, now=now)
    cur = resolve_period("month", offset=0, now=now)
    assert prev.end == cur.start
