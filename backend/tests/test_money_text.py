"""Stawki i dostępność nie idą z notatek do modelu generatora CV (13.10.2026)."""

from app.services.money_text import is_rate_text, strip_rates_and_availability


def test_rate_and_availability_leave_the_note_and_facts_stay():
    note = (
        "150 PLN/h + VAT, Lublin, Praca zdalna, dostępny 06.03.2023 r. "
        "W Javie pracuje od 2018."
    )
    text = strip_rates_and_availability(note)
    assert "150" not in text and "PLN" not in text
    assert "dostępny" not in text and "06.03.2023" not in text
    assert "W Javie pracuje od 2018." in text


def test_rate_word_with_amount_is_a_rate_and_project_budget_is_not():
    assert is_rate_text("Stawka 140 zł")
    assert is_rate_text("oczekuje 1200 zł/md")
    assert not is_rate_text("Projekt o budżecie 2 mln zł")
    assert "2 mln zł" in strip_rates_and_availability("Projekt o budżecie 2 mln zł.")


def test_system_availability_and_decimal_commas_survive():
    text = "Utrzymywał dostępność systemu 99,9%, pracował 1,5 roku z Kafką."
    assert strip_rates_and_availability(text) == text


def test_empty_input():
    assert strip_rates_and_availability(None) == ""
    assert strip_rates_and_availability("") == ""
