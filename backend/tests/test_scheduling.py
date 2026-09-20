"""Unit tests for `app.core.scheduling` — timezone helpers bez DB."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.scheduling import (
    is_business_day,
    is_within_local_hours,
    is_within_window,
    local_day_bounds,
    seconds_until_local_time,
)


WARSAW = ZoneInfo("Europe/Warsaw")


# ── local_day_bounds ─────────────────────────────────────────────────────────


def test_day_bounds_on_winter_day_utc_plus_1():
    now = datetime(2026, 1, 15, 10, 30, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    assert bounds.start_utc == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)
    assert bounds.end_utc.astimezone(WARSAW).date() == now.date()
    assert bounds.end_utc.astimezone(WARSAW).hour == 23
    assert bounds.end_utc.astimezone(WARSAW).minute == 59


def test_day_bounds_on_summer_day_utc_plus_2():
    now = datetime(2026, 7, 15, 10, 30, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    assert bounds.start_utc == datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)


def test_day_bounds_around_dst_transition_spring():
    # W Polsce zmiana czasu zimowego → letniego: 30 marca 2025, 02:00 → 03:00.
    now = datetime(2025, 3, 30, 12, 0, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    # 30 marca zaczyna się o 23:00 UTC 29 marca (UTC+1 przed zmianą).
    assert bounds.start_utc == datetime(2025, 3, 29, 23, 0, tzinfo=timezone.utc)


def test_day_bounds_from_utc_input_converts_correctly():
    # Wejście w UTC — 00:30 UTC 16 stycznia = 01:30 Warsaw 16 stycznia.
    now_utc = datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc)
    bounds = local_day_bounds(now_utc)
    assert bounds.start_utc.astimezone(WARSAW).date() == (
        now_utc.astimezone(WARSAW).date()
    )


# ── is_business_day ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "iso_date,expected",
    [
        ("2026-04-20", True),  # Mon
        ("2026-04-21", True),  # Tue
        ("2026-04-24", True),  # Fri
        ("2026-04-25", False),  # Sat
        ("2026-04-26", False),  # Sun
    ],
)
def test_is_business_day(iso_date, expected):
    moment = datetime.fromisoformat(iso_date + "T10:00:00+02:00")
    assert is_business_day(moment) is expected


@pytest.mark.parametrize(
    "iso_date,label",
    [
        ("2026-01-01", "Nowy Rok (czw)"),
        ("2026-01-06", "Trzech Króli (wt)"),
        ("2026-04-06", "Poniedziałek Wielkanocny — RUCHOME (pon)"),
        ("2026-05-01", "Święto Pracy (pt)"),
        ("2026-06-04", "Boże Ciało — RUCHOME (czw)"),
        ("2026-11-11", "Święto Niepodległości (śr)"),
        ("2026-12-24", "Wigilia — wolna ustawowo od 2025 (czw)"),
        ("2026-12-25", "Boże Narodzenie (pt)"),
    ],
)
def test_weekday_polish_holiday_is_not_a_business_day(iso_date, label):
    """Święto w dniu tygodnia NIE jest dniem roboczym.

    Bez tego target „4 weryfikacje / dzień roboczy" liczyłby 1 maja jako dzień
    pracy, a triggery notyfikacji budziłyby ludzi w Boże Ciało.
    """
    moment = datetime.fromisoformat(iso_date + "T10:00:00+01:00")
    assert is_business_day(moment) is False, label


def test_moveable_holidays_track_easter_across_years():
    """Ruchome święta nie są zahardkodowane — jadą za datą Wielkanocy.

    Wielkanoc 2025 = 20 IV, 2026 = 5 IV. Poniedziałek Wielkanocny i Boże Ciało
    (Wielkanoc + 60 dni) muszą się przesunąć razem z nią.
    """
    # 2025: Poniedziałek Wielkanocny 21 IV, Boże Ciało 19 VI.
    assert is_business_day(datetime(2025, 4, 21, 10, tzinfo=WARSAW)) is False
    assert is_business_day(datetime(2025, 6, 19, 10, tzinfo=WARSAW)) is False
    # ...i te same dni w 2026 są już zwykłymi dniami roboczymi.
    assert is_business_day(datetime(2026, 4, 21, 10, tzinfo=WARSAW)) is True
    assert is_business_day(datetime(2026, 6, 19, 10, tzinfo=WARSAW)) is True


def test_holiday_falling_on_weekend_stays_non_business():
    """3 maja 2026 = niedziela. Nadal nie-roboczy, bez podwójnego liczenia."""
    assert is_business_day(datetime(2026, 5, 3, 10, tzinfo=WARSAW)) is False


def test_business_day_uses_local_date_not_utc_date():
    """23:30 UTC 31 XII to już 1 I lokalnie → święto, nie dzień roboczy.

    Gdyby funkcja patrzyła na datę UTC, zobaczyłaby 31 XII (czwartek, roboczy).
    """
    new_years_eve_late_utc = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert new_years_eve_late_utc.astimezone(WARSAW).date().isoformat() == "2026-01-01"
    assert is_business_day(new_years_eve_late_utc) is False


# ── is_within_window ─────────────────────────────────────────────────────────


def test_window_exact_match():
    now = datetime(2026, 4, 21, 11, 45, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is True


def test_window_within_5min_tolerance():
    now = datetime(2026, 4, 21, 11, 49, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is True


def test_window_outside_tolerance():
    now = datetime(2026, 4, 21, 11, 51, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is False


def test_window_custom_tolerance():
    now = datetime(2026, 4, 21, 11, 52, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45, window_minutes=10) is True


# ── seconds_until_local_time ─────────────────────────────────────────────────


def test_seconds_until_future_target_today():
    now = datetime(2026, 4, 21, 10, 0, tzinfo=WARSAW)
    secs = seconds_until_local_time(now, hour=11, minute=45)
    # 1h 45min = 6300s
    assert secs == pytest.approx(6300, abs=1)


def test_seconds_until_target_passed_today_rolls_to_tomorrow():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=WARSAW)
    secs = seconds_until_local_time(now, hour=11, minute=45)
    # Cel minął o 15 min → jutro = 23h 45min = 85500s
    assert secs == pytest.approx(23 * 3600 + 45 * 60, abs=1)


# ── is_within_local_hours ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hour,expected",
    [
        (7, False),
        (8, True),  # granica otwarcia jest DOMKNIĘTA
        (12, True),
        (17, True),
        (18, False),  # granica zamknięcia jest OTWARTA: „do 18:00"
        (23, False),
        (0, False),
    ],
)
def test_business_hours_window_is_half_open(hour: int, expected: bool):
    now = datetime(2026, 4, 21, hour, 30, tzinfo=WARSAW)
    assert is_within_local_hours(now, start_hour=8, end_hour=18) is expected


def test_equal_hours_mean_the_window_is_off_not_empty():
    """Escape hatch bez deployu: wyrównane godziny = bieg całą dobę.

    Odwrotna interpretacja („okno o zerowej długości") zatrzymałaby pętlę na
    zawsze, a jedynym objawem byłaby cisza.
    """
    for hour in (0, 3, 12, 23):
        now = datetime(2026, 4, 21, hour, tzinfo=WARSAW)
        assert is_within_local_hours(now, start_hour=8, end_hour=8) is True


def test_window_may_wrap_around_midnight():
    assert is_within_local_hours(
        datetime(2026, 4, 21, 23, tzinfo=WARSAW), start_hour=22, end_hour=6
    )
    assert is_within_local_hours(
        datetime(2026, 4, 21, 3, tzinfo=WARSAW), start_hour=22, end_hour=6
    )
    assert not is_within_local_hours(
        datetime(2026, 4, 21, 12, tzinfo=WARSAW), start_hour=22, end_hour=6
    )


def test_hours_out_of_range_narrow_the_window_instead_of_crashing():
    """Literówka w konfiguracji ma zawęzić okno, nie wywrócić pętli."""
    now = datetime(2026, 4, 21, 12, tzinfo=WARSAW)
    assert is_within_local_hours(now, start_hour=-5, end_hour=99) is True


def test_utc_clock_is_converted_before_the_hour_is_read():
    """Kontener chodzi w UTC — bez konwersji okno przesuwałoby się o 1–2 h.

    07:30 UTC to 09:30 w Warszawie (czas letni), czyli środek okna; bez
    konwersji wypadłoby przed 8:00 i bieg by nie ruszył.
    """
    now = datetime(2026, 7, 21, 7, 30, tzinfo=timezone.utc)
    assert is_within_local_hours(now, start_hour=8, end_hour=18) is True


def test_dst_shift_moves_the_window_with_the_local_clock():
    """Ta sama godzina UTC, dwie strony zmiany czasu, dwie różne odpowiedzi.

    16:30 UTC = 18:30 w czasie letnim (poza oknem) i 17:30 w zimowym (w oknie).
    """
    summer = datetime(2026, 10, 20, 16, 30, tzinfo=timezone.utc)
    winter = datetime(2026, 11, 20, 16, 30, tzinfo=timezone.utc)
    assert is_within_local_hours(summer, start_hour=8, end_hour=18) is False
    assert is_within_local_hours(winter, start_hour=8, end_hour=18) is True


def test_naive_datetime_is_read_as_local_not_utc():
    now = datetime(2026, 4, 21, 9, 0)
    assert is_within_local_hours(now, start_hour=8, end_hour=18) is True
