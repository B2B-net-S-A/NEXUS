"""Nagłówek CV = nazwa roli od klienta bez dopisków (D2, 13.10.2026).

Tytuły w kształcie produkcyjnym, z fikcyjnymi klientami i numerami.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.cv_service_title_repair import MARKER, planned_change
from app.services.job_working_title import cv_role_title, cv_role_title_for_job


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


def _job(title, role_name=None, client_reference=None):
    return SimpleNamespace(
        title=title,
        client_reference=client_reference,
        client_id=None,
        champion_profile={"basics": {"role_name": role_name}} if role_name else None,
    )


@pytest.mark.parametrize(
    "title,reference,role_name,expected",
    [
        # 02.11.2026: PKO nazywa zapytanie przedmiotem usługi, nie stanowiskiem.
        # Nagłówek „usługi programistyczne – Imię Nazwisko” zgłosił DL.
        (
            "ZOB-3103 usługi programistyczne",
            "ZOB-3156",
            "Senior Fullstack Developer (.NET + React)",
            "Senior Fullstack Developer (.NET + React)",
        ),
        (
            "ZOB-3103 usługi programistyczne - .Net",
            "ZOB-3103",
            "Senior .NET Developer",
            "Senior .NET Developer",
        ),
        ("usługa analizy systemowej ZOB-3092", None, "Analityk", "Analityk"),
        (
            "Usługi programistycznej – Bazy Danych (ZOB-3109)",
            "ZOB-3109",
            "Data Engineer",
            "Data Engineer",
        ),
        (
            "usług programistycznych - Python (ZOB-2995)",
            None,
            "Python Dev",
            "Python Dev",
        ),
        ("Usługa Konsultanta ds. DevOps", None, "DevOps Engineer", "DevOps Engineer"),
        (
            "RFX - Zakup usług Analityka IT_PKN500016126",
            None,
            "Analityk IT",
            "Analityk IT",
        ),
        # Rola w Championie też bywa przepisaną nazwą z numerem.
        (
            "usługi analizy systemowej (ZOB-3059)",
            "ZOB-3059",
            "Analityk Systemowy ZOB-3059 ",
            "Analityk Systemowy",
        ),
    ],
)
async def test_service_title_gives_way_to_champion_role(
    title, reference, role_name, expected
):
    job = _job(title, role_name, reference)
    assert await cv_role_title_for_job(None, job) == expected
    # Potok generacji czyści nagłówek drugi raz: rola ma z tego wyjść bez zmian.
    assert cv_role_title(expected) == expected


@pytest.mark.parametrize(
    "title,role_name,expected",
    [
        # Bez roli w Championie nie ma czym zastąpić — zostaje nazwa od klienta.
        ("usługi programistyczne (ZOB-1)", None, "usługi programistyczne"),
        # Champion przepisał nazwę usługi albo sam kod: to też nie rola.
        ("usługi programistyczne", "Usługi programistyczne", "usługi programistyczne"),
        ("usługi programistyczne", "ZOB-3103", "usługi programistyczne"),
        # Nazwa będąca rolą wygrywa z Championem jak dotąd (D2).
        ("Programista Java (ZOB-2976)", "Senior Java Developer", "Programista Java"),
        # „usług” w środku to część nazwy roli.
        ("Administrator usług IT", "Admin", "Administrator usług IT"),
        ("Programista Usług Integracyjnych", "Dev", "Programista Usług Integracyjnych"),
    ],
)
async def test_champion_role_only_replaces_a_service_title(title, role_name, expected):
    assert await cv_role_title_for_job(None, _job(title, role_name)) == expected


# ── Jednorazowa poprawka CV etapu z nazwą usługi (03.11.2026) ───────────────
# Tu, a nie w nowym pliku: nowy plik przetasował shardy i posadził
# `test_jjit_import.py` za `test_integration_runs.py`, który zostawia otwarte runy JJIT.

ROLE = "Senior Fullstack Developer (.NET + React)"
OLD_FILE = "ZOB-3156_usługi programistyczne_Ewa Fikcyjna.docx"
NEW_FILE = f"ZOB-3156_{ROLE}_Ewa Fikcyjna.docx"


def _html(header: str) -> str:
    return f'<article class="cv"><h1>{header}</h1><hr><p>usługi programistyczne</p></article>'


def _plan(html, filename=OLD_FILE, role=ROLE, blind=False, custom=False):
    return planned_change(html, filename, role, blind=blind, custom_filename=custom)


def test_bad_header_and_file_get_the_role_and_keep_the_person():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"))
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")
    assert change.filename == NEW_FILE
    assert change.old_position == "usługi programistyczne"


def test_only_the_header_changes_in_the_body():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"))
    assert change.html.endswith("<p>usługi programistyczne</p></article>")


def test_dash_inside_the_service_name_stays_out_of_the_person():
    change = _plan(
        _html("Usługi programistycznej – Bazy Danych – Ewa Fikcyjna"),
        filename="ZOB-3109_Usługi programistycznej – Bazy Danych_Ewa Fikcyjna.docx",
    )
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")


def test_blind_header_has_no_person_to_keep():
    change = _plan(_html("usługi programistyczne"), blind=True)
    assert change.html == _html(ROLE)


def test_header_fixed_by_a_person_stays_and_the_file_follows_it():
    change = _plan(_html("Programista Fullstack – Ewa Fikcyjna"))
    assert change.html is None
    assert change.filename == "ZOB-3156_Programista Fullstack_Ewa Fikcyjna.docx"


def test_without_a_role_the_bad_header_and_file_stay():
    bad = _html("usługi programistyczne – Ewa")
    assert _plan(bad, role="usługi programistyczne") is None
    assert _plan(bad, role="") is None


def test_filename_set_by_hand_stays():
    change = _plan(_html("usługi programistyczne – Ewa Fikcyjna"), custom=True)
    assert change.filename is None
    assert change.html == _html(f"{ROLE} – Ewa Fikcyjna")


def test_reserved_characters_leave_the_filename_and_the_header_is_escaped():
    change = _plan(
        _html("usługi programistyczne – Ewa Fikcyjna"),
        role="Data & BI Engineer (SQL / SSIS)",
    )
    assert "<h1>Data &amp; BI Engineer (SQL / SSIS) – Ewa Fikcyjna</h1>" in change.html
    assert change.filename == "ZOB-3156_Data & BI Engineer (SQL SSIS)_Ewa Fikcyjna.docx"


def test_header_with_markup_is_not_guessed():
    change = _plan("<h1><span>usługi programistyczne</span> – Ewa</h1>")
    assert change.html is None
    assert change.filename == NEW_FILE


@pytest.mark.parametrize("filename", [None, "CV_Ewa.docx", "ZOB-1_Tester_Ewa.docx"])
def test_other_files_stay(filename):
    assert _plan(_html("Tester – Ewa"), filename=filename) is None


def test_entrypoint_runs_the_repair_once():
    entrypoint = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    assert f'run_unless_marked "{MARKER}"' in entrypoint
