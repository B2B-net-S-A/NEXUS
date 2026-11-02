"""Okres stanowiska w CV firmowym jak w oryginale (zgłoszenie z 02.11.2026)."""

from datetime import date

import pytest

from app.services import cv_rewrite_merge
from app.services.cv_source_dates import date_fix, date_ranges, restore_experience_dates

ROLE = "Hays Recruitment Network Technical Lead"


def _source(period: str) -> str:
    return (
        f"EXPERIENCE\nNetwork Technical Lead\nHays Recruitment\n{period}\nCisco, Meraki"
    )


def test_reported_case_end_date_is_not_turned_into_ongoing():
    fix = date_fix("08.2022 - obecnie", _source("08.2022 – 05.2026"), ROLE)
    assert fix is not None
    assert (fix.current, fix.expected) == ("08.2022 - obecnie", "08.2022 - 05.2026")


@pytest.mark.parametrize(
    "period",
    [
        "Aug 2022 – May 2026",
        "sierpień 2022 - maj 2026",
        "08.2022-05.2026",
        "08/2022 05/2026",
        "01/08/2022 – 31/05/2026",
    ],
)
def test_source_formats(period):
    fix = date_fix("08.2022 - obecnie", _source(period), ROLE)
    assert fix is not None and fix.expected == "08.2022 - 05.2026"


def test_ongoing_in_source_stays_and_wrong_end_goes_back_to_ongoing():
    assert date_fix("03.2022 - obecnie", _source("03/2022 – present"), ROLE) is None
    fix = date_fix("03.2022 - 12.2025", _source("03/2022 – obecnie"), ROLE)
    assert fix is not None and fix.expected == "03.2022 - obecnie"


def test_changed_end_date_goes_back_to_source():
    fix = date_fix("12.2020 - 03.2021", _source("Dec 2020 – Mar 2025"), ROLE)
    assert fix is not None and fix.expected == "12.2020 - 03.2025"


def test_year_only_source_does_not_contradict_month():
    assert date_fix("03.2023 - 05.2026", _source("2023 - 2026"), ROLE) is None
    assert date_fix("2023 - 2026", _source("03.2023 – 05.2026"), ROLE) is None
    fix = date_fix("2023 - currently", _source("2023 - 2026"), ROLE)
    assert fix is not None and fix.expected == "2023 - 2026"


@pytest.mark.parametrize(
    "source",
    [
        # Studia z tym samym początkiem nie zamykają pracy: firmy nie ma obok.
        "Hays Recruitment\n" + "x" * 900 + "\nEDUKACJA Uniwersytet 08.2022 – 05.2026",
        # Dwa okresy z tym samym początkiem: nie wiadomo, który to ten.
        "Hays Recruitment 08.2022 – 05.2026\nHays Recruitment 08.2022 – 12.2024",
        # Okresu nie ma w oryginale albo nie umiemy go przeczytać.
        "Hays Recruitment, pracuję tam od kilku lat",
        "",
    ],
)
def test_unsure_cases_change_nothing(source):
    assert date_fix("08.2022 - obecnie", source, ROLE) is None


def test_role_without_words_or_dates_changes_nothing():
    assert date_fix("08.2022 - obecnie", _source("08.2022 – 05.2026"), "") is None
    assert date_fix("", _source("08.2022 – 05.2026"), ROLE) is None


def test_phone_and_birth_date_are_not_periods():
    assert date_ranges("+48 516 152 644 ur. 14.06.1990 r.") == []


def test_year_in_role_name_does_not_shift_period():
    found = date_ranges("Windows Server 2019 03.2020 - 05.2021")
    assert (found[-1].start, found[-1].end) == ((2020, 3), (2021, 5))


def test_reversed_neighbouring_periods_are_not_a_period():
    assert date_ranges("Brilliant 09.2018 - 06.2014 Acme") == []


def test_merged_promotions_keep_ongoing():
    source = (
        "Hays Recruitment Senior Lead 01.2023 – obecnie\n"
        "Hays Recruitment Lead 08.2022 – 12.2022"
    )
    assert date_fix("08.2022 - obecnie", source, ROLE) is None


def test_generator_fixes_only_false_ongoing():
    source = _source("Dec 2020 – Mar 2025")
    data = {
        "experience": [
            {
                "company": "Hays Recruitment",
                "position": "Lead",
                "dates": "12.2020 - 03.2021",
            }
        ]
    }
    assert restore_experience_dates(data, source) == 0
    assert data["experience"][0]["dates"] == "12.2020 - 03.2021"


def test_generator_fixes_current_month_written_as_end_date():
    data = {
        "experience": [
            {
                "company": "Hays Recruitment",
                "position": "Lead",
                "dates": "02.2025 - 11.2026",
            }
        ]
    }
    source = _source("02.2025 - 09.2026")
    assert restore_experience_dates(data, source, today=date(2026, 11, 2)) == 1
    assert data["experience"][0]["dates"] == "02.2025 - 09.2026"


def test_restore_experience_dates_changes_only_contradicted_roles():
    source = (
        "Hays Recruitment Network Technical Lead 08.2022 – 05.2026\n"
        "Orange Polska Network Engineer 01.2018 – 07.2022"
    )
    data = {
        "experience": [
            {
                "company": "Hays Recruitment",
                "position": "Network Technical Lead",
                "dates": "08.2022 - obecnie",
            },
            {
                "company": "Orange Polska",
                "position": "Network Engineer",
                "dates": "01.2018 - 07.2022",
            },
        ]
    }
    assert restore_experience_dates(data, source) == 1
    assert [j["dates"] for j in data["experience"]] == [
        "08.2022 - 05.2026",
        "01.2018 - 07.2022",
    ]


def _html(period: str) -> str:
    return (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        f'<p data-cv-section="role"><strong>Network Technical Lead</strong> {period}</p>'
        "<p>Hays Recruitment</p><ul><li>Cisco</li></ul>"
    )


def test_html_fix_restores_period_and_keeps_markup():
    result = cv_rewrite_merge.restore_role_dates_html(
        _html("08.2022 - obecnie"), _source("08.2022 – 05.2026")
    )
    assert result is not None
    html, count = result
    assert count == 1
    assert "08.2022 - 05.2026" in html and "obecnie" not in html
    assert "<strong>Network Technical Lead</strong>" in html


def test_html_fix_touches_only_the_chosen_role():
    html = (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><strong>Lead</strong> 08.2022 - obecnie</p><p>Hays Recruitment</p>'
        '<p data-cv-section="role"><strong>Engineer</strong> 01.2018 - 09.2019</p><p>Orange</p>'
    )
    source = "Hays Recruitment 08.2022 – 05.2026\nOrange 01.2018 – 07.2022"
    result = cv_rewrite_merge.restore_role_dates_html(html, source, role_index=1)
    assert result is not None
    assert result[1] == 1
    assert "08.2022 - obecnie" in result[0] and "01.2018 - 07.2022" in result[0]


def test_html_fix_nothing_to_do():
    source = _source("08.2022 – 05.2026")
    result = cv_rewrite_merge.restore_role_dates_html(
        _html("08.2022 - 05.2026"), source
    )
    assert result is not None and result[1] == 0
