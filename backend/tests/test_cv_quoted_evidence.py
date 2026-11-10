"""Sprawdzanie cytatu modelu w tekście CV (``cv_quoted_evidence``, 09.11.2026).

``raw_cv_text`` z PDF bywa przeplatany datami i nagłówkami w środku zdania
(kolumna z datami czytana razem z treścią). Model cytuje zdanie sklejone,
a dosłowne porównanie je odrzucało: pomiar na stagingu 09.11.2026 — 176
z 1 490 cytatów (12%) było prawdziwych, ale niedosłownych. Tu pilnujemy, że
taki cytat przechodzi, a zmyślony, przestawiony albo krótki — nie.
"""

from __future__ import annotations

from app.services import application_screening, candidate_ai_assessment
from app.services import cv_quoted_evidence as svc

# Tekst jak z PDF z kolumną dat: zdanie przerwane datą i nagłówkiem.
CV_TEXT = (
    "Experience\n"
    "Senior Business Analyst\n"
    "Responsible for gathering requirements and determining ways to optimize/\n"
    "01-2021 – Present\n"
    "improve JIRA and Confluence building workflows for 12 delivery teams.\n"
    "Kierownik projektu wdrożenia systemu\n"
    "2019 – 2020\n"
    "księgowego w spółce z branży logistycznej, zespół 8 osób.\n"
    "Skills: SQL, Excel, BPMN\n"
)

GLUED = (
    "determining ways to optimize/ improve JIRA and Confluence building "
    "workflows for 12 delivery teams"
)


def _found(quote: str, *haystacks: str) -> bool:
    return svc.quote_matcher(haystacks or (CV_TEXT,))(quote)


def test_literal_quote_still_passes():
    assert _found("Skills: SQL,   excel")
    assert _found("SQL")


def test_quote_glued_over_inserted_date_passes():
    assert _found(GLUED)
    # Polskie znaki i nagłówek z latami w środku zdania.
    assert _found(
        "Kierownik projektu wdrożenia systemu księgowego w spółce z branży "
        "logistycznej, zespół 8 osób"
    )


def test_invented_quote_with_cv_topics_is_dropped():
    assert not _found(
        "led the migration of JIRA and Confluence to the cloud for 40 teams"
    )
    assert not _found("5 lat doświadczenia jako kierownik projektu w logistyce")


def test_reordered_words_are_not_a_quote():
    assert not _found(
        "workflows building Confluence and JIRA improve for delivery 12 teams"
    )


def test_short_quote_must_be_literal():
    # Pięć słów sklejonych ponad datą: za mało, żeby ufać podobieństwu.
    assert not _found("ways to optimize/ improve JIRA")
    assert _found("optimize/")


def test_two_distant_sentences_glued_without_ellipsis_are_dropped():
    assert not _found(
        "gathering requirements and determining spółce z branży logistycznej zespół"
    )


def test_ellipsis_joins_fragments_that_each_stand_on_their_own():
    # Decyzja: „…” dzieli cytat na fragmenty; każdy musi przejść sam, tymi
    # samymi regułami (krótki dosłownie). Wielokropek nie daje więc więcej,
    # niż dałyby dwa osobne cytaty, a rekruter widzi, że coś pominięto.
    assert _found("Senior Business Analyst … Skills: SQL, Excel, BPMN")
    assert _found("Responsible for gathering requirements ... 12 delivery teams")
    assert _found(f"...{GLUED}...")
    assert not _found("Senior Business Analyst … Python, Django")
    assert not _found("Senior Business Analyst … ways to optimize/ improve JIRA")
    assert not _found("… …")


def test_keep_quoted_reasons_keeps_glued_and_drops_invented():
    kept = svc.keep_quoted_reasons(
        [
            {"text": "Usprawnia JIRA.", "quote": GLUED},
            {"text": "Zmyślone.", "quote": "migrated 300 Jenkins pipelines to GitHub"},
        ],
        [CV_TEXT, None],
    )
    assert kept == [{"text": "Usprawnia JIRA.", "quote": GLUED}]


def test_assessment_tags_glued_quote_as_cv_not_profile():
    tagged = candidate_ai_assessment.tag_sources(
        [{"text": "a", "quote": GLUED}], cv=CV_TEXT, notes="", profile="Analyst"
    )
    assert tagged[0]["source"] == candidate_ai_assessment.SOURCE_CV


def test_deal_breaker_accepts_glued_quote():
    raw = '{"deal_breaker": {"condition": "Brak JIRA", "quote": "%s"}}' % GLUED
    hit = application_screening.keep_quoted_deal_breaker(raw, ["Brak JIRA"], [CV_TEXT])
    assert hit == {"condition": "Brak JIRA", "quote": GLUED}
    raw_bad = '{"deal_breaker": {"condition": "Brak JIRA", "quote": "never used JIRA or Confluence at any job"}}'
    assert (
        application_screening.keep_quoted_deal_breaker(
            raw_bad, ["Brak JIRA"], [CV_TEXT]
        )
        is None
    )
