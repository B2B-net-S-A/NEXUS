"""Punkty „Dlaczego nasz kandydat” jako kompetencje (pomiar poprawek 17.11.2026).

Na 126 CV zatwierdzonych 09–16.11.2026 rekruterzy przepisywali punkty 3–5
z pojedynczych osiągnięć („Projektował…”) na kompetencje („Doświadczenie w…”),
usuwali linię „Specjalizacja: …”, podnosili lata w punkcie 1 (role pokrewne),
dopisywali miesiące do dat ról i zmieniali kategorię „Dane i BI” na AI.
Reguła: docs/claude/generator-cv/dlaczego-kompetencje-zamiast-osiagniec.md.
"""

from __future__ import annotations

import pytest

from app.services.cv_generator_b2b.legacy_v7 import _helpers
from app.services.cv_generator_b2b.legacy_v7.client_sector import apply_client_sector
from app.services.cv_generator_b2b.legacy_v7.prompts import get_prompt


@pytest.mark.parametrize("language", ["pl", "en"])
def test_prompt_has_no_specialization_line(language):
    prompt = get_prompt(language, False, "tailored")
    assert "Specjalizacja:" not in prompt
    assert "Specialization:" not in prompt


def test_polish_prompt_asks_for_competency_points():
    prompt = get_prompt("pl", False, "tailored")
    assert "„Doświadczenie w" in prompt
    assert "w tym 7 lat jako DevOps Engineer" in prompt
    # Punkty 3–5 nie zaczynają się już od czasownika w czasie przeszłym.
    assert "Projektował i rozwijał [pierwszy must-have]" not in prompt


def test_english_prompt_asks_for_competency_points():
    prompt = get_prompt("en", False, "tailored")
    assert '"Experience in' in prompt
    assert "including 7 years as a DevOps Engineer" in prompt
    assert "Designed and developed [first must-have]" not in prompt


@pytest.mark.parametrize(
    "language, category",
    [("pl", "AI i uczenie maszynowe"), ("en", "AI and machine learning")],
)
def test_skill_categories_include_ai(language, category):
    assert category in get_prompt(language, False, "tailored")


@pytest.mark.parametrize(
    "language, phrase",
    [("pl", "skali CEFR"), ("en", "CEFR")],
)
def test_languages_use_cefr_when_the_source_gives_it(language, phrase):
    assert phrase in get_prompt(language, False, "tailored")


@pytest.mark.parametrize(
    "language, phrase",
    [("pl", "Miesiąc ze źródła"), ("en", "month from the source")],
)
def test_role_dates_keep_the_month_from_the_source(language, phrase):
    assert phrase in get_prompt(language, False, "tailored")


def _data(point, roles):
    return {
        "why_points": [point, "b", "c", "d", "e"],
        "experience": [{"dates": d, "position": p, "company": c} for d, p, c in roles],
    }


def test_area_figure_with_role_subfigure_is_not_replaced_by_whole_career():
    """„w IT” z wyliczeniem roli: kod nie wlicza lat z kelnerowania."""
    data = _data(
        "3 lata doświadczenia w IT, w tym 3 lata jako Analyst",
        [
            ("01.2022 – 06.2025", "Analyst", "Bank"),
            ("01.2016 – 12.2021", "Waiter", "Restaurant"),
        ],
    )
    _helpers._fix_experience_years(data, "pl")
    assert (
        data["why_points"][0] == "3 lata doświadczenia w IT, w tym 3 lata jako Analyst"
    )


def test_plain_it_figure_still_takes_whole_career():
    data = _data(
        "5 lat doświadczenia w IT",
        [("01.2016 – 06.2025", "Developer", "Acme")],
    )
    _helpers._fix_experience_years(data, "pl")
    assert data["why_points"][0] == "Ponad 9 lat doświadczenia w IT"


def test_sector_clause_is_a_separate_fact_after_role_subfigure():
    """Punkt 1 z „w tym M lat jako X” nie traci dopisku o branży klienta."""
    data = _data(
        "Ponad 8 lat doświadczenia w IT, w tym ponad 7 lat jako DevOps Engineer",
        [
            ("08.2019 – 11.2026", "DevOps Engineer", "Bank Sp. z o.o."),
            ("06.2018 – 07.2019", "Support Engineer", "Acme"),
        ],
    )
    point = apply_client_sector(
        data,
        {
            "sector": "bankowym",
            "roles": [{"company": "Bank Sp. z o.o.", "industry_company": "Bank"}],
        },
        cv_text="Bank Sp. z o.o.",
        language="pl",
        blind_cv=False,
    )
    assert point == (
        "Ponad 8 lat doświadczenia w IT, w tym ponad 7 lat jako DevOps Engineer; "
        "ponad 7 lat w sektorze bankowym (Bank)"
    )


@pytest.mark.parametrize(
    "point",
    [
        "Doświadczenie w zapewnianiu zgodności z wymaganiami DORA w Nordea — przeglądy kontroli dla 12 systemów",
        "Experience in regulatory compliance at Nordea, aligning AML controls with EU requirements",
    ],
)
def test_competency_point_about_compliance_is_not_a_fit_verdict(point):
    """Punkty 3–5 zaczynają się teraz od „Doświadczenie w…”; zgodność to fakt."""
    data = {"why_points": ["5 lat doświadczenia jako Analyst", "a", point, "c", "d"]}
    _helpers._apply_summary_standard(data, "pl")
    assert point in data["why_points"]


def test_fit_verdict_is_still_removed():
    point = "Doświadczenie kandydata jest zgodne z wymaganiami roli"
    data = {"why_points": ["5 lat doświadczenia jako Analyst", "a", point, "c", "d"]}
    _helpers._apply_summary_standard(data, "pl")
    assert point not in data["why_points"]
