"""Lata doświadczenia w „Dlaczego nasz kandydat” (audyt 13.10.2026, zmiana 02.11.2026).

Decyzja Artura z 02.11.2026: nagłówek nie zawyża stażu. Rekruterzy poprawiali
„18 lat” na „Ponad 17 lat” (19 z 67 plików zmieniało tę liczbę), więc kod pisze
pełne lata w dół, a od 3 dodatkowych miesięcy „Ponad N”. Ułamek modelu zgodny
z datami zostaje. Dane fikcyjne.
"""

from datetime import datetime

import pytest

from app.services.cv_generator_b2b.legacy_v7 import _helpers


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(_helpers, "local_now", lambda: datetime(2026, 10, 14, 12, 0))


def _fixed(point, dates="01.2022 – 06.2026", language="pl"):
    data = {
        "why_points": [point],
        "experience": [
            {"position": "Developer", "company": "Firma Testowa", "dates": dates}
        ],
    }
    _helpers._fix_experience_years(data, language)
    _helpers._fix_scoped_years(data, language)
    return data["why_points"][0]


@pytest.mark.parametrize(
    "point,dates",
    [
        ("4,5 roku doświadczenia komercyjnego", "01.2022 – 06.2026"),
        ("2,5 roku doświadczenia", "01.2024 – 06.2026"),
        ("4,5 roku w Firma Testowa", "01.2022 – 06.2026"),
    ],
)
def test_fraction_that_matches_the_dates_stays(point, dates):
    assert _fixed(point, dates) == point


def test_headline_never_rounds_the_tenure_up():
    assert _fixed("5 lat doświadczenia") == "Ponad 4 lata doświadczenia"
    assert _fixed("3 lata doświadczenia", "01.2024 – 06.2026") == (
        "Ponad 2 lata doświadczenia"
    )


@pytest.mark.parametrize(
    "dates,expected",
    [
        ("01.2022 – 12.2025", "4 lata doświadczenia"),  # równo 48 miesięcy
        ("01.2022 – 02.2026", "4 lata doświadczenia"),  # 2 miesiące to jeszcze N
        ("01.2022 – 03.2026", "Ponad 4 lata doświadczenia"),  # 3 miesiące
        ("01.2022 – 11.2026", "Ponad 4 lata doświadczenia"),  # 4 lata 11 mies.
    ],
)
def test_over_starts_at_three_extra_months(dates, expected):
    assert _fixed("9 lat doświadczenia", dates) == expected


def test_over_keeps_the_model_prefix_out_and_the_case_of_the_sentence():
    assert _fixed("Ponad 9 lat doświadczenia") == "Ponad 4 lata doświadczenia"
    assert _fixed("Łącznie 9 lat doświadczenia") == "Łącznie ponad 4 lata doświadczenia"


def test_over_in_english():
    assert (
        _fixed("9 years of experience", language="en") == "Over 4 years of experience"
    )


def test_overlapping_contracts_count_once():
    data = {
        "why_points": ["9 lat doświadczenia"],
        "experience": [
            {"position": "A", "company": "X", "dates": "01.2018 – 12.2022"},
            {"position": "B", "company": "Y", "dates": "01.2020 – 12.2022"},
        ],
    }
    _helpers._fix_experience_years(data, "pl")
    assert data["why_points"] == ["5 lat doświadczenia"]


def test_gap_between_jobs_does_not_count():
    data = {
        "why_points": ["9 lat doświadczenia"],
        "experience": [
            {"position": "A", "company": "X", "dates": "01.2010 – 12.2011"},
            {"position": "B", "company": "Y", "dates": "01.2020 – 12.2021"},
        ],
    }
    _helpers._fix_experience_years(data, "pl")
    assert data["why_points"] == ["4 lata doświadczenia"]


def test_scoped_figure_uses_the_same_rule():
    assert _fixed("9 lat jako Developer") == "Ponad 4 lata jako Developer"
    assert _fixed("Pracował 9 lat w Firma Testowa") == (
        "Pracował ponad 4 lata w Firma Testowa"
    )


def test_under_a_year_is_one_year_like_before():
    assert _fixed("1 rok doświadczenia", "01.2026 – 06.2026") == "1 rok doświadczenia"
    assert _fixed("5 lat doświadczenia", "01.2026 – 09.2026") == "1 rok doświadczenia"
    assert _fixed("5 lat doświadczenia", "01.2026 – 03.2026") == "5 lat doświadczenia"


def test_fraction_far_from_the_dates_is_still_corrected():
    # 45 miesięcy = 3 lata 9 miesięcy; „4.5 years” nie jest zgodne z datami.
    assert _fixed("4.5 years of experience", "01.2023 – 09.2026", "en") == (
        "Over 3 years of experience"
    )
