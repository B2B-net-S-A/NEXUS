"""Odmiana technologii i jednoliterowe nazwy — wspólne reguły (audyt 06.10.2026)."""

from __future__ import annotations

from app.services.skill_inflection import dictionary_base_name, inflected_in_text
from app.services.skill_normalize import cut_at_word, is_single_letter_skill
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

WITH_C = {**PROD_LIKE_SKILLS, "C": ("language", ()), "R": ("language", ())}


def test_inflected_dictionary_technology_gets_its_base_name():
    with hydrated_taxonomy():
        assert dictionary_base_name("Javy") == "Java"
        assert dictionary_base_name("Dockerem") == "Docker"
        assert dictionary_base_name("Pythonie") == "Python"
        assert dictionary_base_name("javy") == "java"
        # Już forma podstawowa i słowo spoza słownika — nic do zmiany.
        assert dictionary_base_name("Java") is None
        assert dictionary_base_name("bankowości") is None
        assert dictionary_base_name("Spring Boota") is None


def test_inflected_form_found_in_folded_text():
    with hydrated_taxonomy():
        assert inflected_in_text("Java", "znajomosc javy i springa")
        assert inflected_in_text("Docker", "doswiadczenie z dockerem")
        # „Java” nie trafia w „JavaScript” — końcówki to zamknięta lista.
        assert not inflected_in_text("Java", "znajomosc javascriptu")


def test_single_letter_skill_only_from_the_dictionary():
    with hydrated_taxonomy(WITH_C):
        assert is_single_letter_skill("C")
        assert is_single_letter_skill("r")
        assert not is_single_letter_skill("X")
        assert not is_single_letter_skill("C#")
    # Bez słownika pojedyncza litera to zawsze szum.
    assert not is_single_letter_skill("C")


def test_cut_at_word_never_breaks_a_word():
    assert cut_at_word("krótkie", 100) == "krótkie"
    assert cut_at_word("ala ma kota", 9) == "ala ma"
    assert cut_at_word("x" * 20, 10) == "x" * 10
