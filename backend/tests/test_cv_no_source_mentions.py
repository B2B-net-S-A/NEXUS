"""CV bez dopisków o źródle faktu i o braku doświadczenia komercyjnego (17.11.2026).

Zgłoszenie Artura: „Bazy danych (niekomercyjnie): MongoDB - znajomość
potwierdzona podczas screeningu, bez doświadczenia komercyjnego”. Klient nie
ma wiedzieć, skąd generator wziął fakt, a zastrzeżenie czyta jako „nie umie”.
Kopia produkcji z 16.11 (958 CV z 30 dni): to samo w zadaniach („per screening
notes”), językach („B2 według notatek ze screeningu; C1 według CV”), punkcie
„Dlaczego” i umiejętnościach.
Reguła: docs/claude/generator-cv/bez-zrodla-faktu-i-zastrzezen-w-cv.md.
"""

from __future__ import annotations

import pytest

from app.services.cv_generator_b2b.legacy_v7 import _helpers
from app.services.cv_generator_b2b.legacy_v7.prompts import get_prompt


def _strip(data):
    return _helpers.strip_source_mentions(data)


def test_reported_case_category_label_and_item_tail():
    data = {
        "skills": [
            {
                "label": "Bazy danych:",
                "content": "PostgreSQL, Amazon DynamoDB, InfluxDB",
            },
            {
                "label": "Bazy danych (niekomercyjnie):",
                "content": "MongoDB - znajomość potwierdzona podczas screeningu, "
                "bez doświadczenia komercyjnego",
            },
            {"label": "Integracje i API:", "content": "RabbitMQ, HTTP"},
        ]
    }
    notes = _strip(data)
    assert data["skills"] == [
        {
            "label": "Bazy danych:",
            "content": "PostgreSQL, Amazon DynamoDB, InfluxDB, MongoDB",
        },
        {"label": "Integracje i API:", "content": "RabbitMQ, HTTP"},
    ]
    assert notes and notes[0].startswith("WERYFIKUJ")


def test_category_label_alone_loses_the_caveat():
    data = {"skills": [{"label": "Databases (non-commercial):", "content": "MongoDB"}]}
    _strip(data)
    assert data["skills"] == [{"label": "Databases:", "content": "MongoDB"}]


@pytest.mark.parametrize(
    "before, after",
    [
        (
            "Works primarily with Scandinavian clients in shipping and fund segments "
            "(per screening notes)",
            "Works primarily with Scandinavian clients in shipping and fund segments",
        ),
        (
            "Launch products in six markets: Czechia, Slovenia and Italy; screening notes "
            "additionally report participation in expansion into seven new markets.",
            "Launch products in six markets: Czechia, Slovenia and Italy.",
        ),
        (
            "Wdrażanie usług w Kubernetes, potwierdzone podczas rozmowy rekrutacyjnej",
            "Wdrażanie usług w Kubernetes",
        ),
    ],
)
def test_duty_loses_the_source_clause(before, after):
    data = {"experience": [{"responsibilities": [before]}]}
    _strip(data)
    assert data["experience"][0]["responsibilities"] == [after]


def test_why_point_loses_the_non_commercial_clause():
    data = {
        "why_points": [
            "5 lat doświadczenia jako Backend Developer",
            "MongoDB wykorzystywał w systemach medycznych; ma także niekomercyjne "
            "doświadczenie z GraphQL.",
        ]
    }
    _strip(data)
    assert data["why_points"][1] == "MongoDB wykorzystywał w systemach medycznych."


def test_language_keeps_one_level_without_the_source():
    data = {"languages": ["Angielski - B2 według notatek ze screeningu; C1 według CV"]}
    _strip(data)
    assert data["languages"] == ["Angielski - B2"]


@pytest.mark.parametrize(
    "text",
    [
        "Oversaw AML, PEP and sanctions screening across multiple jurisdictions",
        "Sanctions screening, KYC, AML",
        "Prowadzenie rozrachunków i przygotowanie deklaracji podatkowych",
        "Presented at Open Door events and participated in recruitment interviews",
    ],
)
def test_domain_words_stay(text):
    """„Screening” w AML, „deklaracje podatkowe”, rozmowy jako zadanie to fakty."""
    data = {
        "why_points": [text],
        "experience": [{"responsibilities": [text]}],
        "skills": [{"label": "Wiedza dziedzinowa:", "content": text}],
    }
    assert _strip(data) == []
    assert data["why_points"] == [text]
    assert data["experience"][0]["responsibilities"] == [text]


@pytest.mark.parametrize("language", ["pl", "en"])
def test_prompt_forbids_source_mentions(language):
    prompt = get_prompt(language, False, "tailored")
    marker = "ŹRÓDŁO FAKTU" if language == "pl" else "SOURCE OF A FACT"
    assert marker in prompt
