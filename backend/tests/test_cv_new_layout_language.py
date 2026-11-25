"""Języki na stronie 1 „Nowego CV” — zapis z myślnikiem bez spacji (pętla jakości 25.11.2026)."""

from __future__ import annotations

import pytest

from app.services.cv_new_layout.facts import lang_code, lang_parts


@pytest.mark.parametrize(
    ("entry", "name", "level"),
    [
        ("Polish-fluent.", "Polish", "fluent"),
        ("polski-ojczysty", "polski", "ojczysty"),
        ("Serbo-Croatian", "Serbo-Croatian", ""),
        ("English - C1", "English", "C1"),
    ],
)
def test_language_with_hyphen_without_spaces(entry, name, level):
    """#40503: „Polish-fluent.” dawało pastylkę „PO” bez poziomu; myślnik bez spacji dzieli
    tylko po znanej nazwie języka."""
    assert lang_parts(entry) == (name, level)
    if name.lower() in ("polish", "polski"):
        assert lang_code(name) == "PL"


@pytest.mark.parametrize(
    ("entry", "name", "level"),
    [
        ("Angielski B2", "Angielski", "B2"),
        ("English -B2", "English", "B2"),
        ("English (reading/listening) - C1", "English (reading/listening)", "C1"),
        ("Esperanto – B2.", "Esperanto", "B2"),
    ],
)
def test_language_without_dash_or_with_half_dash(entry, name, level):
    """Przegląd 2749 wpisów (25.11.2026): „Angielski B2” i „English -B2” gubiły poziom."""
    assert lang_parts(entry) == (name, level)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("English (reading/listening)", "EN"),
        ("Persian", "FA"),
        ("Perski", "FA"),
        ("Azari", "AZ"),
        ("Wietnamski", "VI"),
        ("Łacina", "LA"),
        ("Esperanto", "EO"),
    ],
)
def test_more_language_codes(name, code):
    assert lang_code(name) == code


def test_level_not_specified_is_not_shown_as_level():
    from app.services.cv_new_layout.page1 import shown_language

    assert shown_language("level not specified", "en") == ""
    assert shown_language("poziom nieokreślony", "pl") == ""


def test_role_paragraphs_after_languages_without_experience_heading():
    """#22485: w edytorze zniknął nagłówek „EXPERIENCE” — stanowiska szły do języków,
    a doświadczenie było puste."""
    from app.services.cv_new_content import cv_json_from_editor_html

    html = (
        "<h1>QA – Jan Test</h1>"
        '<h2 data-cv-section="languages">LANGUAGES</h2><p>Polish - native · English - C1</p>'
        '<p data-cv-section="role"><strong>Quality Engineer</strong> 03.2026 - Present</p>'
        '<p data-cv-section="employer">Comscore</p>'
        '<p data-cv-section="duties_label">Tasks:</p><ul><li><p>Testing.</p></li></ul>'
    )
    cj = cv_json_from_editor_html(
        html, language="en", blind=False, fallback=None
    ).cv_json
    assert cj["languages"] == ["Polish - native", "English - C1"]
    assert [(e["position"], e["company"], e["dates"]) for e in cj["experience"]] == [
        ("Quality Engineer", "Comscore", "03.2026 - Present")
    ]
