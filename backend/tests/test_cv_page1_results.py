"""„Najmocniejszy wynik” na stronę 1 Nowego CV — sprawdzenie, scalenie, wyzwalacz.

Bez bazy: kontrola zdań modelu (`cv_page1_result_checks`), scalenie dodatków
strony 1, łańcuch HTML → model → lista z atrapą modelu i sesji, wyzwalacz po
commicie. Trasa i zapis w Postgresie: `test_cv_page1_results_api.py`.
Dane fikcyjne.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import cv_page1_results as service
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_layout import chosen_result
from app.services.cv_page1_why import inputs_sha
from app.services.cv_page1_why_checks import WhyInputs
from app.services.cv_page1_result_checks import (
    ISSUE_COMPANY_NAMED,
    ISSUE_NOT_ONE_SENTENCE,
    ISSUE_NUMBER_NOT_IN_CV,
    ISSUE_QUOTE_MISSING,
    ISSUE_QUOTE_NOT_IN_CV,
    ISSUE_TOO_LONG,
    MAX_RESULTS,
    RoleSource,
    merged_extras,
    source_sha,
    verify_results,
)

ROLES = [
    RoleSource(
        index=0,
        company="Acme Bank",
        position="Starszy tester",
        dates="01.2021 - obecnie",
        duties=(
            "Zaprojektowanie testów regresyjnych, które ograniczyły liczbę defektów "
            "produkcyjnych o około 30% w systemie płatności.",
            "Koordynacja zespołu 6 testerów w projekcie migracji do chmury.",
        ),
        technologies=("Postman", "Jira"),
    ),
    RoleSource(
        index=1,
        company="Example Logistics (klient: Firma Beta)",
        position="Tester",
        dates="03.2017 - 12.2020",
        duties=(
            "Automatyzacja 1 200 przypadków testowych w Selenium – czas regresji "
            "skrócony z 5 dni do 1 dnia.",
        ),
        technologies=("Selenium",),
    ),
]
WHY = [
    "Ponad 8 lat doświadczenia jako Tester oprogramowania",
    "Praktyczne doświadczenie z Postmanem, Jirą i Selenium w testach systemów płatności",
]
GOOD = {
    "text": "Ograniczenie defektów produkcyjnych o **około 30%** w systemie płatności "
    "w Acme Bank",
    "quote": "ograniczyły liczbę defektów produkcyjnych o około 30% w systemie płatności",
    "company": "Acme Bank",
}


def _one(item: dict, *, blind: bool = False) -> dict:
    results = verify_results([item], ROLES, WHY, blind=blind)
    assert len(results) == 1, results
    return results[0]


# ── Sprawdzenie zdań ────────────────────────────────────────────────────────


def test_good_quote_is_verified():
    result = _one(GOOD)
    assert result["verified"] is True
    assert "issue" not in result
    assert result["company"] == "Acme Bank"
    assert result["text"] == GOOD["text"]


def test_quote_ignores_case_quotes_dashes_and_punctuation():
    result = _one(
        {
            "text": "Skrócenie czasu regresji **z 5 dni do 1 dnia** w Example Logistics",
            "quote": "AUTOMATYZACJA 1 200 przypadków testowych w Selenium - czas regresji "
            "skrócony z 5 dni do 1 dnia",
            "company": "Example Logistics (klient: Firma Beta)",
        }
    )
    assert result["verified"] is True


def test_changed_word_in_quote_is_not_in_cv():
    result = _one(
        {**GOOD, "quote": "ograniczyły liczbę błędów produkcyjnych o około 30%"}
    )
    assert result["verified"] is False
    assert result["issue"] == ISSUE_QUOTE_NOT_IN_CV


def test_invented_quote_is_not_in_cv():
    result = _one(
        {
            "text": "Wdrożenie testów wydajnościowych dla **2 mln użytkowników** w Acme Bank",
            "quote": "wdrożenie testów wydajnościowych dla 2 mln użytkowników",
            "company": "Acme Bank",
        }
    )
    assert result["verified"] is False
    assert result["issue"] == ISSUE_QUOTE_NOT_IN_CV


def test_changed_number_is_not_in_cv():
    result = _one({**GOOD, "text": GOOD["text"].replace("30%", "40%")})
    assert result["verified"] is False
    assert result["issue"] == ISSUE_NUMBER_NOT_IN_CV


def test_number_from_another_point_of_the_same_role_is_allowed():
    result = _one(
        {
            "text": "Ograniczenie defektów o **około 30%** przy zespole 6 testerów w Acme Bank",
            "quote": GOOD["quote"],
            "company": "Acme Bank",
        }
    )
    assert result["verified"] is True


def test_number_from_another_role_is_rejected():
    result = _one(
        {
            "text": "Ograniczenie defektów o **około 30%** w 1 200 przypadkach w Acme Bank",
            "quote": GOOD["quote"],
            "company": "Acme Bank",
        }
    )
    assert result["issue"] == ISSUE_NUMBER_NOT_IN_CV


def test_thousands_written_differently_still_match():
    result = _one(
        {
            "text": "Automatyzacja **1200 przypadków testowych** w Selenium w Example "
            "Logistics",
            "quote": "Automatyzacja 1 200 przypadków testowych w Selenium",
            "company": "Example Logistics (klient: Firma Beta)",
        }
    )
    assert result["verified"] is True


def test_two_sentences_are_rejected():
    result = _one(
        {
            **GOOD,
            "text": "Ograniczenie defektów o **około 30%** w Acme Bank. Koordynacja "
            "zespołu 6 testerów",
        }
    )
    assert result["issue"] == ISSUE_NOT_ONE_SENTENCE


def test_abbreviation_is_not_a_second_sentence():
    result = _one({**GOOD, "text": "Ograniczenie defektów o ok. **30%** w Acme Bank"})
    assert result["verified"] is True


def test_too_long_sentence_is_rejected():
    long_text = GOOD["text"] + " " + "w ramach programu modernizacji " * 5
    result = _one({**GOOD, "text": long_text.strip()})
    assert result["issue"] == ISSUE_TOO_LONG


def test_short_or_missing_quote_is_rejected():
    assert _one({**GOOD, "quote": "około 30%"})["issue"] == ISSUE_QUOTE_MISSING
    assert _one({**GOOD, "quote": ""})["issue"] == ISSUE_QUOTE_MISSING


def test_duplicate_of_point_1_is_dropped():
    items = [
        {
            "text": "**Ponad 8 lat** doświadczenia w testowaniu oprogramowania",
            "quote": "Starszy tester",
            "company": "Acme Bank",
        },
        GOOD,
    ]
    results = verify_results(items, ROLES, WHY)
    assert [r["text"] for r in results] == [GOOD["text"]]


def test_duplicate_of_point_2_is_dropped():
    items = [
        {
            "text": "Praktyczne doświadczenie z **Postmanem i Jirą** w testach systemów "
            "płatności",
            "quote": "Zaprojektowanie testów regresyjnych, które ograniczyły",
            "company": "Acme Bank",
        }
    ]
    assert verify_results(items, ROLES, WHY) == []


def test_blind_cv_sentence_must_not_name_a_company():
    result = _one(GOOD, blind=True)
    assert result["issue"] == ISSUE_COMPANY_NAMED
    anonymous = _one({**GOOD, "text": "Ograniczenie defektów o **około 30%** w banku"})
    assert anonymous["verified"] is True


def test_company_comes_from_the_role_with_the_quote():
    result = _one({**GOOD, "company": "Inna firma"})
    assert result["verified"] is True
    assert result["company"] == "Acme Bank"


def test_verified_first_in_model_order_and_capped():
    bad = {**GOOD, "text": "Ograniczenie defektów o **50%** w Acme Bank"}
    second = {
        "text": "Skrócenie regresji **z 5 dni do 1 dnia** w Example Logistics",
        "quote": "czas regresji skrócony z 5 dni do 1 dnia",
        "company": "Example Logistics (klient: Firma Beta)",
    }
    third = {
        "text": "Koordynacja **zespołu 6 testerów** w migracji do chmury w Acme Bank",
        "quote": "Koordynacja zespołu 6 testerów w projekcie migracji do chmury",
        "company": "Acme Bank",
    }
    invented = {
        "text": "Wdrożenie **3 nowych systemów** w Acme Bank",
        "quote": "wdrożenie trzech nowych systemów w banku",
        "company": "Acme Bank",
    }
    results = verify_results([bad, GOOD, second, invented, third], ROLES, WHY)
    assert len(results) == MAX_RESULTS
    assert [r["verified"] for r in results] == [True, True, True, False]
    assert results[0]["text"] == GOOD["text"]
    assert results[3]["text"] == bad["text"]


def test_trailing_period_follows_points_1_and_2():
    with_dots = [p + "." for p in WHY]
    result = verify_results([GOOD], ROLES, with_dots)[0]
    assert result["text"].endswith("Acme Bank.")
    without = verify_results([{**GOOD, "text": GOOD["text"] + "."}], ROLES, WHY)[0]
    assert without["text"] == GOOD["text"]


def test_unbalanced_bold_and_list_marker_are_cleaned():
    result = _one({**GOOD, "text": "- Ograniczenie defektów o **około 30% w Acme Bank"})
    assert result["text"] == "Ograniczenie defektów o około 30% w Acme Bank"


def test_unverified_result_never_reaches_page_1():
    bad = verify_results(
        [{**GOOD, "text": GOOD["text"].replace("30%", "40%")}], ROLES, WHY
    )
    assert chosen_result({"results": bad, "result_index": 0}) is None
    good = verify_results([GOOD], ROLES, WHY)
    assert chosen_result({"results": good, "result_index": 0}) == GOOD["text"]


# ── Scalenie z dodatkami strony 1 ───────────────────────────────────────────


def test_merge_keeps_other_keys_and_stores_sha():
    results = verify_results([GOOD], ROLES, WHY)
    merged = merged_extras(
        {"why": ["a", "b", "c"], "result_text": "", "result_index": 2}, results, "abc"
    )
    assert merged["why"] == ["a", "b", "c"]
    assert merged["result_text"] == ""
    assert merged["results"] == results
    assert merged["results_source_sha"] == "abc"
    assert merged["result_index"] == 0


def test_merge_keeps_choice_when_results_are_the_same():
    results = verify_results([GOOD], ROLES, WHY)
    extras = {"results": results, "result_index": 1, "results_source_sha": "old"}
    merged = merged_extras(extras, list(results), "new")
    assert merged["result_index"] == 1
    assert merged["results_source_sha"] == "new"
    assert extras["results_source_sha"] == "old"  # wejście bez zmian


def test_merge_on_empty_extras():
    merged = merged_extras(None, [], source_sha("<p>x</p>"))
    assert merged == {
        "results": [],
        "results_source_sha": source_sha("<p>x</p>"),
        "result_index": 0,
    }


# ── Odpowiedź modelu, prompt ────────────────────────────────────────────────


def test_parse_response_accepts_json_and_fenced_json():
    raw = json.dumps({"results": [GOOD]}, ensure_ascii=False)
    assert service.parse_response(raw) == [GOOD]
    assert service.parse_response(f"```json\n{raw}\n```") == [GOOD]


@pytest.mark.parametrize("raw", ["", "nie JSON", '{"items": []}', "[]"])
def test_parse_response_rejects_broken_answers(raw):
    with pytest.raises(ValueError):
        service.parse_response(raw)


def test_prompt_language_and_blind_variant():
    assert "po polsku" in service.system_prompt("pl", blind=False)
    assert "in English" in service.system_prompt("en", blind=False)
    assert "Blind CV" in service.system_prompt("pl", blind=True)
    assert "Blind CV" not in service.system_prompt("en", blind=False)


# ── Łańcuch HTML → model → lista (atrapa modelu i sesji) ────────────────────

PAYLOAD = {
    "candidate_name": "Jan Przykładowy",
    "position": "Tester oprogramowania",
    "language": "pl",
    "blind": False,
    "highlight_keywords": [],
    "why_points": WHY + ["Doświadczenie w testach API w Acme Bank"],
    "education": [],
    "skills": [{"label": "Testowanie:", "content": "Postman, Selenium"}],
    "certifications": [],
    "languages": ["Polski - ojczysty"],
    "experience": [
        {
            "position": role.position,
            "dates": role.dates,
            "company": role.company,
            "technologies": list(role.technologies),
            "responsibilities": list(role.duties),
        }
        for role in ROLES
    ],
}
HTML = render_interactive_html(PAYLOAD, None, document_only=True)


WHY_ANSWER = {
    "experience": {
        "text": "{LATA_IT} w IT jako tester, w bankowości",
        "it_roles": [0, 1],
        "role_roles": [],
    },
    "requirements": {"text": "", "evidence": []},
    "key_task": {"text": "", "quote": "", "source": "cv", "company": ""},
}


class _FakeSession:
    """Tyle sesji, ile potrzebuje `refresh_stage_cv`: get, scalar, commit, rollback."""

    def __init__(self, csv):
        self.csv = csv
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model, key):
        return self.csv if key == self.csv.id else None

    async def scalar(self, statement):
        return self.csv

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _Csv:
    def __init__(self, **values):
        self.id = 7
        self.cv_layout = "new"
        self.branded_status = "draft"
        self.branded_draft_html = HTML
        self.branded_language = "pl"
        self.branded_template = "standard"
        self.page1_extras = None
        self.__dict__.update(values)


@pytest.fixture
def model(monkeypatch):
    calls: list[dict] = []

    @asynccontextmanager
    async def no_quota(db, feature, *, user_id=None, units=1):
        yield None

    def fake_model(system, content, request_id):
        calls.append({"system": system, "content": content})
        return json.dumps({"results": calls_answer[0]}, ensure_ascii=False)

    def fake_why_model(system, content, request_id):
        why_calls.append({"system": system, "content": content})
        return json.dumps(WHY_ANSWER, ensure_ascii=False)

    async def no_inputs(db, csv):
        return WhyInputs(), None

    calls_answer = [[GOOD]]
    why_calls: list[dict] = []
    monkeypatch.setattr(service, "ai_feature", no_quota)
    monkeypatch.setattr(service, "_call_model", fake_model)
    monkeypatch.setattr(service, "_call_why_model", fake_why_model)
    monkeypatch.setattr(service, "load_why_inputs", no_inputs)
    monkeypatch.setattr(service, "api_key_configured", lambda model: True)
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    return calls, calls_answer


@pytest.mark.asyncio
async def test_refresh_writes_results_and_keeps_other_extras(model):
    calls, _ = model
    csv = _Csv(page1_extras={"why": ["x", "y", "z"], "result_index": 3})
    db = _FakeSession(csv)
    outcome = await service.refresh_stage_cv(db, csv.id)
    assert outcome.status == service.UPDATED
    extras = csv.page1_extras
    assert extras["why"] == ["x", "y", "z"]
    assert extras["result_index"] == 0
    assert extras["results_source_sha"] == source_sha(HTML)
    assert extras["results"][0]["verified"] is True
    assert extras["results"][0]["company"] == "Acme Bank"
    # Model dostaje role i punkty 1–2, bez imienia i nazwiska.
    sent = calls[0]["content"]
    assert "Jan Przykładowy" not in sent
    assert "Example Logistics" in sent
    assert "Doświadczenie w testach API" not in sent
    assert "po polsku" in calls[0]["system"]


@pytest.mark.asyncio
async def test_background_run_skips_when_sha_matches(model):
    calls, _ = model
    extras = {
        "results": [],
        "results_source_sha": source_sha(HTML),
        "result_index": 0,
        "why_generated": [],
        "why_source_sha": inputs_sha(HTML, WhyInputs()),
    }
    csv = _Csv(page1_extras=dict(extras))
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert outcome.status == service.UNCHANGED
    assert calls == []
    forced = await service.refresh_stage_cv(_FakeSession(csv), csv.id, force=True)
    assert forced.status == service.UPDATED
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_background_run_skips_classic_layout(model):
    calls, _ = model
    csv = _Csv(cv_layout="classic")
    outcome = await service.refresh_stage_cv(
        _FakeSession(csv), csv.id, only_new_layout=True
    )
    assert outcome.status == service.SKIPPED
    assert calls == []


@pytest.mark.asyncio
async def test_model_failure_leaves_extras_untouched(model, monkeypatch):
    def broken(system, content, request_id):
        raise TimeoutError("model nie odpowiedział")

    monkeypatch.setattr(service, "_call_model", broken)
    monkeypatch.setattr(service, "_call_why_model", broken)
    before = {"why": ["x"], "results_source_sha": "stary"}
    csv = _Csv(page1_extras=dict(before))
    db = _FakeSession(csv)
    outcome = await service.refresh_stage_cv(db, csv.id, force=True)
    assert outcome.status == service.FAILED
    assert csv.page1_extras == before
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_broken_model_answer_is_a_failure_not_an_empty_list(model):
    _, answer = model
    answer[0] = "nie lista"
    csv = _Csv()
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    # Zepsuta lista wyników nie zapisuje się jako pusta (bieg w tle spróbuje
    # znowu); zdania 1–3 z drugiego wywołania zapisują się normalnie.
    assert outcome.status == service.UPDATED
    assert outcome.reason == "results"
    assert "results" not in csv.page1_extras
    assert csv.page1_extras["why_generated"][0]["verified"] is True


@pytest.mark.asyncio
async def test_broken_why_answer_keeps_previous_sentences(model, monkeypatch):
    monkeypatch.setattr(service, "_call_why_model", lambda *a: "nie JSON")
    before = {"why": ["Moje zdanie.", "", ""], "why_source_sha": "stary"}
    csv = _Csv(page1_extras=dict(before))
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert outcome.status == service.UPDATED
    assert outcome.reason == "why"
    assert csv.page1_extras["why"] == ["Moje zdanie.", "", ""]
    assert csv.page1_extras["why_source_sha"] == "stary"
    assert csv.page1_extras["results"][0]["verified"] is True


@pytest.mark.asyncio
async def test_cv_without_role_points_needs_no_model(model):
    calls, _ = model
    csv = _Csv(branded_draft_html="<h1>Tester – Jan Przykładowy</h1><p>Krótko.</p>")
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert outcome.status == service.UPDATED
    assert csv.page1_extras["results"] == []
    assert calls == []


@pytest.mark.asyncio
async def test_missing_api_key_is_a_logged_failure(model, monkeypatch):
    monkeypatch.setattr(service, "api_key_configured", lambda model: False)
    csv = _Csv()
    outcome = await service.refresh_stage_cv(_FakeSession(csv), csv.id)
    assert outcome.status == service.FAILED
    assert csv.page1_extras is None


# ── Wyzwalacz po commicie ───────────────────────────────────────────────────


class _AsyncLike:
    def __init__(self, session):
        self.sync_session = session


@pytest.fixture
def spawned(monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(service, "_spawn", seen.append)
    monkeypatch.setattr(service, "api_key_configured", lambda model: True)
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    return seen


@pytest.mark.asyncio
async def test_trigger_runs_after_commit_only(spawned):
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        service.refresh_after_commit(_AsyncLike(session), 11)
        assert spawned == []
        session.commit()
    assert spawned == [11]


@pytest.mark.asyncio
async def test_trigger_is_dropped_on_rollback(spawned):
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.connection()
        service.refresh_after_commit(_AsyncLike(session), 12)
        session.rollback()
        session.commit()
    assert spawned == []


@pytest.mark.asyncio
async def test_trigger_needs_the_flag_and_a_key(spawned, monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    with Session(engine) as session:
        service.refresh_after_commit(_AsyncLike(session), 13)
        session.commit()
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    monkeypatch.setattr(service, "api_key_configured", lambda model: False)
    with Session(engine) as session:
        service.refresh_after_commit(_AsyncLike(session), 14)
        session.commit()
    assert spawned == []


def test_trigger_ignores_fake_sessions():
    service.refresh_after_commit(object(), 15)
    service.refresh_after_commit(_AsyncLike(object()), 16)
