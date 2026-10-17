"""Stawki i dostępność nie idą z notatek do modelu generatora CV (13.10.2026)."""

import time

import pytest

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


@pytest.mark.parametrize(
    "note",
    [
        "Oczekiwania: 20 000 PLN netto B2B",
        "Oczekuje 22k netto",
        "Chce 160 zł netto",
        "Budżet kandydata: 18 000 PLN",
        "Ma ofertę za 200 PLN dziennie",
        "Wypowiedzenie 1 miesiąc",
        "1 miesiąc wypowiedzenia",
        "Kandydat dostępny od 1 listopada.",
        "Dostępna od zaraz",
    ],
)
def test_candidate_money_and_notice_leave_the_note(note):
    # Przegląd PR 1: oczekiwania i oferty bez słowa „stawka” szły do modelu.
    assert strip_rates_and_availability(note) == ""


@pytest.mark.parametrize(
    "fact",
    [
        "Wdrożył API dostępne w chmurze Azure, użył Kafki.",
        "Aplikacja dostępna na iOS i Androida.",
        "Zarządzał budżetem 2 mln PLN.",
        "Programuje w .NET 8 od 2019 roku.",
    ],
)
def test_facts_about_systems_and_projects_stay(fact):
    assert strip_rates_and_availability(fact) == fact


# ── Koszt (17.10.2026) ──────────────────────────────────────────────────────
# Notatki, odpowiedzi kandydata i tekst z AI w edytorze trafiają tu bez limitu
# długości. Do 17.10.2026 „stawka” + 4 tys. spacji albo „1  1  1…” liczyły się
# sekundami — wzorce wracały kwadratowo.

K = 20_000
CPU_LIMIT = 2.0


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("wynagrodzenie" + "to" * K + "x", id="glued_word"),
        pytest.param("stawka" + " " * K + "x", id="spaces_after_rate_word"),
        pytest.param("1" * K + "x", id="digits"),
        pytest.param("1 " * K + "x", id="digit_space"),
        pytest.param("1  " * K + "x", id="digit_two_spaces"),
        pytest.param("1." * K + "x", id="digit_dot"),
        pytest.param("1 . " * K + "x", id="digit_space_dot"),
        pytest.param("1 zł, " * K, id="many_amounts"),
    ],
)
def test_rate_checks_are_linear(text):
    for check in (is_rate_text, strip_rates_and_availability):
        start = time.process_time()
        check(text)
        spent = time.process_time() - start
        assert spent < CPU_LIMIT, f"{check.__name__}: {spent:.2f} s"
