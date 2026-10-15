"""Nagłówek CV = nazwa roli od klienta bez dopisków (D2, 13.10.2026).

Tytuły w kształcie produkcyjnym, z fikcyjnymi klientami i numerami.
"""

import pytest

from app.services.job_working_title import cv_role_title


@pytest.mark.parametrize(
    "title,reference,clients,expected",
    [
        (
            "Bank Północny: PRJ 4412 - Data Platform Developer (51234)",
            None,
            ["Bank Północny"],
            "Data Platform Developer",
        ),
        (
            "Bank Północny: BCCM RRP: SP1 Business Analyst - MVB project (42752)",
            None,
            ["Bank Północny"],
            "Business Analyst",
        ),
        (
            "Poland - Warsaw/Gdansk/Gdynia IT Analyst (Senior) (42939)",
            None,
            [],
            "IT Analyst (Senior)",
        ),
        ("PL-EBSD-IT Analyst Senior (42819)", None, [], "IT Analyst Senior"),
        (
            "Analityk biznesowo-systemowy  x1 CZII  Zamówienie 18",
            None,
            [],
            "Analityk biznesowo-systemowy",
        ),
        (
            "Tester Automatyzujący / Tester Danych Senior (ZOB-2949)",
            "ZOB 2949",
            [],
            "Tester Automatyzujący / Tester Danych Senior",
        ),
        (
            "RFX-wsparcie w utrzymaniu i rozwoju Power BI_PKN500023226",
            None,
            [],
            "Wsparcie w utrzymaniu i rozwoju Power BI",
        ),
        ("AI Engineer MID (ZOB-2536) - 3.iteracja", None, [], "AI Engineer MID"),
        (
            "Mobile Developer Android/Kotlin (dodatkowy profil)",
            None,
            [],
            "Mobile Developer Android/Kotlin",
        ),
        ("Analityk Systemowy ZOB-3054", None, [], "Analityk Systemowy"),
        (
            "Senior Software Developer RITM0864052",
            None,
            [],
            "Senior Software Developer",
        ),
        ("LowCode Developer (ITVM-5894)", None, [], "LowCode Developer"),
        ("Polska - Java Developer", None, [], "Java Developer"),
        ("Poland - Remote - Data Engineer", None, [], "Data Engineer"),
        # 15.10.2026: numer z nazwy trafia do `client_reference` — nagłówek
        # nie może zostać z „_” po zdjętym kodzie.
        (
            "RFX-wsparcie w utrzymaniu i rozwoju Power BI_PKN500023226",
            "PKN500023226",
            [],
            "Wsparcie w utrzymaniu i rozwoju Power BI",
        ),
        ("Tester_PKN/5/000177/26", "PKN/5/000177/26", [], "Tester"),
        ("Kierownik projektu_EITE500011826", "EITE500011826", [], "Kierownik projektu"),
        (
            "Senior Software Developer_RITM0864052",
            "RITM0864052",
            [],
            "Senior Software Developer",
        ),
        (
            "Bank Północny: Data Platform Developer (51234)(51235)",
            "51234, 51235",
            ["Bank Północny"],
            "Data Platform Developer",
        ),
    ],
)
def test_client_codes_and_process_notes_leave_the_header(
    title, reference, clients, expected
):
    assert cv_role_title(title, reference, clients) == expected


@pytest.mark.parametrize(
    "title",
    [
        "ISO 27001 Auditor",
        "UI-UX Designer",
        "SAP-ABAP Developer",
        "Java Developer",
        # Przegląd PR 1: technologia z cyfrą na początku i małe litery marki.
        "iOS Developer",
        "macOS Administrator",
        "dbt Engineer",
        "MS365 Administrator",
        "DB2 Administrator",
        "TM1 Specialist",
        "ES6 Developer",
        "SQL: Administrator",
        "AWS: DevOps Engineer",
        "Security Engineer (ISO 27001)",
        "Data Analyst (PL-300)",
        "Azure Architect (AZ-305)",
    ],
)
def test_real_role_names_are_not_cut(title):
    assert cv_role_title(title) == title


def test_role_is_never_translated_or_emptied():
    assert cv_role_title("Data Platform Developer") == "Data Platform Developer"
    assert cv_role_title("(12345)") == "(12345)"
    assert cv_role_title("") == ""
    assert cv_role_title(None) == ""
