"""CV-11: never inflate a scoped claim or fabricate date precision."""

import pytest

from app.services.cv_generator_b2b.standalone_service import (
    _fix_experience_years,
    _parse_date_range,
    _total_experience_years,
)


@pytest.mark.parametrize(
    "dates",
    ["03.2020–06.2022", "03/2020–06/2022", "2020-03–2022-06"],
)
def test_month_formats_have_identical_intervals(dates):
    assert _parse_date_range(dates) == (2020 * 12 + 2, 2022 * 12 + 5)
    assert _total_experience_years([{"dates": dates}]) == 2


def test_nineteen_months_are_not_two_completed_years():
    assert _total_experience_years([{"dates": "01.2020–07.2021"}]) == 1


@pytest.mark.parametrize("dates", ["2020–2022", "2020", "13.2020–06.2022", ""])
def test_incomplete_or_invalid_dates_do_not_assert_exact_total(dates):
    assert _total_experience_years([{"dates": dates}]) is None


def test_partial_history_does_not_become_complete_total():
    assert _total_experience_years(
        [{"dates": "01.2020–12.2022"}, {"company": "Earlier employer"}]
    ) is None


@pytest.mark.parametrize(
    "point,language",
    [
        ("3 lata doświadczenia jako Python Developer", "pl"),
        ("3 lata doświadczenia w AWS", "pl"),
        ("3 lata doświadczenia w Go", "pl"),
        ("3 lata doświadczenia w bankowości", "pl"),
        ("3 years of experience as a Python Developer", "en"),
        ("3 years of experience with AWS", "en"),
        ("3 years of experience at Acme", "en"),
        ("3 years of Python experience", "en"),
        ("Python: 3 years of experience", "en"),
        ("3 lata doświadczenia programistycznego", "pl"),
    ],
)
def test_career_change_cannot_inflate_scoped_claim(point, language):
    data = {
        "experience": [
            {"position": "Warehouse worker", "dates": "01.2010–12.2017"},
            {"position": "Python Developer", "dates": "01.2018–12.2020"},
        ],
        "why_points": [point],
    }
    _fix_experience_years(data, language)
    assert data["why_points"] == [point]


@pytest.mark.parametrize("number", ["2,5 roku", "2.5 roku", "2–4 lata", "2+ lata"])
def test_generic_total_replaces_entire_numeric_expression(number):
    data = {
        "experience": [{"dates": "01.2020–12.2022"}],
        "why_points": [f"{number} doświadczenia zawodowego"],
    }
    _fix_experience_years(data, "pl")
    assert data["why_points"] == ["3 lata doświadczenia zawodowego"]


def test_employment_gaps_are_not_counted_as_experience():
    assert _total_experience_years(
        [{"dates": "01.2018–12.2018"}, {"dates": "01.2022–12.2022"}]
    ) == 2
