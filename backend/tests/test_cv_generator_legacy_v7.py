"""Production default: the CV generator runs the 2bc6b14f flow (prompt v7).

Users reported that CVs changed after the 09-09/09-10 rebuild (#1444 and
follow-ups), so generation runs the pre-rebuild flow unless
``CV_GENERATION_PIPELINE=v10``. These tests pin what "pre-rebuild" means on
observable effects: what reached the model, what landed in the payload and
what the approval code can do with it. ``conftest`` pins the rebuilt pipeline
for the rest of the suite, so every test here deletes both variables first.
"""

import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.legacy_v7 import (
    legacy_pipeline_enabled,
    pipeline as legacy,
)
from app.services.cv_generator_b2b.legacy_v7.prompts import (
    get_prompt as legacy_prompt,
)
from app.services.cv_generator_b2b.prompts import get_prompt as rebuilt_prompt

_CV_TEXT = (
    "Jan Kowalski\n"
    "Backend Developer\n"
    "01.2015 – 07.2019, Acme Sp. z o.o., Backend Developer\n"
    "Utrzymanie API w Pythonie. Technologie: Python, PostgreSQL, Kubernetes.\n"
)


def _ai_json(**overrides):
    data = {
        "name": "Jan Kowalski",
        "first_name": "Jan",
        "position": "Backend Developer",
        "why_points": ["3 lata doświadczenia jako Backend Developer"],
        "education": [],
        "skills": [{"label": "Backend", "content": "Python, PostgreSQL"}],
        "certifications": [],
        "languages": ["Polski – ojczysty"],
        "experience": [
            {
                "dates": "01.2015 – 07.2019",
                "company": "Acme Sp. z o.o.",
                "position": "Backend Developer",
                "responsibilities": ["Utrzymanie API w Pythonie"],
                "technologies": ["Python", "PostgreSQL", "Kubernetes"],
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def defaults(monkeypatch):
    """Production env (both flags unset), model/extractor stubbed, and every
    entry point of the rebuilt pipeline booby-trapped."""
    monkeypatch.delenv("CV_GENERATION_PIPELINE", raising=False)
    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    seen = {"calls": [], "extracted": 0, "response": _ai_json()}

    def extract(data, name):
        seen["extracted"] += 1
        return _CV_TEXT

    def analyze(user_content, request_id, system=None, **kwargs):
        seen["calls"].append({"user": user_content, "system": system, **kwargs})
        return json.dumps(seen["response"])

    def forbidden(*args, **kwargs):
        raise AssertionError("the rebuilt pipeline must not run by default")

    monkeypatch.setattr(legacy, "extract_text_from_file", extract)
    monkeypatch.setattr(legacy, "analyze_with_ai", analyze)
    monkeypatch.setattr(legacy, "render_cv_to_bytes", lambda *a, **k: b"DOCX")
    for name in ("extract_source_facts", "verify_final_cv", "analyze_with_ai"):
        monkeypatch.setattr(svc, name, forbidden)
    return seen


def _run(mode="polished", champion=None, rule=None, prepared=None, cv=b"cv"):
    return svc._run_generation_pipeline(
        cv_bytes=cv,
        cv_filename="cv.pdf",
        champion_dto=champion,
        screening_notes_text="Kandydat potwierdził znajomość Pythona.",
        language="pl",
        blind_cv=False,
        request_id="legacy-test",
        fallback_name="Jan Kowalski",
        started_at=time.time(),
        job_id=1,
        job_title="Backend Developer",
        content_mode=mode,
        client_rule=rule,
        prepared_source_facts=prepared,
    )


def _champion():
    return ChampionProfileForPrompt(
        must_have=["Kubernetes"],
        nice_to_have=["Terraform"],
        responsibilities="Utrzymanie klastrów produkcyjnych",
    )


def _rule(**overrides):
    return CvRuleSnapshot(
        filename_pattern=None,
        spaces_to_underscores=False,
        cv_language=None,
        requires_en_copy=False,
        requires_rodo_consent_block=False,
        version=1,
        **overrides,
    )


# ── Routing ───────────────────────────────────────────────────────────────


def test_flag_defaults_to_the_legacy_flow_and_v10_selects_the_rebuilt_one(
    monkeypatch,
):
    monkeypatch.delenv("CV_GENERATION_PIPELINE", raising=False)
    assert legacy_pipeline_enabled()
    for value in ("v10", "V10 ", "source_facts"):
        monkeypatch.setenv("CV_GENERATION_PIPELINE", value)
        assert not legacy_pipeline_enabled()
    monkeypatch.setenv("CV_GENERATION_PIPELINE", "legacy")
    assert legacy_pipeline_enabled()


def test_v10_flag_routes_generation_to_the_rebuilt_pipeline(defaults, monkeypatch):
    monkeypatch.setenv("CV_GENERATION_PIPELINE", "v10")

    class Routed(Exception):
        pass

    def rebuilt_entry(**kwargs):
        raise Routed

    monkeypatch.setattr(svc, "extract_source_facts", rebuilt_entry)
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: _CV_TEXT)
    with pytest.raises(Routed):
        _run()
    assert defaults["calls"] == []


# ── What reaches the model ────────────────────────────────────────────────


def test_one_model_call_reads_the_raw_cv_with_the_v7_prompt(defaults):
    result = _run("polished")
    assert len(defaults["calls"]) == 1
    call = defaults["calls"][0]
    assert call["user"].startswith(f"<cv>\n{_CV_TEXT.strip()}\n</cv>")
    assert "<screening_notes>" in call["user"]
    assert "<source_facts>" not in call["user"]
    # Below "tailored" the Champion section is withheld, as at the baseline.
    assert "<champion_profile>" not in call["user"]
    assert call["system"] == legacy_prompt("pl", False, "polished")
    assert call["system"] != rebuilt_prompt("pl", False, "polished")
    assert result.docx_bytes == b"DOCX"


def test_frozen_v7_prompt_keeps_the_baseline_instructions():
    prompt = legacy_prompt("pl", False, "tailored")
    assert prompt.startswith("Jesteś ekspertem w analizie CV.")
    assert "NIE zaniżaj" in prompt
    assert "<source_facts>" not in prompt
    assert legacy_prompt("en", False, "polished").startswith(
        "You are an expert in CV analysis."
    )


def test_tailored_mode_sends_the_champion_section(defaults):
    _run("tailored", champion=_champion())
    assert "<champion_profile>" in defaults["calls"][0]["user"]
    assert "Kubernetes" in defaults["calls"][0]["user"]


# ── What lands in the document ────────────────────────────────────────────


def test_bold_only_champion_list_in_tailored_and_none_below(defaults):
    polished = _run("polished", champion=_champion())
    assert "highlight_keywords" not in polished.render_payload
    tailored = _run("tailored", champion=_champion())
    assert tailored.render_payload["highlight_keywords"] == ["Kubernetes", "Terraform"]


def test_missing_industry_defaults_to_it_like_the_baseline(defaults):
    result = _run()
    assert result.render_payload["experience"][0]["industry"] == "IT"


def test_career_headline_uses_the_baseline_rounding(defaults):
    # 01.2015–07.2019 = 55 months: the baseline rounds to 5, the rebuilt
    # pipeline floors to 4.
    result = _run()
    assert result.render_payload["why_points"][0].startswith("5 lat doświadczenia")


def test_overlong_bullets_are_shortened_not_rejected(defaults):
    long_bullet = (
        "Utrzymanie i rozwój rozproszonego API w Pythonie dla klientów bankowych"
    )
    defaults["response"] = _ai_json(
        experience=[{**_ai_json()["experience"][0], "responsibilities": [long_bullet]}]
    )
    result = _run(rule=_rule(max_bullet_chars=30))
    bullet = result.render_payload["experience"][0]["responsibilities"][0]
    assert len(bullet) <= 30
    assert bullet.endswith("…")
    assert any("skrócono 1 punktów" in w for w in result.warnings)


def test_payload_keeps_the_keys_approval_and_downloads_rely_on(defaults):
    rule = _rule()
    result = _run(rule=rule)
    payload = result.render_payload
    assert "source_facts" not in payload
    assert "factual_verification" not in payload
    assert payload["client_rule_snapshot"]["version"] == 1
    provenance = payload["editorial_provenance"]
    assert provenance["pipeline"] == "legacy_v7"
    assert provenance["cv_sha256"] == hashlib.sha256(b"cv").hexdigest()
    assert payload["artifact_provenance"]["template_sha256"]
    assert result.template_bytes


# ── Previews / second language share one AI-free preparation ─────────────


def test_prepared_sources_never_call_the_model_and_are_reused(defaults):
    prepared = svc.prepare_source_facts(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        screening_notes_text="Kandydat potwierdził znajomość Pythona.",
        request_id="legacy-test",
    )
    assert prepared.cv_text == _CV_TEXT
    assert prepared.facts_json == "null"
    assert defaults["calls"] == []
    _run(prepared=prepared)
    _run(prepared=prepared)
    assert defaults["extracted"] == 1
    assert len(defaults["calls"]) == 2


def test_prepared_sources_are_bound_to_their_exact_inputs(defaults):
    prepared = svc.prepare_source_facts(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        screening_notes_text="Kandydat potwierdził znajomość Pythona.",
        request_id="legacy-test",
    )
    with pytest.raises(svc.StandaloneGenerationError) as error:
        _run(prepared=prepared, cv=b"other cv")
    assert error.value.code == "source_extraction_failed"
    assert defaults["calls"] == []


# ── The real renderer accepts the legacy payload ──────────────────────────


def test_real_render_and_rerender_of_a_legacy_payload(defaults, monkeypatch):
    from app.services.cv_generator_b2b.docx_renderer import render_cv_to_bytes

    monkeypatch.setattr(legacy, "render_cv_to_bytes", render_cv_to_bytes)
    result = _run("tailored", champion=_champion())
    assert result.docx_bytes[:2] == b"PK"
    assert (
        hashlib.sha256(result.docx_bytes).hexdigest()
        == result.render_payload["artifact_provenance"]["generated_docx_sha256"]
    )
    assert svc.rerender_docx_from_payload(result.render_payload)[:2] == b"PK"


# ── Approval does not require an AI review while evidence is advisory ─────


async def test_unchanged_generation_can_be_approved_without_ai_review(monkeypatch):
    from app.services.cv_standalone_approval import approve_unchanged_generation

    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    doc = SimpleNamespace(
        id=7,
        client_id=None,
        client_rule_version=None,
        status="ready",
        render_payload={"name": "Jan", "position": "Engineer", "language": "pl"},
        docx_content=b"exact docx",
        docx_sha256=hashlib.sha256(b"exact docx").hexdigest(),
        filename="cv.docx",
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock()
    )
    version = await approve_unchanged_generation(db, doc, 9)
    assert version.generated_owner_id == 7
    assert version.render_metadata["generation_review_available"] is False
    db.add.assert_called_once()


async def test_editor_approval_skips_the_paid_review_while_evidence_is_advisory(
    monkeypatch,
):
    from app.services import cv_approval_review as review

    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("no AI source review while evidence is advisory")

    monkeypatch.setattr(review, "load_review_source", forbidden)
    monkeypatch.setattr(review, "verify_editor_content", forbidden)
    draft = SimpleNamespace(
        id=5, edit_revision=7, generated_document_id=11, branded_render_metadata={}
    )
    result = await review.prepare_approval_review(
        AsyncMock(), draft, "<p>Edited claim</p>"
    )
    assert result["status"] == "unverified"
    assert result["method"] == "evidence_enforcement_off"


# ── M05-B01: lata w „Dlaczego nasz kandydat" liczone do DZIŚ ──────────────


def test_model_gets_todays_date_outside_the_cached_system_prompt(defaults):
    from datetime import date

    _run()
    call = defaults["calls"][0]
    today = date.today()
    assert "<generation_date>" in call["user"]
    assert today.strftime("%m.%Y") in call["user"]
    # The cached system prompt stays byte-for-byte the frozen v7 one.
    assert call["system"] == legacy_prompt("pl", False, "polished")
    assert today.strftime("%m.%Y") not in call["system"]


def test_generation_date_block_speaks_the_document_language():
    from datetime import date

    pl = legacy.build_generation_date_block("pl", date(2026, 9, 14))
    en = legacy.build_generation_date_block("en", date(2026, 9, 14))
    assert "14.09.2026" in pl and "09.2026" in pl and "obecnie" in pl
    assert "2026-09-14" in en and "09.2026" in en


def _roles(*roles):
    return [
        {"position": position, "company": company, "dates": dates}
        for position, company, dates in roles
    ]


def test_role_bound_figure_is_recomputed_from_that_roles_dates():
    from app.services.cv_generator_b2b.legacy_v7._helpers import _fix_scoped_years

    data = {
        "experience": _roles(
            ("Senior Backend Developer", "Test Company Alfa", "01.2017 – 12.2024")
        ),
        "why_points": [
            "6 lat jako Backend Developer, w tym ponad 3 lata w obecnej roli"
        ],
    }
    _fix_scoped_years(data, "pl")
    # 96 months → 8; the "w obecnej roli" sub-figure is not tied to a name.
    assert data["why_points"] == [
        "8 lat jako Backend Developer, w tym ponad 3 lata w obecnej roli"
    ]


def test_company_bound_figure_is_recomputed_from_that_companys_roles():
    from app.services.cv_generator_b2b.legacy_v7._helpers import _fix_scoped_years

    data = {
        "experience": _roles(
            ("QA Engineer", "Test Company Zeta", "05.2019 – 12.2024"),
            ("Tester", "Test Company Beta", "01.2015 – 04.2019"),
        ),
        "why_points": ["Ponad 4 lata w Test Company Zeta przy testach API"],
    }
    _fix_scoped_years(data, "pl")
    # Only Zeta's 68 months count (→ 6), never Beta's.
    assert data["why_points"] == ["6 lat w Test Company Zeta przy testach API"]


def test_scoped_fix_never_adds_years_from_another_role():
    from app.services.cv_generator_b2b.legacy_v7._helpers import _fix_scoped_years

    data = {
        "experience": _roles(
            ("Warehouse worker", "Test Company Gamma", "01.2010 – 12.2017"),
            ("Python Developer", "Test Company Delta", "01.2018 – 12.2020"),
        ),
        "why_points": [
            "2 lata jako Python Developer",
            "5 years as a Data Engineer",  # no such role → untouched
            "4 lata jako Developera",  # inflected, no exact match → untouched
            "3 lata doświadczenia jako Python Developer",  # baseline headline
        ],
    }
    _fix_scoped_years(data, "pl")
    assert data["why_points"] == [
        "3 lata jako Python Developer",
        "5 years as a Data Engineer",
        "4 lata jako Developera",
        "3 lata doświadczenia jako Python Developer",
    ]


def test_ongoing_role_figure_lands_in_document_without_coverage_warning(defaults):
    from app.services.cv_generator_b2b.legacy_v7._helpers import (
        _total_experience_years,
    )

    role = {
        "dates": "01.2019 – obecnie",
        "company": "Test Company Alfa",
        "position": "Backend Developer",
        "responsibilities": ["Utrzymanie API w Pythonie"],
        "technologies": ["Python"],
    }
    defaults["response"] = _ai_json(
        why_points=["6 lat jako Backend Developer"], experience=[role]
    )
    result = _run()
    expected = _total_experience_years([role])
    point = result.render_payload["why_points"][0]
    assert point.startswith(f"{expected} ")
    assert point.endswith("jako Backend Developer")
    assert not any(
        w.startswith("BRAK POKRYCIA") and "why_points" in w for w in result.warnings
    )


# ── M05-B07: rok graniczny z samych lat nie jest nakładaniem się okresów ────


def test_year_only_roles_sharing_a_boundary_year_do_not_warn():
    from app.services.cv_generator_b2b.legacy_v7._helpers import (
        _date_overlap_warnings,
    )

    data = {
        "experience": [
            {"company": "Test Company Theta", "dates": "2020 - 2026"},
            {"company": "Test Company Iota", "dates": "2017 - 2020"},
        ]
    }
    assert _date_overlap_warnings(data, "pl") == []


def test_year_only_roles_with_certain_overlap_still_warn():
    from app.services.cv_generator_b2b.legacy_v7._helpers import (
        _date_overlap_warnings,
    )

    data = {
        "experience": [
            # Nawet najwęższy odczyt (12.2019–01.2022 i 12.2020–01.2026)
            # daje dwa wspólne miesiące.
            {"company": "Test Company Theta", "dates": "2020 - 2026"},
            {"company": "Test Company Iota", "dates": "2019 - 2022"},
            {"company": "Test Company Kappa", "dates": "03.2021 - obecnie"},
        ]
    }
    warnings = _date_overlap_warnings(data, "pl")
    assert any("Theta" in w and "Iota" in w for w in warnings)
    assert any("Iota" in w and "Kappa" in w for w in warnings)
