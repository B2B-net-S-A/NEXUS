"""Błędy „Nowego CV” znalezione w pętli jakości na szkicach ze stagingu (25.11.2026)."""

from __future__ import annotations

import pytest

from app.services.cv_new_layout import NewCvDocument, fit_new_cv_page1
from app.services.cv_new_layout.axis import stops
from app.services.cv_new_layout.context import build_context
from app.services.cv_new_layout.facts import Span, duration_text, parse_dates
from app.services.cv_new_layout.labels import LABELS
from tests._cv_new_layout_fixtures import TODAY, _skill_groups, english, long_cv

NOW = 2026 + 10.6 / 12


def test_year_only_end_means_december_like_the_editor():
    """#42327: „09.2018 - 2019” dawało 4 mies.; edytor (`client-form-years.ts`) i staż do
    Worda (`cv_tenure_checks`) liczą koniec samym rokiem jako grudzień: 1 rok 4 mies."""
    span = parse_dates("09.2018 - 2019", NOW)
    assert span.start == pytest.approx(2018 + 8 / 12) and span.end == pytest.approx(
        2020.0
    )
    assert duration_text(span) == "ok. 1 rok"  # koniec bez miesiąca: pełne lata w dół
    assert parse_dates("2014 - 2016", NOW) == Span(2014.0, 2017.0, False)
    assert parse_dates("2019", NOW) == Span(2019.0, 2020.0, False)


def test_same_company_with_year_only_end_is_one_segment():
    data = long_cv()
    data["experience"] = [
        {
            "dates": d,
            "company": "Trimetis Services Sp. z o.o.",
            "position": "Tester",
            "industry": "",
            "technologies": [],
            "responsibilities": [],
        }
        for d in ("09.2019 - 01.2022", "09.2018 - 2019")
    ]
    st = stops(build_context(NewCvDocument.from_cv_json(data), TODAY))
    assert [s.company for s in st] == ["Trimetis Services"]


def test_english_education_block_is_not_titled_like_the_section():
    """Po angielsku nagłówek sekcji i podtytuł bloku były oba „Education”."""
    en = LABELS["en"]
    assert en["schooling_head"].casefold() != en["education"].casefold()


def test_page1_fits_with_many_skill_categories():
    """#43050: 15 kategorii umiejętności — strona 1 nie mieściła się nawet przy 8 pt,
    a Edukacja wypadała z kartki. Nadmiar kategorii idzie na str. 2."""
    data = english(long_cv())
    data["skills"] = _skill_groups(22, 9)
    report = fit_new_cv_page1(NewCvDocument.from_cv_json(data), today=TODAY)
    assert report.fits, report
    assert report.font_pt >= 8.0
