"""Granice okresów w strefie biznesowej — fundament pod temat 6 audytu.

113 wywołań ``date.today()`` w app/ czyta zegar KONTENERA (UTC), a firma pracuje
w Europe/Warsaw. Różnica to 1 h latem i 2 h zimą — czyli okno, w którym „dziś"
znaczy co innego dla systemu i dla użytkownika. Objaw jest cichy: liczba jest
poprawna, tylko opisuje inny dzień.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.core.scheduling import (
    business_today,
    local_month_bounds,
    local_quarter_bounds,
)


def _utc(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_business_today_is_a_date():
    assert isinstance(business_today(), date)


def test_winter_month_starts_at_23_utc_previous_day():
    """Zimą Warszawa to UTC+1, więc styczeń zaczyna się 31.12 o 23:00 UTC."""
    b = local_month_bounds(date(2026, 1, 15))
    assert b.start_utc == _utc(2025, 12, 31, 23)
    assert b.end_utc == _utc(2026, 1, 31, 23)


def test_summer_month_starts_at_22_utc_previous_day():
    """Latem Warszawa to UTC+2 — offset NIE jest stały przez rok."""
    b = local_month_bounds(date(2026, 7, 15))
    assert b.start_utc == _utc(2026, 6, 30, 22)
    assert b.end_utc == _utc(2026, 7, 31, 22)


def test_quarter_spanning_dst_switch_has_different_offsets_at_each_end():
    """Q1 2026 zaczyna się w czasie zimowym, a kończy w letnim (zmiana 29.03).

    Stała korekta o godzinę dałaby tu złą granicę na jednym z końców.
    """
    q = local_quarter_bounds(date(2026, 3, 20))
    assert q.start_utc == _utc(2025, 12, 31, 23)  # UTC+1
    assert q.end_utc == _utc(2026, 3, 31, 22)  # UTC+2


def test_quarter_boundaries_cover_the_year_without_gap_or_overlap():
    ends = []
    for month in (1, 4, 7, 10):
        q = local_quarter_bounds(date(2026, month, 15))
        ends.append((q.start_utc, q.end_utc))
    for (_, prev_end), (next_start, _) in zip(ends, ends[1:]):
        assert prev_end == next_start, "kwartały muszą się stykać co do mikrosekundy"


def test_december_rolls_into_next_year():
    b = local_month_bounds(date(2026, 12, 5))
    assert b.end_utc == _utc(2026, 12, 31, 23)


def test_bounds_are_half_open_so_midnight_belongs_to_the_new_period():
    """Zdarzenie dokładnie o północy lokalnej należy do NOWEGO okresu.

    Domknięty koniec wymagałby „ostatniej mikrosekundy" i gubił zdarzenia
    zapisane właśnie w niej.
    """
    jan = local_month_bounds(date(2026, 1, 15))
    feb = local_month_bounds(date(2026, 2, 15))
    assert jan.end_utc == feb.start_utc
