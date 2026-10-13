"""Czytanie frazy wymagania (13.10.2026) — wariant A: dwie listy.

Przypadki z pomiaru na produkcji: zdania, branże, języki i umiejętności
miękkie z „musi mieć” nie znajdują nikogo jako słowa kluczowe, a technologia
z komentarzem w nawiasie wypadała z bramki. Czyste testy, bez bazy.
"""

import pytest

from app.services.requirement_phrase import read_phrase, suggestions_for
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "SQL": ("database", ()),
    "JMeter": ("qa", ()),
    "REST API": ("api", ("rest",)),
}


def _read(text: str):
    with hydrated_taxonomy(SKILLS):
        return read_phrase(text)


@pytest.mark.parametrize(
    "text, keyword, talk_text",
    [
        ("SQL (bardzo dobra znajomość)", "SQL", "SQL — bardzo dobra znajomość"),
        ("Bardzo dobra znajomość SQL", "SQL", "Bardzo dobra znajomość SQL"),
        # Opis narzędzia to nie poziom — komentarz bez pozycji do rozmowy.
        ("JMeter (narzędzie do testowania wydajności)", "JMeter", None),
        ("Java", "Java", None),
    ],
)
def test_technology_with_comment_keeps_the_word_and_moves_the_level(
    text, keyword, talk_text
):
    reading = _read(text)
    assert reading.keyword == keyword
    assert reading.talk_text == talk_text
    assert reading.needs_decision is False
    assert reading.kind == "technology"


def test_sentence_needs_a_decision_and_suggests_searchable_words():
    reading = _read("doświadczenie w przetargach")
    assert reading.kind == "prose"
    assert reading.needs_decision is True
    assert reading.keyword is None
    assert reading.talk == "skills"
    assert reading.talk_text == "doświadczenie w przetargach"
    # Rdzeń z gwiazdką i odpowiedniki z listy prowadzonej przez człowieka.
    assert reading.suggestions[0] == "przetarg*"
    assert {"PZP", "SIWZ"} <= set(reading.suggestions)


def test_sentence_with_a_technology_suggests_the_technology_first():
    with hydrated_taxonomy(SKILLS):
        suggestions = suggestions_for("Integracja danych z wykorzystaniem REST API")
    assert suggestions[0] == "REST API"


@pytest.mark.parametrize(
    "text, kind, talk",
    [
        ("Język angielski min. B2", "language", "language"),
        ("angielski B2", "language", "language"),
        ("Stakeholder management", "soft", "skills"),
        ("doświadczenie w bankowości", "domain", "domains"),
    ],
)
def test_things_to_check_in_the_interview(text, kind, talk):
    reading = _read(text)
    assert (reading.kind, reading.talk, reading.needs_decision) == (kind, talk, True)
    assert reading.keyword is None


def test_single_domain_word_stays_a_keyword_with_hints():
    reading = _read("bankowość")
    assert reading.kind == "domain"
    assert reading.needs_decision is False
    assert reading.keyword == "bankowość"
    assert "bankow*" in reading.suggestions


def test_city_is_not_a_requirement_word():
    reading = _read("Warszawa")
    assert reading.kind == "city"
    assert reading.needs_decision is True


@pytest.mark.parametrize("text", ["mikroserwisy", "Scrum"])
def test_categories_stay_keywords_without_decision(text):
    reading = _read(text)
    assert reading.needs_decision is False
    assert reading.keyword == text


def test_talk_item_is_capped_at_section_limit():
    long_text = "Doświadczenie " + "bardzo długie zdanie klienta " * 12
    reading = _read(long_text)
    assert reading.talk_text is not None and len(reading.talk_text) <= 160


def test_reading_serialises_for_the_api():
    data = _read("doświadczenie w przetargach").as_dict()
    assert data["kind"] == "prose"
    assert isinstance(data["suggestions"], list)
