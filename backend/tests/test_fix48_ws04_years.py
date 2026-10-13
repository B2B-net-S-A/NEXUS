"""Lata doświadczenia w „Dlaczego nasz kandydat” — poprawka po audycie 13.10.2026.

`round()` w Pythonie zaokrągla połówki do parzystej: 54 miesiące (4,5 roku)
dawały 4, a model, który napisał „4,5 roku”, dostawał „4 lata”. Staż nie może
być zaniżany: połowa roku idzie w górę, a ułamek modelu zgodny z datami
zostaje. Dane fikcyjne.
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


def test_half_year_rounds_up_not_to_even():
    assert _helpers._total_experience_years([{"dates": "01.2022 – 06.2026"}]) == 5
    assert _fixed("4 lata doświadczenia") == "5 lat doświadczenia"
    assert _fixed("3 lata doświadczenia", "01.2024 – 06.2026") == (
        "3 lata doświadczenia"
    )


def test_fraction_far_from_the_dates_is_still_corrected():
    # 45 miesięcy = 3,75 roku → 4; „4.5 years” nie jest zgodne z datami.
    assert _fixed("4.5 years of experience", "01.2023 – 09.2026", "en") == (
        "4 years of experience"
    )
