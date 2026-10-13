"""Strażnik terminów generatora CV — poprawki po audycie 13.10.2026 (pkt 11).

Strażnik (``strip_unsupported_terms``) wycinał prawdziwe umiejętności: skrót
z wymagań przy pełnej nazwie w CV („AWS” ↔ „Amazon Web Services”, GCP, CI/CD,
TDD, OOP, ML) i zwykłe słowa, gdy CV jest w innym języku niż wymagania
i wynikowe CV („Test automation” przy „testowanie automatyczne”). Reguła:
wątpliwość = termin zostaje, z uwagą do sprawdzenia. Dane fikcyjne.
"""

import pytest

from app.services.cv_generator_b2b.legacy_v7._helpers import strip_unsupported_terms


def _run(cv_text, requirements, items, language="en", notes=""):
    data = {
        "experience": [{"technologies": list(items)}],
        "skills": [{"label": "X", "content": ", ".join(items)}],
    }
    warnings = strip_unsupported_terms(
        data,
        cv_text=cv_text,
        screening_notes_text=notes,
        requirements=requirements,
        language=language,
    )
    skills = data["skills"][0]["content"] if data["skills"] else ""
    return data["experience"][0]["technologies"], skills, warnings


_EN_CV = (
    "Senior developer. Built continuous integration and delivery pipelines in "
    "Jenkins. Test-driven development, object-oriented programming, machine "
    "learning models in Python, Amazon Web Services (Lambda, S3), Google Cloud "
    "Platform, Microsoft SQL Server, Power BI dashboards."
)


def test_abbreviation_in_requirements_matches_full_name_in_cv():
    items = ["CI/CD", "TDD", "OOP", "ML", "AWS", "GCP", "MS SQL", "Power BI", "Python"]
    techs, skills, warnings = _run(_EN_CV, items, items)
    assert techs == items
    assert skills == ", ".join(items)
    assert warnings == []


@pytest.mark.parametrize(
    "cv_text,term",
    [
        ("Skills: AWS (EC2), GCP, CI/CD", "Amazon Web Services"),
        ("Skills: AWS (EC2), GCP, CI/CD", "Google Cloud Platform"),
        ("Umiejętności: ciągła integracja i wdrażanie w Jenkinsie", "CI/CD"),
        ("Projekty z uczeniem maszynowym w Pythonie", "ML"),
        ("Programowanie obiektowe w Javie", "OOP"),
    ],
)
def test_full_name_and_abbreviation_match_both_ways(cv_text, term):
    techs, _, warnings = _run(cv_text, [term], [term], language="pl")
    assert techs == [term]
    assert warnings == []


def test_polish_cv_english_requirements_keep_plain_skills_with_a_note():
    cv = (
        "Doświadczenie: testowanie automatyczne aplikacji webowych w Selenium, "
        "zarządzanie projektami, przegląd kodu."
    )
    items = ["Test automation", "Project management", "Code review", "Selenium"]
    techs, skills, warnings = _run(cv, items, items, language="en")
    assert techs == items
    assert skills == ", ".join(items)
    joined = " ".join(warnings)
    assert "removed" not in joined
    assert "Test automation" in joined and "Code review" in joined


def test_english_cv_polish_requirements_keep_plain_skills_with_a_note():
    cv = "Experience: automated testing of web apps with Selenium, project management, code reviews."
    items = ["Testy automatyczne", "Zarządzanie projektami", "Przegląd kodu"]
    techs, skills, warnings = _run(cv, items, items, language="pl")
    assert techs == items
    assert skills == ", ".join(items)
    joined = " ".join(warnings)
    assert "usunięto" not in joined
    assert "WERYFIKUJ" in joined and "Przegląd kodu" in joined


def test_polish_cv_keeps_english_plain_term_copied_from_requirements():
    # Wynikowe CV po polsku, model przepisał „Code review” z wymagań, a CV
    # mówi „przegląd kodu” — innym językiem, ale to ta sama umiejętność.
    cv = "Programista Java w banku. Przegląd kodu, testy jednostkowe w JUnit."
    techs, _, warnings = _run(cv, ["Code review"], ["Code review"], language="pl")
    assert techs == ["Code review"]
    assert warnings and "usunięto" not in " ".join(warnings)


@pytest.mark.parametrize("technology", ["OpenTelemetry", "Spring Boot"])
@pytest.mark.parametrize("language", ["en", "pl"])
def test_technology_only_from_question_still_leaves(technology, language):
    # D3 zostaje: nazwa technologii nie ma tłumaczenia, więc inny język CV nie
    # jest wątpliwością.
    cv = "Doświadczenie: monitoring w Grafanie i Prometheusie, alerty dla zespołu."
    notes = f"P: Czy pracował Pan z {technology}?\nO: Tylko z Grafaną."
    techs, skills, warnings = _run(
        cv, [], ["Grafana", technology], language=language, notes=notes
    )
    assert techs == ["Grafana"]
    assert skills == "Grafana"
    assert technology in " ".join(warnings)


def test_plain_requirement_absent_from_same_language_cv_still_leaves():
    # Wypełniacz z wymagań w tym samym języku co CV dalej znika.
    cv = "Backend developer. Built REST APIs in Java and Spring Boot for a bank."
    techs, _, warnings = _run(
        cv, ["Project management"], ["Java", "Project management"], language="en"
    )
    assert techs == ["Java"]
    assert "Project management" in " ".join(warnings)
