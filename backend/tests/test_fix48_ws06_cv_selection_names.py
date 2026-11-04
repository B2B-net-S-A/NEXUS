"""AI na zaznaczeniu: nazwa na początku zdania i plakietka rozwinięcia (audyt 13.10.2026).

Kontrola „bez nowych faktów” bierze słowa pisane wielką literą z „Ułóż
w zdanie” (`unsupported_facts`), a ta pomija każde słowo z wielkiej litery na
początku zdania i po „( : ; „ " '”. Dlatego przechodziły „Klient: Microsoft —
…”, „(Microsoft)”, „„Allegro”” i dopisane zdanie „Microsoft jako główny
klient.”. Przy „Rozwiń” taka propozycja dostawała jeszcze plakietkę „Zgodne ze
źródłem”, bo plakietka zależała tylko od tego, czy cytat istnieje.
"""

from __future__ import annotations

import json

import pytest

from app.services import cv_command_ai as command_ai
from app.services import cv_selection_ai as ai

FRAGMENT = "rozwój aplikacji backendowych w Javie dla klientów"
ORIGINAL = (
    "Odpowiadał za rozwój aplikacji backendowych dla klientów z branży bankowej "
    "w zespole pięciu osób."
)
QUOTE = "rozwój aplikacji backendowych dla klientów z branży bankowej"


def check(action: str, text: str, *quotes: str, grounds=None) -> dict:
    raw = json.dumps({"text": text, "quotes": list(quotes)}, ensure_ascii=False)
    return ai.check(action, FRAGMENT, raw, grounds or ai.Grounds())


# ── nazwa po dwukropku, nawiasie, średniku i cudzysłowie ────────────────────


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Klient: Microsoft — rozwój aplikacji backendowych w Javie", "Microsoft"),
        ("Rozwój aplikacji backendowych w Javie dla klientów (Microsoft)", "Microsoft"),
        ("Rozwój aplikacji backendowych w Javie dla klientów; Microsoft", "Microsoft"),
        ("Rozwój aplikacji backendowych w Javie dla klientów „Allegro”", "Allegro"),
        ('Rozwój aplikacji backendowych w Javie dla klientów "Allegro"', "Allegro"),
        # skrót przed nazwą nie kończy zdania
        (
            "Rozwój aplikacji backendowych w Javie dla klientów, np. Microsoft",
            "Microsoft",
        ),
    ],
)
@pytest.mark.parametrize("action", ["rephrase", "proofread"])
def test_name_after_punctuation_is_a_new_fact(
    action: str, text: str, name: str
) -> None:
    out = check(action, text)
    assert (out["status"], out["reason"], out["problem"]) == (
        "rejected",
        "new_fact",
        name,
    ), out
    assert name in out["message"]


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Rozwój aplikacji backendowych w Javie dla klientów. AWS w produkcji.", "AWS"),
        ("GitHub: rozwój aplikacji backendowych w Javie dla klientów", "GitHub"),
    ],
)
def test_acronym_or_inner_capital_at_sentence_start_is_a_new_fact(
    text: str, name: str
) -> None:
    """Zwykłe słowo nie ma wielkich liter w środku — „AWS” i „GitHub” to nazwy."""
    out = check("rephrase", text)
    assert (out["status"], out["reason"], out["problem"]) == (
        "rejected",
        "new_fact",
        name,
    ), out


# ── wielka litera na początku zdania ────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Rozwój aplikacji backendowych w Javie dla klientów. Kubernetes w produkcji.",
        "Google: rozwój aplikacji backendowych w Javie dla klientów",
        "Rozwój aplikacji backendowych w Javie dla klientów. Microsoft jako główny klient.",
    ],
)
def test_new_word_at_sentence_start_is_flagged_in_a_rephrase(text: str) -> None:
    """Na początku zdania kod nie odróżni nazwy od zwykłego słowa („Tworzenie”),
    więc w redakcji to uwaga na karcie, nie odmowa — ale nie przechodzi bez słowa."""
    out = check("rephrase", text)
    assert out["status"] == "ok", out
    assert out["cautions"], out
    assert out["cautions"][0] in text


