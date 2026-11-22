"""Dopiski o stopniu znajomości w umiejętnościach CV (17.11.2026, wariant A+B).

Zgłoszenie z zespołu: generator pisał „Cucumber (krótkie doświadczenie
praktyczne)”, „Java (podstawy)”. Klient czyta to jako brak umiejętności.
Na kopii produkcji z 16.11 takie dopiski miało 64 z 958 CV z 30 dni.
Decyzja Artura: dopisek znika, technologia zostaje i schodzi na koniec
kategorii (chyba że jest wymaganiem klienta), rekruter dostaje uwagę.
"""

import pytest

from app.services.cv_generator_b2b.legacy_v7._helpers import strip_unsupported_terms

CV = (
    "Selenium WebDriver Cucumber SpecFlow WebdriverIO Next.js SQL Java C# "
    "JavaScript C++ Angular HTML CSS Power BI DAX Power Query Docker Kubernetes"
)


def _run(content: str, *, requirements=(), language="pl"):
    data = {"experience": [], "skills": [{"label": "Kategoria:", "content": content}]}
    warnings = strip_unsupported_terms(
        data,
        cv_text=CV,
        screening_notes_text="",
        requirements=list(requirements),
        language=language,
    )
    return data["skills"][0]["content"], warnings


def test_reported_case_drops_note_and_moves_item_to_the_end():
    content, warnings = _run(
        "Selenium WebDriver, Cucumber (krótkie doświadczenie praktyczne), "
        "SpecFlow, WebdriverIO, Next.js"
    )
    assert content == "Selenium WebDriver, SpecFlow, WebdriverIO, Next.js, Cucumber"
    joined = " ".join(warnings)
    assert "WERYFIKUJ" in joined
    assert "Cucumber (krótkie doświadczenie praktyczne)" in joined


def test_several_basic_items_keep_their_order_at_the_end():
    content, _ = _run("SQL, Java (podstawy), C#, JavaScript (podstawy), C++ (podstawy)")
    assert content == "SQL, C#, Java, JavaScript, C++"


@pytest.mark.parametrize(
    "item",
    [
        "Angular (basic)",
        "Angular (basic level)",
        "Angular (poziom podstawowy)",
        "Angular (podstawowa znajomość)",
        "Angular (znajomość teoretyczna)",
        "Angular (ograniczone doświadczenie)",
        "Angular (some familiarity)",
        "Angular (wskazane w CV, bez potwierdzonego użycia komercyjnego)",
        "Angular (doświadczenie niekomercyjne)",
        "Angular - podstawowa znajomość",
        "Angular – basic",
    ],
)
def test_level_notes_are_removed_in_both_languages(item):
    content, warnings = _run(f"{item}, Docker")
    assert content == "Docker, Angular"
    assert warnings


def test_scope_in_brackets_stays_and_only_the_level_part_goes():
    content, _ = _run(
        "Power BI (DAX, Power Query), Docker (basic, Docker Compose), Kubernetes"
    )
    assert content == "Power BI (DAX, Power Query), Kubernetes, Docker (Docker Compose)"


def test_positive_or_neutral_notes_stay_in_place():
    content, warnings = _run("Java (10+ lat), SQL (zaawansowana znajomość), Docker")
    assert content == "Java (10+ lat), SQL (zaawansowana znajomość), Docker"
    assert warnings == []


def test_client_requirement_keeps_its_place_without_the_note():
    content, _ = _run(
        "Cucumber (krótkie doświadczenie praktyczne), Selenium WebDriver, SpecFlow",
        requirements=["Cucumber"],
    )
    assert content == "Cucumber, Selenium WebDriver, SpecFlow"


def test_english_warning():
    _, warnings = _run("Angular (basic), HTML", language="en")
    assert any("VERIFY" in w and "Angular (basic)" in w for w in warnings)


def test_no_experience_note_still_removes_the_whole_item():
    content, _ = _run(
        "Iceberg (podstawowa znajomość, brak praktycznego doświadczenia), Docker"
    )
    assert content == "Docker"


@pytest.mark.parametrize(
    "item,expected",
    [
        # Przebieg po 36 017 pozycjach ze stagingu (17.11): myślnik w pozycji
        # ze średnikami nie może uciąć wszystkiego po nim.
        (
            "Linux - podstawy; macOS; iOS; TeamViewer - zdalne usuwanie usterek",
            "Linux; macOS; iOS; TeamViewer - zdalne usuwanie usterek",
        ),
        ("Postman (REST API - poziom podstawowy)", "Postman (REST API)"),
        (
            "automatyzacja testów (Python, Selenium WebDriver, Robot Framework - "
            "podstawowa znajomość)",
            "automatyzacja testów (Python, Selenium WebDriver, Robot Framework)",
        ),
        (
            "Data Analysis & Reporting (Excel, SQL and Splunk basics)",
            "Data Analysis & Reporting (Excel, SQL and Splunk)",
        ),
        (
            "Power BI (dashboards, data modeling, basic DAX)",
            "Power BI (dashboards, data modeling, DAX)",
        ),
        (
            "Angular (basic knowledge; practical experience with smaller changes)",
            "Angular",
        ),
        ("Snowflake - znajomość podstawowa", "Snowflake"),
        (
            "Google Cloud Platform (podstawy, rozwijane samodzielnie)",
            "Google Cloud Platform",
        ),
    ],
)
def test_real_staging_items_keep_every_real_skill(item, expected):
    content, _ = _run(item)
    assert content == expected


@pytest.mark.parametrize(
    "content",
    [
        "VBA (Visual Basic for Applications), Docker",
        "Check Point (GAIA, Identity Awareness, SmartView), Docker",
    ],
)
def test_product_names_are_not_levels(content):
    kept, warnings = _run(content)
    assert kept == content
    assert warnings == []
