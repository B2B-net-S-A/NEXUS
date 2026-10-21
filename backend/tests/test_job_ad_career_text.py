"""Strona kariery z ogłoszenia (21.10.2026) — mapowanie treści, bez bazy.

Reguły: ``docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md``.
"""

from __future__ import annotations

from app.services import job_public_profile as jpp
from app.services.job_ad.career import career_text


def test_lead_becomes_subtitle_and_duties_follow_the_project():
    text = career_text(
        {
            "lead": "Szukamy osoby do zespołu płatności.",
            "about": "Zespół buduje mikroserwisy.\n\nPraca w Scrumie.",
            "responsibilities": ["rozwój w Javie.", "przeglądy kodu;", "  "],
        },
        "pl",
    )
    assert text.subtitle == "Szukamy osoby do zespołu płatności"
    assert text.about == (
        "Zespół buduje mikroserwisy.\n\nPraca w Scrumie.\n\n"
        "Czym się zajmiesz: rozwój w Javie; przeglądy kodu."
    )


def test_english_ad_gets_an_english_duties_heading():
    text = career_text({"responsibilities": ["code reviews"]}, "en")
    assert text.subtitle is None
    assert text.about == "What you will do: code reviews."


def test_empty_ad_gives_nothing_to_publish():
    text = career_text({"lead": " ", "about": "", "responsibilities": []}, "pl")
    assert text.subtitle is None and text.about is None


def test_invisible_characters_never_reach_the_page():
    # „‮” odwraca kierunek tekstu: kontrola czyta tekst bez niego.
    text = career_text({"lead": "Stawka‮ 081 zł‬", "about": "A­B"}, "pl")
    assert "‮" not in (text.subtitle or "")
    assert text.about == "AB"


def test_about_is_cut_at_a_paragraph_never_mid_sentence():
    long_paragraph = "x" * (jpp.ABOUT_MAX - 10)
    text = career_text(
        {"about": f"{long_paragraph}\n\nDrugi akapit, który się nie zmieści."}, "pl"
    )
    assert text.about == long_paragraph
