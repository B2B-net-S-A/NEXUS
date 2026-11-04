"""Stawki i dostępność w notatkach dla generatora CV — poprawki po audycie 13.10.2026.

Audyt (pkt 10): filtr łapał „150 zł/h”, ale przepuszczał kwotę bez waluty przy
słowie o pieniądzach („stawka 150 B2B”, „rate 140”, „zarabia 18k, chce 22k”)
i dostępność po angielsku („Notice: 1 month”, „Can start in 2 weeks”).
W drugą stronę ginęły fakty o systemach i projektach („dostępność 99,95%”,
„System jest dostępny 24/7”, „projekt wart 5 mln PLN”).
"""

import pytest

from app.services.money_text import is_rate_text, strip_rates_and_availability


@pytest.mark.parametrize(
    "note",
    [
        "Stawka: 150",
        "Stawka 25k B2B",
        "Kandydat chce 160 na B2B",
        "Rozmawialiśmy o stawce 150-160.",
        "Widełki 20-25k",
        "Wynagrodzenie: 18 000",
        "Ustaliliśmy rate 140.",
        "Rate: 140",
        "Obecnie zarabia 18k",
        "Chce 22k.",
        "Salary 18000",
    ],
)
def test_amount_without_currency_next_to_money_word_leaves_the_note(note):
    assert strip_rates_and_availability(note) == ""


@pytest.mark.parametrize(
    "note,kept",
    [
        ("Kandydat ok, stawka 150 B2B, zna Kafkę", "Kandydat ok, zna Kafkę"),
        ("Dobry kontakt, chce 150 na B2B, zna Kafkę", "Dobry kontakt, zna Kafkę"),
        ("Mocny w Javie. Obecnie zarabia 18k, chce 22k.", "Mocny w Javie."),
        ("W Allegro od 2019 do teraz, rate 150", "W Allegro od 2019 do teraz,"),
        ("Rozmowa ok. Stawka 150, dostępny od zaraz.", "Rozmowa ok."),
    ],
)
def test_money_fragment_goes_and_the_rest_of_the_note_stays(note, kept):
    assert strip_rates_and_availability(note) == kept


@pytest.mark.parametrize(
    "note",
    [
        "Notice: 1 month",
        "1 month notice",
        "Can start in 2 weeks",
        "Start: od 1.11",
        "Gotowy do startu od listopada",
        "Może zacząć od 1 grudnia",
        "Start ASAP",
        "Dostępna za 2 tygodnie",
    ],
)
def test_candidate_start_and_notice_leave_the_note(note):
    assert strip_rates_and_availability(note) == ""


@pytest.mark.parametrize(
    "fact",
    [
        "Odpowiadał za dostępność 99,95% platformy",
        "Odpowiadał za dostępność 99.95% platformy",
        "System jest dostępny 24/7 dla 2 mln użytkowników",
        "Zbudował API, które jest dostępne publicznie",
        "Prowadził projekt wart 5 mln PLN",
        "Zwiększył conversion rate o 15%",
        "Wdrożył rate limiting 1000 req/s",
        "Karierę rozpoczął od testów manualnych",
        "Pracuje od 3 lat na B2B",
        "Zna Java 17, Spring Boot 3, 5 lat doświadczenia.",
        "Pracował w startupie od 2019",
    ],
)
def test_facts_about_systems_projects_and_career_stay(fact):
    assert strip_rates_and_availability(fact) == fact


def test_rate_word_with_bare_amount_counts_as_rate_note():
    # Licznik „notatki ze stawką” w karcie „CV do klienta” liczy to, co
    # generator wycina — także stawkę bez waluty.
    assert is_rate_text("stawka 150 B2B")
    assert is_rate_text("rate 140")
    assert not is_rate_text("success rate 95%")
    assert not is_rate_text("Stawka zależy od projektu")
