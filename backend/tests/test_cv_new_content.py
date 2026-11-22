"""Treść „Nowego CV” czytana z HTML-a edytora (`cv_new_content`)."""

from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_new_content import cv_json_from_editor_html

PAYLOAD = {
    "candidate_name": "Jan Przykładowy",
    "position": "Tester oprogramowania",
    "language": "pl",
    "blind": False,
    "highlight_keywords": ["Postman", "Jira"],
    "why_points": [
        "Ponad 8 lat doświadczenia w testowaniu oprogramowania.",
        "Praktyczne doświadczenie z Postmanem i Jirą.",
        "Koordynacja zespołu 6 testerów w projekcie bankowym.",
    ],
    "education": [
        {
            "dates": "2015 - 2020",
            "institution": "Politechnika Przykładowa",
            "degree": "Informatyka, magister inżynier",
            "location": "Kraków, Polska",
        }
    ],
    "skills": [
        {"label": "Testowanie:", "content": "Postman, testy regresyjne, UAT"},
        {"label": "Narzędzia:", "content": "Jira, Git"},
    ],
    "certifications": ["ISTQB Foundation Level (2019)", "Scrum Master (2021)"],
    "languages": ["Polski - ojczysty", "Angielski - C1"],
    "experience": [
        {
            "position": "Starszy tester",
            "dates": "01.2022 - obecnie",
            "company": "Firma Alfa",
            "technologies": ["Postman", "Jira"],
            "responsibilities": ["Testy API.", "Raportowanie defektów."],
        },
        {
            "position": "Tester",
            "dates": "03.2018 - 12.2021",
            "company": "Firma Beta",
            "technologies": ["Selenium"],
            "responsibilities": ["Testy manualne."],
        },
    ],
}
FALLBACK = {
    "name": "Jan Przykładowy",
    "position": "Tester oprogramowania",
    "highlight_keywords": ["UAT"],
    "experience": [
        {
            "position": "Starszy tester",
            "company": "Firma Alfa",
            "dates": "01.2022 - obecnie",
            "industry": "Bankowość",
        }
    ],
}


def _html(**overrides):
    return render_interactive_html({**PAYLOAD, **overrides}, None, document_only=True)


def test_generator_html_round_trips_to_generator_shape():
    content = cv_json_from_editor_html(_html(), fallback=FALLBACK)
    data = content.cv_json
    assert data["name"] == "Jan Przykładowy"
    assert data["position"] == "Tester oprogramowania"
    assert len(data["why_points"]) == 3
    assert "**Postman**" in data["why_points"][1] or "Postman" in data["why_points"][1]
    assert [r["company"] for r in data["experience"]] == ["Firma Alfa", "Firma Beta"]
    first = data["experience"][0]
    assert first["position"] == "Starszy tester"
    assert first["dates"] == "01.2022 - obecnie"
    assert first["technologies"] == ["Postman", "Jira"]
    assert first["responsibilities"] == ["Testy API.", "Raportowanie defektów."]
    assert first["industry"] == "Bankowość"
    assert data["experience"][1]["industry"] == ""
    assert data["skills"][0] == {
        "label": "Testowanie:",
        "content": "Postman, testy regresyjne, UAT",
    }
    assert data["education"] == [
        {
            "dates": "2015 - 2020",
            "institution": "Politechnika Przykładowa",
            "degree": "Informatyka, magister inżynier",
            "location": "Kraków, Polska",
        }
    ]
    assert data["certifications"] == PAYLOAD["certifications"]
    assert data["languages"] == ["Polski - ojczysty", "Angielski - C1"]
    assert "UAT" in data["highlight_keywords"]
    assert "Postman" in data["highlight_keywords"]
    assert content.rodo_clause.startswith("Wyrażam zgodę")
    assert content.unmapped_sections == ()


