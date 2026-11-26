"""Propozycja AI wyróżnika pod nazwiskiem w „Nowym CV” (Artur 26.11.2026).

Bez bazy: kontrola propozycji modelu (`cv_page1_highlight_checks`), scalenie
dodatków strony 1 (odrzucone nie wracają), łańcuch HTML → model → lista
z atrapą modelu i sesji (awaria = bez propozycji, dodatki bez zmian),
przyjęcie i odrzucenie w `PATCH …/cv/page1` (`_merged`), ponowne sprawdzenie
przyjętego wyróżnika przy renderze i to, że sama propozycja nie trafia do CV.
Trasy w Postgresie: `test_cv_page1.py`, `test_cv_page1_results_api.py`.
Dane fikcyjne.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from app.api.cv_page1 import Page1Update, _merged
from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.services import cv_page1_highlight as service
from app.services.ai_models import model_for
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_layout import forget_page1_result
from app.services.cv_new_content import cv_json_from_editor_html
from app.services.cv_new_layout import NewCvDocument, render_new_cv_html
from app.services.cv_new_layout.highlight import choice_from_extras
from app.services.cv_page1_highlight_checks import (
    ISSUE_COMPANY_NAMED,
    Entry,
    ISSUE_GENDERED,
    ISSUE_NOT_A_CERTIFICATE,
    ISSUE_NOT_AN_AWARD,
    ISSUE_NOT_MUST,
    ISSUE_NUMBER_NOT_IN_CV,
    ISSUE_QUOTE_MISSING,
    ISSUE_QUOTE_NOT_IN_CV,
    ISSUE_TOKEN_TOO_LONG,
    MAX_PROPOSALS,
    accepted_highlight,
    companies_from_cv_json,
    entries_from_cv_json,
    highlight_sha,
    merged_highlight,
    proposal_key,
    rechecked_highlight,
    verify_proposals,
)

AWARD_LINE = (
    "Wyróżnienie Best Project Manager 2021 za program KYC w klastrze bałtyckim."
)
CV = {
    "candidate_name": "Jan Przykładowy",
    "position": "Kierownik projektu",
    "language": "pl",
    "blind": False,
    "highlight_keywords": [],
    "why_points": ["Ponad 8 lat doświadczenia jako Kierownik projektu"],
    "education": [],
    "skills": [],
    "certifications": [
        "PRINCE2 Practitioner - Axelos (2021)",
        "Scrum Master - Scrum.org (2019)",
    ],
    "languages": [],
    "experience": [
        {
            "position": "Kierownik projektu",
            "dates": "01.2019 - obecnie",
            "company": "Example Bank",
            "technologies": ["Jira"],
            "responsibilities": [
                AWARD_LINE,
                "Prowadzenie zespołu 12 osób w projekcie migracji do chmury.",
                "Wdrażanie best practices w zarządzaniu ryzykiem.",
            ],
        },
        {
            "position": "Analityk",
            "dates": "03.2015 - 12.2018",
            "company": "Firma Beta",
            "technologies": [],
            "responsibilities": ["Analiza wymagań dla 3 systemów płatności."],
        },
    ],
}
HTML = render_interactive_html(CV, None, document_only=True)
CV_JSON = cv_json_from_editor_html(HTML, language="pl", blind=False).cv_json
ENTRIES = entries_from_cv_json(CV_JSON)
COMPANIES = companies_from_cv_json(CV_JSON)
MUST = ("PRINCE2 Practitioner", "Jira")

AWARD = {
    "kind": "award",
    "label": "Wyróżnienie Best Project Manager",
    "token": "2021",
    "text": "**Best Project Manager 2021** za program KYC w Example Bank.",
    "quote": "Wyróżnienie Best Project Manager 2021 za program KYC",
}
CERT = {
    "kind": "certificate",
    "label": "Certyfikat PRINCE2 Practitioner",
    "token": "PRINCE2",
    "text": "Certyfikat **PRINCE2 Practitioner** wydany przez Axelos w 2021 r.",
    "quote": "PRINCE2 Practitioner - Axelos (2021)",
}


def _verify(items, *, must=MUST, blind=False):
    return verify_proposals(items, ENTRIES, must, companies=COMPANIES, blind=blind)


def _one(item, **kw):
    (out,) = _verify([item], **kw)
    return out


# ── Sprawdzenie propozycji ──────────────────────────────────────────────────


def test_award_with_quote_from_the_cv_is_verified():
    out = _one(AWARD)
    assert out["verified"] is True, out
    assert out["source"] == "role"
    assert out["company"] == "Example Bank"
    assert out["key"] == proposal_key(AWARD)


def test_certificate_from_must_with_quote_is_verified():
    out = _one(CERT)
    assert out["verified"] is True, out
    assert out["source"] == "certification"


def test_without_quote_there_is_no_proposal():
    out = _one({**AWARD, "quote": ""})
    assert out["verified"] is False and out["issue"] == ISSUE_QUOTE_MISSING


def test_invented_quote_is_not_in_cv():
    out = _one({**AWARD, "quote": "Nagroda Lider Roku 2022 w Example Bank"})
    assert out["issue"] == ISSUE_QUOTE_NOT_IN_CV


def test_changed_year_is_not_in_cv():
    out = _one(
        {**AWARD, "token": "2022", "text": "**Best Project Manager 2022** za KYC."}
    )
    assert out["issue"] == ISSUE_NUMBER_NOT_IN_CV


def test_plain_duty_is_not_an_award():
    out = _one(
        {
            "kind": "award",
            "label": "Zespół 12 osób",
            "token": "12",
            "text": "Prowadzenie **zespołu 12 osób** w migracji do chmury.",
            "quote": "Prowadzenie zespołu 12 osób w projekcie migracji do chmury",
        }
    )
    assert out["issue"] == ISSUE_NOT_AN_AWARD


def test_best_practices_is_not_an_award():
    out = _one(
        {
            "kind": "award",
            "label": "Best practices",
            "token": "",
            "text": "Wdrażanie **best practices** w zarządzaniu ryzykiem.",
            "quote": "Wdrażanie best practices w zarządzaniu ryzykiem",
        }
    )
    assert out["issue"] == ISSUE_NOT_AN_AWARD


@pytest.mark.parametrize(
    "line",
    [
        "Wybór najlepszych dostawców IT dla banku",
        "Rozliczenia z tytułu umów leasingowych",
        "Won 3 new enterprise clients in the CEE region",
        "Managed top accounts across Poland",
        "Osiąganie wyróżniających się wyników sprzedaży w regionie",
    ],
)
def test_duty_with_an_award_like_word_is_not_an_award(line):
    """Przegląd 26.11.2026: „najlepszych”, „z tytułu”, „won”, „top” i
    „wyróżniających się” to zwykłe słowa obowiązku, nie nagroda."""
    item = {
        "kind": "award",
        "label": "Wyróżnik",
        "token": "",
        "text": "Wynik z CV.",
        "quote": line,
    }
    (out,) = verify_proposals(
        [item],
        [Entry("role", line, line, "Example Bank")],
        MUST,
        companies=[],
        blind=False,
    )
    assert out["issue"] == ISSUE_NOT_AN_AWARD, out


@pytest.mark.parametrize(
    "line",
    [
        "Received the Best IT Project Manager award for the Baltic Cluster in 2015",
        "Won the first prize in the national hackathon",
        "1. miejsce w ogólnopolskim konkursie programistycznym",
        "Laureat konkursu Lider Cyfryzacji 2020",
        "Uzyskanie wyróżnienia Best IT Project Manager w klastrze bałtyckim",
        "Tytuł „Pracownik Roku 2019” w dziale IT",
        "Employee of the Year 2022 in the delivery unit",
    ],
)
def test_real_awards_still_count(line):
    item = {
        "kind": "award",
        "label": "Wyróżnik",
        "token": "",
        "text": "Nagroda z CV.",
        "quote": line,
    }
    (out,) = verify_proposals(
        [item],
        [Entry("role", line, line, "Example Bank")],
        MUST,
        companies=[],
        blind=False,
    )
    assert out.get("issue") != ISSUE_NOT_AN_AWARD, out


def test_certificate_outside_must_is_rejected():
    out = _one(
        {
            "kind": "certificate",
            "label": "Certyfikat Scrum Master",
            "token": "PSM",
            "text": "Certyfikat **Scrum Master** z 2019 r.",
            "quote": "Scrum Master - Scrum.org (2019)",
        }
    )
    assert out["issue"] == ISSUE_NOT_MUST
    # Profil bez MUST — certyfikat nie ma z czym się zgadzać.
    assert _one(CERT, must=())["issue"] == ISSUE_NOT_MUST


def test_certificate_quoted_from_a_role_point_is_not_a_certificate():
    out = _one({**CERT, "quote": "Wyróżnienie Best Project Manager 2021"})
    assert out["issue"] == ISSUE_NOT_A_CERTIFICATE


def test_token_longer_than_the_wreath_is_rejected():
    assert _one({**AWARD, "token": "BestPM2021"})["issue"] == ISSUE_TOKEN_TOO_LONG


def test_gendered_form_is_rejected():
    out = _one({**AWARD, "text": "Nagrodzony tytułem **Best Project Manager 2021**."})
    assert out["issue"] == ISSUE_GENDERED


def test_blind_cv_must_not_name_the_company():
    out = _one(AWARD, blind=True)
    assert out["issue"] == ISSUE_COMPANY_NAMED
    ok = _one(
        {**AWARD, "text": "**Best Project Manager 2021** za program KYC w banku."},
        blind=True,
    )
    assert ok["verified"] is True and "company" not in ok


def test_verified_first_without_duplicates_and_capped():
    bad = {**AWARD, "quote": "Nagroda, której nie ma w CV wcale"}
    out = _verify([bad, AWARD, dict(AWARD), CERT, bad, bad])
    assert len(out) <= MAX_PROPOSALS
    assert [p["verified"] for p in out] == [True, True, False]
    assert out[0]["kind"] == "award" and out[1]["kind"] == "certificate"


def test_broken_items_are_skipped():
    assert _verify(["tekst", None, 5]) == []


# ── Scalenie, przyjęcie, odrzucenie ─────────────────────────────────────────


def test_merge_keeps_choice_and_drops_rejected_proposals():
    award, cert = _verify([AWARD, CERT])
    extras = {
        "why": ["zostaje"],
        "highlight": {"mode": "off"},
        "highlight_rejected": [award["key"]],
    }
    merged = merged_highlight(extras, [award, cert], "sha1")
    assert [p["kind"] for p in merged["highlight_proposals"]] == ["certificate"]
    assert merged["highlight"] == {"mode": "off"}
    assert merged["why"] == ["zostaje"]
    assert merged["highlight_source_sha"] == "sha1"


def _extras():
    return {"highlight_proposals": _verify([AWARD, CERT]), "why": ["zostaje"]}


def _key_of(item):
    return proposal_key(item)


def test_accepting_a_proposal_writes_mode_ai_with_quote():
    payload = Page1Update(highlight={"mode": "ai", "proposal": _key_of(CERT)})
    merged = _merged(_extras(), payload)
    assert merged["highlight"]["mode"] == "ai"
    assert merged["highlight"]["label"] == CERT["label"]
    assert merged["highlight"]["quote"] == CERT["quote"]
    assert merged["why"] == ["zostaje"]


def test_unverified_or_missing_proposal_cannot_be_accepted():
    extras = {"highlight_proposals": _verify([{**AWARD, "quote": ""}])}
    unverified = extras["highlight_proposals"][0]["key"]
    for key in (unverified, "nie-ma-takiej", None):
        with pytest.raises(HTTPException) as err:
            _merged(extras, Page1Update(highlight={"mode": "ai", "proposal": key}))
        assert err.value.status_code == 422


def test_accept_and_reject_follow_the_key_when_the_list_was_replaced():
    """Przegląd 26.11.2026: bieg w tle i „Poszukaj w CV” mogą podmienić listę między
    tym, co rekruter widzi, a jego kliknięciem — wybór idzie po odcisku, nie po numerze."""
    seen = _verify([AWARD, CERT])  # to widzi rekruter: [nagroda, certyfikat]
    other = {
        **AWARD,
        "label": "Inna nagroda",
        "quote": "Wyróżnienie Best Project Manager 2021",
    }
    replaced = {
        "highlight_proposals": _verify([other, CERT])
    }  # bieg w tle: [inna, certyfikat]
    accepted = _merged(
        replaced, Page1Update(highlight={"mode": "ai", "proposal": seen[1]["key"]})
    )
    assert accepted["highlight"]["label"] == CERT["label"]
    with pytest.raises(HTTPException) as err:  # nagrody, którą widział, już nie ma
        _merged(
            replaced, Page1Update(highlight={"mode": "ai", "proposal": seen[0]["key"]})
        )
    assert err.value.status_code == 422
    rejected = _merged(replaced, Page1Update(highlight_reject=seen[1]["key"]))
    assert [p["label"] for p in rejected["highlight_proposals"]] == ["Inna nagroda"]
    assert rejected["highlight_rejected"] == [seen[1]["key"]]


def test_accepting_a_proposal_whose_quote_left_the_cv_is_refused():
    payload = Page1Update(highlight={"mode": "ai", "proposal": _key_of(AWARD)})
    with pytest.raises(HTTPException) as err:
        _merged(_extras(), payload, lambda highlight: False)
    assert err.value.status_code == 422


def test_rejecting_removes_the_proposal_and_remembers_it():
    extras = _extras()
    merged = _merged(extras, Page1Update(highlight_reject=_key_of(AWARD)))
    assert [p["kind"] for p in merged["highlight_proposals"]] == ["certificate"]
    assert merged["highlight_rejected"] == [proposal_key(AWARD)]
    # Kolejny bieg modelu z tą samą nagrodą jej nie przywraca.
    again = merged_highlight(merged, _verify([AWARD, CERT]), "sha2")
    assert [p["kind"] for p in again["highlight_proposals"]] == ["certificate"]


def test_rejecting_the_accepted_proposal_returns_to_auto():
    accepted = _merged(
        _extras(), Page1Update(highlight={"mode": "ai", "proposal": _key_of(AWARD)})
    )
    rejected = _merged(accepted, Page1Update(highlight_reject=_key_of(AWARD)))
    assert "highlight" not in rejected
    with pytest.raises(HTTPException):
        _merged(_extras(), Page1Update(highlight_reject="nie-ma-takiej"))


def test_new_cv_forgets_proposals_and_the_ai_choice_but_not_rejections():
    accepted = _merged(
        _extras(), Page1Update(highlight={"mode": "ai", "proposal": _key_of(AWARD)})
    )
    accepted = {**accepted, "highlight_source_sha": "x", "highlight_rejected": ["k"]}
    kept = forget_page1_result(accepted)
    assert kept == {"highlight_rejected": ["k"]}
    off = forget_page1_result({"highlight": {"mode": "off"}, "highlight_proposals": []})
    assert off == {"highlight": {"mode": "off"}}


# ── Render: propozycja tylko po przyjęciu, cytat sprawdzany na bieżącej treści ─


def _page1(extras):
    doc = NewCvDocument.from_cv_json(CV_JSON, highlight=choice_from_extras(extras))
    html = render_new_cv_html(doc)
    return html[html.index("<div class='p1'>") : html.index("<div class='rest'>")]


def test_proposal_alone_never_reaches_page_1():
    page = _page1(_extras())
    assert "class='hl'" not in page
    assert "Best Project Manager" not in page


def test_accepted_proposal_is_on_page_1():
    accepted = _merged(
        _extras(), Page1Update(highlight={"mode": "ai", "proposal": _key_of(AWARD)})
    )
    page = _page1(rechecked_highlight(accepted, CV_JSON, blind=False))
    assert "<div class='hlk'>Wyróżnienie Best Project Manager</div>" in page
    assert "<b>Best Project Manager 2021</b> za program KYC" in page


def test_accepted_highlight_gives_way_when_the_quote_left_the_cv():
    accepted = _merged(
        _extras(), Page1Update(highlight={"mode": "ai", "proposal": _key_of(AWARD)})
    )
    edited = json.loads(json.dumps(CV))
    edited["experience"][0]["responsibilities"].pop(0)
    edited_json = cv_json_from_editor_html(
        render_interactive_html(edited, None, document_only=True),
        language="pl",
        blind=False,
    ).cv_json
    again = rechecked_highlight(accepted, edited_json, blind=False)
    assert "highlight" not in again
    assert again["highlight_proposals"] == accepted["highlight_proposals"]
    # Blind CV po przyjęciu: zdanie z nazwą firmy też ustępuje.
    assert "highlight" not in rechecked_highlight(accepted, CV_JSON, blind=True)
    custom = {"highlight": {"mode": "custom", "label": "A", "text": "B."}}
    assert rechecked_highlight(custom, edited_json, blind=False) == custom


# ── Łańcuch HTML → model → lista (atrapa modelu i sesji) ────────────────────


class _FakeSession:
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
    answer = [[AWARD, CERT]]
    features: list[AIFeatureKey] = []

    @asynccontextmanager
    async def quota(db, feature, *, user_id=None, units=1):
        features.append(feature)
        yield None

    def fake_model(system, content, request_id):
        calls.append({"system": system, "content": content})
        return json.dumps({"proposals": answer[0]}, ensure_ascii=False)

    async def must(db, csv):
        return MUST, None

    monkeypatch.setattr(service, "ai_feature", quota)
    monkeypatch.setattr(service, "_call_model", fake_model)
    monkeypatch.setattr(service, "load_must", must)
    monkeypatch.setattr(service, "api_key_configured", lambda model: True)
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    return calls, answer, features


def test_feature_has_its_own_key_in_the_registry():
    assert service.FEATURE is AIFeatureKey.cv_page1_highlight
    assert model_for(AIFeatureKey.cv_page1_highlight)


@pytest.mark.asyncio
async def test_refresh_writes_proposals_and_keeps_the_choice(model):
    calls, _, features = model
    csv = _Csv(page1_extras={"highlight": {"mode": "off"}, "why": ["x"]})
    outcome = await service.refresh_highlight(_FakeSession(csv), csv.id)
    assert outcome.status == service.UPDATED
    extras = csv.page1_extras
    assert [p["verified"] for p in extras["highlight_proposals"]] == [True, True]
    assert extras["highlight"] == {"mode": "off"}
    assert extras["why"] == ["x"]
    assert extras["highlight_source_sha"] == highlight_sha(HTML, MUST, 1)
    assert features == [AIFeatureKey.cv_page1_highlight]
    sent = calls[0]["content"]
    assert "Jan Przykładowy" not in sent
    assert "PRINCE2 Practitioner - Axelos (2021)" in sent and "Jira" in sent
    assert "po polsku" in calls[0]["system"]


@pytest.mark.asyncio
async def test_background_run_skips_when_input_did_not_change(model):
    calls, _, _ = model
    extras = {
        "highlight_proposals": [],
        "highlight_source_sha": highlight_sha(HTML, MUST, 1),
    }
    csv = _Csv(page1_extras=dict(extras))
    assert (await service.refresh_highlight(_FakeSession(csv), csv.id)).status == (
        service.UNCHANGED
    )
    assert calls == []
    forced = await service.refresh_highlight(_FakeSession(csv), csv.id, force=True)
    assert forced.status == service.UPDATED and len(calls) == 1


@pytest.mark.asyncio
async def test_background_run_skips_classic_layout(model):
    calls, _, _ = model
    csv = _Csv(cv_layout="classic")
    outcome = await service.refresh_highlight(
        _FakeSession(csv), csv.id, only_new_layout=True
    )
    assert outcome.status == service.SKIPPED and calls == []


@pytest.mark.asyncio
async def test_model_failure_means_no_proposal_and_no_error(model, monkeypatch):
    def broken(system, content, request_id):
        raise TimeoutError("model nie odpowiedział")

    monkeypatch.setattr(service, "_call_model", broken)
    before = {"highlight": {"mode": "custom", "label": "A", "text": "B."}}
    csv = _Csv(page1_extras=dict(before))
    db = _FakeSession(csv)
    outcome = await service.refresh_highlight(db, csv.id, force=True)
    assert outcome.status == service.FAILED
    assert csv.page1_extras == before
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_missing_provider_key_is_a_failure_not_an_error(model, monkeypatch):
    monkeypatch.setattr(service, "api_key_configured", lambda model: False)
    csv = _Csv()
    outcome = await service.refresh_highlight(_FakeSession(csv), csv.id, force=True)
    assert outcome.status == service.FAILED and csv.page1_extras is None


@pytest.mark.asyncio
async def test_broken_answer_is_a_failure_not_an_empty_list(model):
    _, answer, _ = model
    answer[0] = "nie lista"
    csv = _Csv()
    outcome = await service.refresh_highlight(_FakeSession(csv), csv.id)
    assert outcome.status == service.FAILED and csv.page1_extras is None


@pytest.mark.asyncio
async def test_empty_answer_is_stored_as_searched_without_proposals(model):
    _, answer, _ = model
    answer[0] = []
    csv = _Csv()
    outcome = await service.refresh_highlight(_FakeSession(csv), csv.id)
    assert outcome.status == service.UPDATED
    assert csv.page1_extras["highlight_proposals"] == []


def test_prompt_language_and_blind_variant():
    assert "po polsku" in service.system_prompt("pl", blind=False)
    assert "in English" in service.system_prompt("en", blind=False)
    assert "Blind CV" in service.system_prompt("pl", blind=True)
    assert "Blind CV" not in service.system_prompt("pl", blind=False)


def test_accepted_highlight_is_trimmed_to_the_page_limits():
    out = accepted_highlight({**AWARD, "label": "x" * 90, "token": "y" * 20})
    assert len(out["label"]) == 60 and len(out["token"]) == 8