@pytest.mark.parametrize(
    ("action", "text", "name"),
    [
        (
            "proofread",
            "Rozwój aplikacji backendowych w Javie dla klientów. Kafka",
            "Kafka",
        ),
        ("shorten", "Rozwój aplikacji w Javie. Microsoft.", "Microsoft"),
    ],
)
def test_new_word_at_sentence_start_is_a_new_fact_where_nothing_may_be_added(
    action: str, text: str, name: str
) -> None:
    """Skrócenie i korekta nie mają powodu wprowadzać nowego słowa."""
    out = check(action, text)
    assert (out["status"], out["reason"], out["problem"]) == (
        "rejected",
        "new_fact",
        name,
    ), out


@pytest.mark.parametrize("action", ["rephrase", "shorten", "proofread"])
def test_reworded_first_word_is_not_flagged(action: str) -> None:
    """Redakcja zmienia słowo, od którego zaczyna się punkt — to nie dopisek."""
    text = {
        "rephrase": "Tworzenie aplikacji backendowych w Javie dla klientów",
        "shorten": "Tworzenie aplikacji w Javie dla klientów",
        "proofread": "Rozwój aplikacji backendowych w Javie dla klientów.",
    }[action]
    out = check(action, text)
    assert out["status"] == "ok", out
    assert out["cautions"] == []


def test_translation_still_ignores_english_sentence_starts() -> None:
    out = ai.check(
        "translate",
        "Rozwój aplikacji w Javie. Testy jednostkowe.",
        json.dumps({"text": "Development of applications in Java. Unit tests."}),
        ai.Grounds(),
    )
    assert out["status"] == "ok" and out["cautions"] == [], out


def test_translation_shows_a_name_after_a_colon_as_a_caution() -> None:
    out = ai.check(
        "translate",
        "Klient: rozwój aplikacji w Javie.",
        json.dumps({"text": "Client: Microsoft, development of applications in Java."}),
        ai.Grounds(),
    )
    assert out["status"] == "ok"
    assert "Microsoft" in out["cautions"], out


# ── „Rozwiń”: plakietka tylko, gdy każde słowo ma źródło ────────────────────


GROUNDS = ai.Grounds(original=ORIGINAL)


@pytest.mark.parametrize(
    "added",
    [
        "; kierował zespołem i zarządzał budżetem projektu",
        ". Microsoft jako główny klient.",
    ],
)
def test_expand_with_words_outside_fragment_and_quote_is_not_verified(
    added: str,
) -> None:
    text = (
        "Rozwój aplikacji backendowych w Javie dla klientów z branży bankowej" + added
    )
    out = check("expand", text, QUOTE, grounds=GROUNDS)
    assert out["status"] == "ok", out
    assert out["verified"] is False
    assert out["sources"] == [{"kind": "original", "quote": QUOTE}]
    # Karta mówi, których słów nie ma w zaznaczeniu ani w cytacie.
    assert out["message"] and "Sprawdź" in out["message"]
    first_new = added.strip(" .;").split()[0].lower()
    assert first_new in out["message"].lower()


def test_expand_built_only_from_fragment_and_quote_keeps_the_badge() -> None:
    out = check(
        "expand",
        "Rozwój aplikacji backendowych w Javie dla klientów z branży bankowej",
        QUOTE,
        grounds=GROUNDS,
    )
    assert out["status"] == "ok" and out["verified"] is True, out
    assert out["message"] is None and out["cautions"] == []


# ── polecenie dla całego CV korzysta z tej samej kontroli ───────────────────


def test_command_replace_with_a_name_after_a_colon_is_a_question() -> None:
    # Nazwa po dwukropku nie przechodzi po cichu. Od asystenta w kolumnie
    # (Edytor CV 3, PR 4, 14.10.2026) fakt spoza CV i notatek wraca jako
    # pytanie do rekrutera („Kandydat mówił o tym na rozmowie?”), a nie jako
    # odrzucenie — do CV trafia dopiero po „Tak, dopisz”.
    lines = [
        command_ai.Line(0, "heading", "Doświadczenie", section="experience"),
        command_ai.Line(1, "role", "**Dev**", section="experience", role=0),
        command_ai.Line(2, "bullet", FRAGMENT, section="experience", role=0),
        command_ai.Line(3, "bullet", "testy jednostkowe", section="experience", role=0),
    ]
    raw = json.dumps(
        {
            "operations": [
                {
                    "type": "replace",
                    "line": 2,
                    "text": "Klient: Microsoft — rozwój aplikacji backendowych w Javie",
                }
            ]
        },
        ensure_ascii=False,
    )
    plan = command_ai.verify_plan(raw, lines, ())
    assert plan["dropped"] == []
    [operation] = plan["operations"]
    assert (operation["ask"], operation["problem"]) == ("source", "Microsoft")