def test_editor_edits_win_over_generator_record():
    edited = (
        _html()
        .replace("Starszy tester", "Lider testów")
        .replace("Testy API.", "Testy API i kontraktów.")
    )
    data = cv_json_from_editor_html(edited, fallback=FALLBACK).cv_json
    role = data["experience"][0]
    assert role["position"] == "Lider testów"
    assert role["responsibilities"][0] == "Testy API i kontraktów."
    # Branża pasuje po firmie i dacie, gdy zmieniono tytuł stanowiska.
    assert role["industry"] == "Bankowość"


def test_tiptap_flat_document_without_wrappers():
    flat = (
        "<h1>Tester oprogramowania – Jan Przykładowy</h1><hr>"
        '<h2 data-cv-section="why_points">Dlaczego nasz kandydat?</h2>'
        "<ul><li><p>Ponad <strong>8 lat</strong> w QA.</p></li></ul>"
        '<h2 data-cv-section="education">Edukacja</h2>'
        "<p>2015 - 2020 <strong>Politechnika Przykładowa</strong> — Informatyka · Kraków</p>"
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><strong>Tester</strong> 2018 - 2021</p>'
        '<p data-cv-section="employer">Firma Beta</p>'
        '<p data-cv-section="duties_label">Zakres zadań:</p>'
        "<ul><li><p>Testy manualne.</p></li></ul>"
        '<p data-cv-section="technologies">Technologie: Selenium, Java</p>'
        '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie danych.</p>'
    )
    content = cv_json_from_editor_html(flat, fallback={"name": "Jan Przykładowy"})
    data = content.cv_json
    assert data["why_points"] == ["Ponad **8 lat** w QA."]
    assert data["education"][0]["institution"] == "Politechnika Przykładowa"
    assert data["education"][0]["degree"] == "Informatyka"
    assert data["education"][0]["location"] == "Kraków"
    role = data["experience"][0]
    assert role == {
        "position": "Tester",
        "dates": "2018 - 2021",
        "company": "Firma Beta",
        "industry": "",
        "technologies": ["Selenium", "Java"],
        "responsibilities": ["Testy manualne."],
    }
    assert content.rodo_clause == "Wyrażam zgodę na przetwarzanie danych."


def test_legacy_html_without_markers_reads_roles_by_shape():
    legacy = (
        "<h1>Analityk – Anna Testowa</h1>"
        "<h2>DOŚWIADCZENIE</h2>"
        "<p><b>Analityk systemowy</b> 05.2019 - obecnie</p>"
        "<p>Firma Gamma</p>"
        "<p>Zakres zadań:</p><ul><li>Analiza wymagań.</li></ul>"
        "<p>Technologie: SQL, UML</p>"
    )
    data = cv_json_from_editor_html(legacy).cv_json
    assert data["name"] == "Anna Testowa"
    assert data["experience"][0]["company"] == "Firma Gamma"
    assert data["experience"][0]["responsibilities"] == ["Analiza wymagań."]
    assert data["experience"][0]["technologies"] == ["SQL", "UML"]


def test_blind_cv_has_no_name_even_when_title_has_one():
    data = cv_json_from_editor_html(
        _html(blind=True), blind=True, fallback=FALLBACK
    ).cv_json
    assert data["name"] == ""
    assert data["blind_cv"] is True
    assert data["position"] == "Tester oprogramowania"


def test_english_cv_sections_and_unknown_section_is_reported():
    english = _html(language="en").replace(
        "</article>", "<h2>Hobby</h2><p>Chess</p></article>"
    )
    content = cv_json_from_editor_html(english, language="en", fallback=FALLBACK)
    assert content.cv_json["language"] == "en"
    assert len(content.cv_json["experience"]) == 2
    assert content.unmapped_sections == ("Hobby",)


def test_empty_html_gives_empty_content():
    content = cv_json_from_editor_html("", fallback=FALLBACK)
    assert content.cv_json["experience"] == []
    assert content.cv_json["name"] == "Jan Przykładowy"
    assert content.rodo_clause == ""
