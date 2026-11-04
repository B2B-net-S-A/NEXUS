"""Kalendarz pracy firmy dla urlopów — czyste funkcje, bez bazy.

Święta liczy biblioteka ``holidays`` dla każdego roku (Compass trzymał tabelę
zasianą na 2026–2030; brak roku = 1 stycznia jako dzień roboczy).
"""

from __future__ import annotations

from datetime import date

from app.services.hr.absence import chain_until
from app.services.hr.calendar import WorkCalendar, month_days


def test_weekend_holiday_and_company_day_off_are_not_working_days() -> None:
    calendar = WorkCalendar(company_days_off={date(2026, 11, 10): "Dzień firmy"})
    assert calendar.kind(date(2026, 11, 7)) == "weekend"
    assert calendar.kind(date(2026, 11, 11)) == "holiday"
    assert calendar.kind(date(2026, 11, 10)) == "company"
    assert calendar.kind(date(2026, 11, 12)) == "work"
    assert calendar.day_name(date(2026, 11, 10)) == "Dzień firmy"
    assert "Niepodległości" in (calendar.day_name(date(2026, 11, 11)) or "")


def test_christmas_week_has_five_working_days_in_2026() -> None:
    # Makieta „Wniosek o urlop”: 23–31.12.2026 = 5 dni roboczych
    # (24–26.12 święta, w tym Wigilia wolna od 2025; 27.12 niedziela).
    calendar = WorkCalendar()
    days = calendar.working_days(date(2026, 12, 23), date(2026, 12, 31))
    assert days == [
        date(2026, 12, 23),
        date(2026, 12, 28),
        date(2026, 12, 29),
        date(2026, 12, 30),
        date(2026, 12, 31),
    ]


def test_holidays_exist_for_years_compass_never_seeded() -> None:
    calendar = WorkCalendar()
    assert not calendar.is_working_day(date(2031, 1, 1))
    assert not calendar.is_working_day(date(2035, 12, 25))


def test_return_date_skips_weekend_and_holidays() -> None:
    calendar = WorkCalendar()
    assert calendar.next_working_day_after(date(2026, 12, 31)) == date(2027, 1, 4)
    assert calendar.next_working_day_after(date(2026, 10, 23)) == date(2026, 10, 26)


def test_reversed_range_has_no_days() -> None:
    assert WorkCalendar().working_days(date(2026, 5, 5), date(2026, 5, 4)) == []


def test_month_days_cover_whole_month() -> None:
    assert len(month_days(2026, 2)) == 28
    assert len(month_days(2028, 2)) == 29
    assert month_days(2026, 12)[-1] == date(2026, 12, 31)


def test_absence_until_chains_requests_over_the_weekend() -> None:
    calendar = WorkCalendar()
    spans = [
        (date(2026, 10, 19), date(2026, 10, 23)),
        (date(2026, 10, 26), date(2026, 10, 28)),
        (date(2026, 11, 16), date(2026, 11, 17)),
    ]
    # Urlop do piątku + kolejny od poniedziałku = jedna nieobecność do środy;
    # wniosek z listopada już się nie dokleja.
    assert chain_until(spans, date(2026, 10, 23), calendar) == date(2026, 10, 28)
