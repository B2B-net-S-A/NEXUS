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


def test_role_without_company_is_labeled_with_its_position_not_own_business():
    """#42900: generator zostawił puste firmy; oś podpisywała każdą rolę „Own business”
    i stawiała je obok siebie — pusta firma to nie własna działalność."""
    data = english(long_cv())
    data["experience"] = [
        {
            "dates": d,
            "company": "",
            "position": p,
            "industry": "",
            "technologies": [],
            "responsibilities": [],
        }
        for d, p in (
            ("09.2023 - currently", "Senior Project Manager"),
            ("01.2021 - 12.2023", "Program Manager"),
            ("05.2014 - 01.2020", "Project Manager"),
        )
    ]
    st = stops(build_context(NewCvDocument.from_cv_json(data), TODAY))
    assert [s.company for s in st] == [
        "Project Manager",
        "Program Manager",
        "Senior Project Manager",
    ]
    assert all(s.role == "" for s in st)


def test_hand_edited_education_row_keeps_dates_out_of_the_field():
    """#40571: „2019 - 2022 — Ekonomia, licencjat” bez pogrubionej uczelni szło w całości
    do kierunku, razem z datami."""
    from app.services.cv_new_content import cv_json_from_editor_html

    html = (
        '<h1>Analityk – Jan Test</h1><h2 data-cv-section="education">EDUKACJA</h2>'
        "<p>2019 - 2022 — Ekonomia, licencjat</p>"
    )
    edu = cv_json_from_editor_html(
        html, language="pl", blind=False, fallback=None
    ).cv_json["education"]
    assert edu == [
        {
            "dates": "2019 - 2022",
            "institution": "",
            "degree": "Ekonomia, licencjat",
            "location": "",
        }
    ]


@pytest.mark.parametrize(
    "text", ["05.2025-obecnie", "05.2025–obecnie", "2019-2021", "05.2025 -obecnie"]
)
def test_dash_without_spaces_still_splits_the_range(text):
    """#39655, #39612: „05.2025-obecnie” bez spacji — stanowisko traciło datę początku."""
    span = parse_dates(text, NOW)
    assert span.start is not None and span.end is not None and span.end > span.start


def test_same_company_after_a_break_is_one_segment():
    """#39461: dwie prace w tej samej firmie z przerwą stały obok siebie na osi
    (oś nie pokazuje przerw — Artur 25.11.2026)."""
    data = english(long_cv())
    data["experience"] = [
        {
            "dates": d,
            "company": c,
            "position": p,
            "industry": "",
            "technologies": [],
            "responsibilities": [],
        }
        for d, c, p in (
            ("09.2024 - currently", "PEGASYSTEMS SOFTWARE LIMITED", "IT Specialist"),
            (
                "05.2022 - 10.2023",
                "PEGASYSTEMS SOFTWARE LIMITED",
                "Associate System Architect",
            ),
            ("03.2020 - 04.2022", "UBS BUSINESS SOLUTIONS POLAND", "Analyst"),
        )
    ]
    st = stops(build_context(NewCvDocument.from_cv_json(data), TODAY))
    assert [s.company for s in st] == [
        "Ubs Business Solutions",
        "Pegasystems Software Limited",
    ]
    assert st[-1].current and st[-1].role == "IT Specialist"


@pytest.mark.parametrize(
    ("text", "months"),
    [("05.2008 - 11-2009", 19), ("11-2009 - 03.2011", 17), ("05.2025-obecnie", None)],
)
def test_month_with_hyphen_is_a_date_not_a_range(text, months):
    """#38606: „05.2008 - 11-2009” po przecięciu myślnikiem bez spacji dawało 1 mies.;
    myślnik bez spacji dzieli zakres tylko po roku („05.2025-obecnie”)."""
    span = parse_dates(text, NOW)
    assert span.start is not None and span.end is not None
    if months is not None:
        assert round((span.end - span.start) * 12) == months
