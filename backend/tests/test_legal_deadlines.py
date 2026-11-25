"""Terminy według art. 111–116 KC i postanowień umów B2B."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.legal import deadlines as d


def test_days_skip_the_event_day() -> None:
    result = d.term_end(date(2026, 3, 3), 14, d.UNIT_DAYS)
    assert result.end == date(2026, 3, 17)
    assert result.basis == ("art. 111 § 2 KC",)


def test_month_from_31st_ends_on_last_day_of_shorter_month() -> None:
    assert d.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert d.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert d.add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)
    result = d.term_end(date(2026, 1, 31), 1, d.UNIT_MONTHS)
    assert result.end == date(2026, 2, 28)
    assert "ostatni dzień miesiąca" in result.steps[0]


def test_february_start_keeps_the_day_number() -> None:
    assert d.add_months(date(2026, 2, 28), 1) == date(2026, 3, 28)
    assert d.add_years(date(2028, 2, 29), 1) == date(2029, 2, 28)
    assert d.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_non_continuous_month_is_30_days() -> None:
    result = d.term_end(date(2026, 1, 31), 1, d.UNIT_MONTHS, continuous=False)
    assert result.end == date(2026, 3, 2)
    assert result.basis == ("art. 114 KC",)


def test_month_points_and_half_month() -> None:
    assert d.month_point(2026, 2, "start") == date(2026, 2, 1)
    assert d.month_point(2026, 2, "middle") == date(2026, 2, 15)
    assert d.month_point(2026, 2, "end") == date(2026, 2, 28)
    with pytest.raises(ValueError):
        d.month_point(2026, 2, "koniec")


def test_action_deadline_on_weekend_or_holiday_moves_to_working_day() -> None:
    # 14 dni od 26.12.2026 = 9.01.2027 (sobota) → poniedziałek 11.01.2027.
    result = d.term_end(date(2026, 12, 26), 14, d.UNIT_DAYS, shift_free_days=True)
    assert result.end == date(2027, 1, 11)
    assert "art. 115 KC" in result.basis
    # 11 listopada 2026 (środa, święto) → 12 listopada.
    assert d.next_working_day(date(2026, 11, 11)) == date(2026, 11, 12)


def test_end_of_contract_is_not_shifted_by_default() -> None:
    result = d.term_end(date(2026, 12, 26), 14, d.UNIT_DAYS)
    assert result.end == date(2027, 1, 9)
    assert "art. 115 KC" not in result.basis


def test_notice_to_end_of_month_does_not_count_delivery_month() -> None:
    assert d.notice_end_of_month(date(2026, 3, 10), 1).end == date(2026, 4, 30)
    assert d.notice_end_of_month(date(2026, 3, 31), 1).end == date(2026, 4, 30)
    assert d.notice_end_of_month(date(2026, 11, 15), 3).end == date(2027, 2, 28)


def test_notice_delivered_on_the_first_still_starts_next_month() -> None:
    result = d.notice_end_of_month(date(2026, 3, 1), 1)
    assert result.end == date(2026, 4, 30)
    assert "1 kwietnia 2026 r." in result.steps[1]
    assert "1 miesiąc kalendarzowy" in result.steps[1]
    assert (
        "2 miesiące kalendarzowe" in d.notice_end_of_month(date(2026, 3, 1), 2).steps[1]
    )


def test_notice_in_days_to_end_of_month() -> None:
    assert d.notice_days_end_of_month(date(2026, 1, 31), 30).end == date(2026, 3, 31)
    assert d.notice_days_end_of_month(date(2026, 1, 15), 14).end == date(2026, 1, 31)


def test_from_next_month() -> None:
    assert d.from_next_month(date(2026, 12, 31)).end == date(2027, 1, 1)
    assert d.from_next_month(date(2026, 5, 1)).end == date(2026, 6, 1)


def test_bad_input_is_refused() -> None:
    with pytest.raises(ValueError):
        d.term_end(date(2026, 1, 1), 1, "kwartały")
    with pytest.raises(ValueError):
        d.add_days(date(2026, 1, 1), -1)
    with pytest.raises(ValueError):
        d.notice_end_of_month(date(2026, 1, 1), 0)


def test_polish_date() -> None:
    assert d.polish_date(date(2026, 9, 1)) == "1 września 2026 r."
