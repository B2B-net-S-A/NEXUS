"""Wtyczka 1.0.8 (Recruiter Lite) — logika bez bazy: słowa kluczowe do
wyszukiwarki, daty zwrotu kredytu, etykiety odpowiedzi. Dane fikcyjne."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.job import RemotePolicy
from app.models.note import NoteType
from app.services import linkedin_extension_outreach as outreach


# ── Słowa kluczowe i zestaw do wyszukiwarki ──────────────────────────────────


def test_keywords_titles_or_then_must_skills_and() -> None:
    assert (
        outreach.search_keywords(
            ["Analityk biznesowy", "Business Analyst"], ["BPMN", "SQL"]
        )
        == '("Analityk biznesowy" OR "Business Analyst") AND BPMN AND SQL'
    )


def test_keywords_without_must_skills_is_titles_only() -> None:
    assert outreach.search_keywords(["Java Developer", "Programista Java"], []) == (
        '("Java Developer" OR "Programista Java")'
    )


def test_keywords_single_title_without_parentheses() -> None:
    assert outreach.search_keywords(["Tester"], ["Selenium"]) == '"Tester" AND Selenium'


@pytest.mark.parametrize(
    ("skill", "expected"),
    [
        ("SQL", "SQL"),
        ("Księgowość", "Księgowość"),
        ("Python3", "Python3"),
        ("Spring Boot", '"Spring Boot"'),
        ("C++", '"C++"'),
        ("C#", '"C#"'),
        ("Node.js", '"Node.js"'),
        ("snake_case", '"snake_case"'),
    ],
)
def test_search_term_quotes_spaces_and_symbols(skill: str, expected: str) -> None:
    assert outreach.search_term(skill) == expected


def test_titles_dedupe_case_insensitive_and_skip_empty() -> None:
    assert outreach.search_titles("java developer", "Java Developer") == [
        "java developer"
    ]
    assert outreach.search_titles(None, "Tester") == ["Tester"]
    assert outreach.search_titles("  ", "Tester") == ["Tester"]


def test_locations_split_and_empty() -> None:
    assert outreach.split_locations("Gdańsk, Warszawa / Kraków; gdańsk") == [
        "Gdańsk",
        "Warszawa",
        "Kraków",
    ]
    assert outreach.split_locations(None) == []
    assert outreach.split_locations("") == []
    assert outreach.split_locations(" , ") == []


def _job(**extra) -> SimpleNamespace:
    base = dict(
        id=7,
        title="Analityk biznesowy",
        working_title="Business Analyst",
        must_skills=[{"name": "BPMN"}, {"name": "SQL"}, {"name": "sql"}],
        nice_skills=[{"name": "UML"}],
        location="Gdańsk",
        remote_policy=RemotePolicy.hybrid,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def test_build_search_kit_matches_contract_example() -> None:
    kit = outreach.build_search_kit(
        _job(), ["Klient Testowy", "Bank Północny", "Bank Północny"]
    )
    assert kit.model_dump() == {
        "job_id": 7,
        "title": "Analityk biznesowy",
        "keywords": '("Business Analyst" OR "Analityk biznesowy") AND BPMN AND SQL',
        "titles": ["Business Analyst", "Analityk biznesowy"],
        "skills_must": ["BPMN", "SQL"],
        "skills_nice": ["UML"],
        "locations": ["Gdańsk"],
        "remote": "hybrid",
        "exclude_companies": ["Bank Północny", "Klient Testowy"],
    }


def test_build_search_kit_bare_job() -> None:
    kit = outreach.build_search_kit(
        _job(
            working_title="Analityk Biznesowy",
            must_skills=None,
            nice_skills=[],
            location=None,
            remote_policy=None,
        ),
        [],
    )
    assert kit.titles == ["Analityk Biznesowy"]
    assert kit.keywords == '"Analityk Biznesowy"'
    assert kit.skills_must == [] and kit.skills_nice == []
    assert kit.locations == [] and kit.remote is None
    assert kit.exclude_companies == []


def test_build_search_kit_strips_quotes_from_terms() -> None:
    kit = outreach.build_search_kit(
        _job(working_title=None, title='Dev "Senior"', must_skills=["C++"]), []
    )
    assert kit.keywords == '"Dev Senior" AND "C++"'


# ── Daty w kalendarzu firmy ──────────────────────────────────────────────────


def test_refund_until_is_send_day_plus_90() -> None:
    sent = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
    assert outreach.refund_until(sent) == date(2027, 1, 19)


def test_refund_until_counts_from_warsaw_day_after_midnight() -> None:
    # 23:30 UTC 21.10 to w Warszawie już 22.10.
    sent = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)
    assert outreach.refund_until(sent) == date(2027, 1, 20)


def test_days_ago_uses_company_calendar() -> None:
    at = datetime(2026, 11, 2, 23, 45, tzinfo=timezone.utc)  # 03.11 w Warszawie
    assert outreach.days_ago(at, date(2026, 11, 12)) == 9
    assert outreach.days_ago(at, date(2026, 11, 3)) == 0


# ── Ślady i etykiety odpowiedzi ──────────────────────────────────────────────


def test_reply_ref_round_trip_and_fits_column() -> None:
    ref = outreach.reply_ref("not_now", 2_147_483_647)
    assert ref == "linkedin_extension:reply:not_now:2147483647"
    assert len(ref) <= 120
    assert outreach.parse_reply_ref(ref) == ("not_now", 2_147_483_647)


@pytest.mark.parametrize(
    "ref",
    [
        None,
        "",
        "linkedin_extension:inmail",
        "linkedin_extension:reply:maybe:5",
        "linkedin_extension:reply:interested:abc",
        "linkedin_extension:reply:interested:5:6",
    ],
)
def test_parse_reply_ref_rejects_other_refs(ref) -> None:
    assert outreach.parse_reply_ref(ref) is None


def test_reply_content_uses_original_channel_and_date() -> None:
    sent_on = date(2026, 10, 21)
    assert (
        outreach.reply_content("interested", "inmail", sent_on)
        == "Odpowiedź na InMail z 21.10.2026: chce rozmawiać"
    )
    assert (
        outreach.reply_content("not_now", "invitation", sent_on)
        == "Odpowiedź na zaproszenie na LinkedInie z 21.10.2026: nie teraz"
    )
    assert (
        outreach.reply_content("no_reply", "inmail", sent_on)
        == "Brak odpowiedzi na InMail z 21.10.2026"
    )


def test_contact_label_for_replies_and_contacts() -> None:
    origins = {5: "linkedin_extension:inmail", 6: "linkedin_extension:linkedin_message"}
    label = outreach.contact_label
    assert label(None, "linkedin_extension:reply:interested:5", origins) == (
        "odpowiedź na InMail"
    )
    assert label(None, "linkedin_extension:reply:not_now:6", origins) == (
        "odpowiedź na wiadomość na LinkedInie"
    )
    assert label(None, "linkedin_extension:reply:no_reply:5", origins) == (
        "brak odpowiedzi"
    )
    # Kontakt, na który odpowiedziano, zniknął — sama „odpowiedź”.
    assert label(None, "linkedin_extension:reply:interested:99", origins) == "odpowiedź"
    assert label(None, "linkedin_extension:inmail") == "InMail"
    assert label(None, "linkedin_extension:cos_nowego") == "kontakt"
    assert label(NoteType.call, None) == "telefon"
    assert label(None, None) == "próba kontaktu"
