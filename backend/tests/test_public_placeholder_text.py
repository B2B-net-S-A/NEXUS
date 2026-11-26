"""Zaślepki modelu nie trafiają na stronę kariery (26.11.2026).

Oferta Oracle (``/r/team-leasing-oracle-kcjy``) pokazywała kandydatom w
rozdziale „Projekt” zdanie szkicu AI „Brak szczegółowych informacji o
projekcie w materiale źródłowym”: model dostał w materiale same „brak”,
opisał ten brak, a rekruter zatwierdził. Takie zdanie mówi o materiale
NEXUSA, nie o projekcie — znika przy zapisie i w każdej projekcji
publicznej, a bez opisu rozdział „Projekt” na stronie znika sam
(``OfferPage.tsx``: ``hasProject``).

Bez bazy. Strażnik na żywym API: ``test_career_links_api.py``
(``test_public_page_never_shows_a_placeholder_about``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import job_public_profile as jpp
from app.services.job_ad.career import career_text
from app.services.public_profile_lint import drop_placeholders

ORACLE = "Brak szczegółowych informacji o projekcie w materiale źródłowym"


@pytest.mark.parametrize(
    "text",
    [
        ORACLE,
        f"{ORACLE}.",
        "O projekcie: brak szczegółowych informacji w materiale źródłowym.",
        "Brak informacji o projekcie.",
        "Brak dodatkowych danych o zespole.",
        "Nie podano opisu projektu.",
        "Materiał źródłowy nie zawiera opisu projektu.",
        "No details about the project in the source material.",
        "No further information about the project.",
    ],
)
def test_placeholder_alone_leaves_nothing(text):
    assert drop_placeholders(text) is None


def test_placeholder_sentence_goes_and_facts_stay():
    text = (
        "Zespół rozwija system rozliczeń w sektorze bankowym. "
        "Brak szczegółowych informacji o technologiach w materiale źródłowym.\n\n"
        "Czym się zajmiesz: rozwój w Javie; przeglądy kodu; testy."
    )
    assert drop_placeholders(text) == (
        "Zespół rozwija system rozliczeń w sektorze bankowym.\n\n"
        "Czym się zajmiesz: rozwój w Javie; przeglądy kodu; testy."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Budujemy nowy system rozliczeń.\n\nPracujesz w zespole 6 osób.",
        "Brak nadgodzin i dyżurów.",
        "Projekt bez dokumentacji — zespół spisuje wiedzę od zera.",
        "Zespół przygotowuje materiały szkoleniowe dla klientów.",
    ],
)
def test_real_text_is_kept_as_is(text):
    assert drop_placeholders(text) == text


def test_empty_input_gives_none():
    assert drop_placeholders(None) is None
    assert drop_placeholders("  \n ") is None


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        client_id=7,
        title="Team Leasing - Oracle",
        champion_profile={},
        must_skills=["Oracle"],
        nice_skills=[],
        location=None,
        remote_policy=None,
        onsite_days_per_week=None,
        onsite_days_per_month=None,
        seniority=None,
    )


def test_public_payload_never_carries_a_placeholder():
    payload = jpp.public_job_payload(
        _job(),
        title="Team Leasing - Oracle",
        link_slug="team-leasing-oracle-kcjy",
        subtitle="Specjalista Oracle do pracy w modelu Team Leasing",
        about=ORACLE,
        sections=None,
    )
    assert payload["about"] is None
    assert payload["subtitle"] == "Specjalista Oracle do pracy w modelu Team Leasing"
    assert "materiale" not in json.dumps(payload, ensure_ascii=False)


def test_ai_draft_drops_the_placeholder_about():
    draft = jpp._parse_draft(
        json.dumps(
            {
                "subtitle": "praca z bazami Oracle w modelu Team Leasing",
                "about": ORACLE,
            },
            ensure_ascii=False,
        )
    )
    assert draft == {
        "subtitle": "praca z bazami Oracle w modelu Team Leasing",
        "about": "",
    }


def test_ai_draft_of_placeholders_only_is_no_draft():
    with pytest.raises(ValueError):
        jpp._parse_draft(
            json.dumps({"subtitle": "", "about": ORACLE}, ensure_ascii=False)
        )


def test_ad_to_career_text_drops_the_placeholder_about():
    text = career_text(
        {
            "lead": "Szukamy specjalisty Oracle.",
            "about": ORACLE,
            "responsibilities": [],
        },
        "pl",
    )
    assert text.subtitle == "Szukamy specjalisty Oracle"
    assert text.about is None
