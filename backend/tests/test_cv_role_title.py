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
        # 21.10.2026: nazwa roli zapisana jako numer u klienta — nagłówek był
        # samym „(43020)”. Bez liter to nie rola: liczymy z pełnej nazwy.
        (
            "PL_IT_Developer_expert_TP#40379 (43020)",
            "PL_IT_Developer_expert_TP#40379",
            ["Bank Północny"],
            "IT Developer expert",
        ),
        # 26.10.2026 (decyzja D4): kod stanowiska „TP#…”, „PeP: …”, kraj „PL_”
        # i „Replacement for <imię>” szły do nagłówka CV i do zaproszenia na
        # prep. Kształty z produkcji, imiona fikcyjne.
        (
            "PL_IT_Developer_expert_TP#40379 (43020)",
            "43020",
            ["Bank Północny"],
            "IT Developer expert",
        ),
        (
            "Bank Północny: PL - MDM - IT Automation Tester Senior - TP#41745 (42553)",
            "42553",
            ["Bank Północny"],
            "MDM - IT Automation Tester Senior",
        ),
        (
            "PL_Transaction Monitoring_IT Developer Expert_TP#45785 (42928)(42927)",
            "42928, 42927",
            [],
            "Transaction Monitoring – IT Developer Expert",
        ),
        (
            "Retail Technology Services_Role: CICD Engineer_PeP: 4985 (42883)",
            "42883",
            [],
            "CICD Engineer",
        ),
        (
            "PEP4989_Domain API_Junior IT Analyst (replacement) (42970)",
            "42970",
            [],
            "Domain API – Junior IT Analyst",
        ),
        (
            "Replacement- PL- GETFIT Senior Test Automation Engineer TP ID 40942 (42283)",
            "42283",
            [],
            "GETFIT Senior Test Automation Engineer",
        ),
        (
            "PL_IngestOps - CoreCDP - Replacement for Jan K (42718)",
            "42718",
            [],
            "IngestOps - CoreCDP",
        ),
        ("1 X Scrum Master Replacement for Anna", None, [], "Scrum Master"),
        (
            "Portfolio Oversight Management - SREP EBA LOM Replacement for Jan Nowak",
            None,
            [],
            "Portfolio Oversight Management - SREP EBA LOM",
        ),
        (
            "Bank Północny: PL_KYC_IT Automation Tester Senior_TP#43800 (42524)",
            "42524",
            ["Bank Północny"],
            "KYC – IT Automation Tester Senior",
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
        # 26.10.2026: reguły Nordei nie tną ról z „PL” ani „x” w nazwie.
        "PL/SQL Developer",
        "Replacement Planner",
        "Expert IT Analyst",
        # Przegląd PR-a: „PL-SQL” to technologia, a „Role:” w środku nazwy
        # to nie prefiks Nordei.
        "PL-SQL Developer",
        "PL_SQL Developer",
        "Data Engineer (Key Role: Payments)",
        "Senior C# Developer",
    ],
)
def test_real_role_names_are_not_cut(title):
    assert cv_role_title(title) == title


def test_role_is_never_translated_or_emptied():
    assert cv_role_title("Data Platform Developer") == "Data Platform Developer"
    assert cv_role_title("(12345)") == "(12345)"
    assert cv_role_title("") == ""
    assert cv_role_title(None) == ""
