"""Final factual gate contracts; model responses are controlled, not model evals."""

import copy
import json
import time

import pytest

from app.services.cv_generator_b2b import factual_verification as gate
from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.provider import CVGeneratorOverloadedError
from app.services.cv_generator_b2b.public_view import build_public_payload


SOURCE = "Jan Testowy. Programista. Tworzył API w Pythonie. Nie pracował z Kubernetes."
DOCUMENT = {
    "name": "Jan Testowy",
    "position": "Programista",
    "why_points": ["Tworzył API w Pythonie."],
    "experience": [],
}


@pytest.fixture(autouse=True)
def _source_stage_isolated_for_final_review_tests(monkeypatch):
    monkeypatch.setattr(
        svc,
        "extract_source_facts",
        lambda **kwargs: {"version": 1, "document": copy.deepcopy(DOCUMENT)},
    )


def review_response(content, **overrides):
    request = json.loads(content)
    return {
        "claims": [
            {
                "path": path,
                "status": "supported",
                "evidence": [{"source": "cv", "quote": SOURCE}],
                **overrides,
            }
            for path in request["claims"]
        ]
    }


def run_gate(data=None):
    return gate.verify_final_cv(
        data or DOCUMENT,
        cv_text=SOURCE,
        screening_notes="",
        identity="Jan Testowy",
        request_id="test",
    )


def test_every_field_requires_real_citations_and_report_is_private(monkeypatch):
    monkeypatch.setattr(
        gate,
        "analyze_with_ai",
        lambda content, *a, **k: json.dumps(review_response(content)),
    )
    report = run_gate()
    assert report["status"] == "verified"
    assert {item["path"] for item in report["claims"]} == set(
        gate.claim_inventory(DOCUMENT)
    )
    assert all(item["evidence"][0]["end"] == len(SOURCE) for item in report["claims"])
    assert report["source_sha256"]["cv"] and report["document_sha256"]
    public = build_public_payload({**DOCUMENT, "factual_verification": report})
    assert "factual_verification" not in public
    assert "source_sha256" not in str(public)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "unknown_source",
        "invented_quote",
        "empty_evidence",
        "non_json",
        "identity_for_skill",
    ],
)
def test_incomplete_or_fabricated_review_cannot_approve(monkeypatch, mutation):
    def response(content, *args, **kwargs):
        result = review_response(content)
        if mutation == "missing":
            result["claims"].pop()
        if mutation == "duplicate":
            result["claims"].append(result["claims"][0])
        if mutation == "extra":
            result["claims"].append({**result["claims"][0], "path": "/unknown"})
        if mutation == "unknown_source":
            result["claims"][0]["evidence"][0]["source"] = "champion"
        if mutation == "invented_quote":
            result["claims"][0]["evidence"][0]["quote"] = "not in source"
        if mutation == "empty_evidence":
            result["claims"][0]["evidence"] = []
        if mutation == "identity_for_skill":
            result["claims"][-1]["evidence"] = [
                {"source": "identity", "quote": "Jan Testowy"}
            ]
        if mutation == "non_json":
            return "approved"
        return json.dumps(result)

    monkeypatch.setattr(gate, "analyze_with_ai", response)
    with pytest.raises(gate.FactualVerificationError) as caught:
        run_gate()
    expected_reason = {
        "missing": "invalid_coverage",
        "duplicate": "invalid_coverage",
        "extra": "invalid_coverage",
        "unknown_source": "invalid_schema",
        "non_json": "invalid_json",
    }.get(mutation, "invalid_evidence")
    assert caught.value.reason == expected_reason
    assert str(caught.value) == "CV source verification did not pass"


@pytest.mark.parametrize(
    "claim,status",
    [
        ("AWS Certified Solutions Architect Professional", "unsupported"),
        ("Pracował z Kubernetes", "contradicted"),
        ("Zarządzał zespołem 3 programistów", "unsupported"),
        ("Projektował architekturę bankowej platformy płatniczej", "unsupported"),
        ("Oczekiwania: 180 PLN/h", "private"),
    ],
)
def test_negative_semantic_verdict_blocks_before_render(monkeypatch, claim, status):
    data = {**DOCUMENT, "why_points": [claim]}
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: SOURCE)
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(data))

    def verdict(content, *args, **kwargs):
        result = review_response(content)
        next(item for item in result["claims"] if item["path"] == "/why_points/0")[
            "status"
        ] = status
        return json.dumps(result)

    monkeypatch.setattr(gate, "analyze_with_ai", verdict)
    rendered = []
    monkeypatch.setattr(
        svc, "render_cv_to_bytes", lambda *a, **k: rendered.append(True)
    )
    with pytest.raises(svc.StandaloneGenerationError) as caught:
        run_pipeline()
    assert caught.value.code == "source_verification_failed"
    assert "podsumowanie" in str(caught.value)
    assert rendered == []


def run_pipeline(rule=None, prepared=None):
    return svc._run_generation_pipeline(
        cv_bytes=b"cv",
        cv_filename="test.docx",
        champion_dto=None,
        screening_notes_text="",
        language="pl",
        blind_cv=False,
        request_id="test",
        fallback_name="Jan Testowy",
        started_at=time.time(),
        job_id=None,
        job_title="Target vacancy, not evidence",
        client_rule=rule,
        prepared_source_facts=prepared,
    )


def test_verifier_sees_glossary_result_and_never_receives_client_rules_as_evidence(
    monkeypatch,
):
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: SOURCE)
    monkeypatch.setattr(
        svc,
        "analyze_with_ai",
        lambda *a, **k: json.dumps({**DOCUMENT, "position": "Software Developer"}),
    )
    requests = []

    def verdict(content, *args, **kwargs):
        requests.append(json.loads(content))
        return json.dumps(review_response(content, status="unsupported", evidence=[]))

    monkeypatch.setattr(gate, "analyze_with_ai", verdict)
    rule = CvRuleSnapshot(
        None,
        False,
        None,
        False,
        False,
        glossary=(("Software Developer", "Programista"), ("Pythonie", "Rust")),
    )
    with pytest.raises(svc.StandaloneGenerationError):
        run_pipeline(rule)
    # Reviewed translations precede the gate; arbitrary replacements are blocked.
    assert requests[0]["final_document"]["position"] == "Programista"
    assert requests[0]["final_document"]["why_points"] == ["Tworzył API w Pythonie."]
    assert requests[0]["sources"]["cv"] == SOURCE
    assert "Target vacancy" not in json.dumps(requests)
    assert "glossary" not in json.dumps(requests)


def test_unavailable_verifier_does_not_fall_back_to_warning_only(monkeypatch):
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: SOURCE)
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(DOCUMENT))

    def unavailable(*args, **kwargs):
        raise CVGeneratorOverloadedError("unavailable")

    monkeypatch.setattr(gate, "analyze_with_ai", unavailable)
    with pytest.raises(svc.StandaloneGenerationError) as caught:
        run_pipeline()
    assert caught.value.code == "source_verification_unavailable"


def test_successful_pipeline_saves_report_for_the_exact_final_document(monkeypatch):
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: SOURCE)
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(DOCUMENT))
    monkeypatch.setattr(
        gate,
        "analyze_with_ai",
        lambda content, *a, **k: json.dumps(review_response(content)),
    )
    rendered = []

    def render(data, *args):
        rendered.append(copy.deepcopy(data))
        return b"docx"

    monkeypatch.setattr(svc, "render_cv_to_bytes", render)
    result = run_pipeline()
    assert result.docx_bytes == b"docx"
    assert (
        result.render_payload["factual_verification"]
        == rendered[0]["factual_verification"]
    )
    assert result.render_payload["factual_verification"]["status"] == "verified"


def test_batches_cover_every_claim_even_for_long_cv(monkeypatch):
    data = {"why_points": ["Tworzył API w Pythonie."] * 85}
    requests = []

    def verdict(content, *args, **kwargs):
        requests.append(json.loads(content))
        return json.dumps(review_response(content))

    monkeypatch.setattr(gate, "analyze_with_ai", verdict)
    report = run_gate(data)
    assert [len(r["claims"]) for r in requests] == [40, 40, 5]
    assert len(report["claims"]) == 85


def test_missing_industry_never_becomes_an_it_claim():
    normalized = svc._normalize_candidate_data(
        {"experience": [{"company": "Acme", "position": "Magazynier"}]}, None
    )
    assert normalized["experience"][0]["industry"] == ""
    assert (
        build_public_payload({**normalized, "blind_cv": True})["experience"][0][
            "company"
        ]
        == "Firma"
    )


def test_summary_prompts_do_not_require_fabrication_prone_template():
    from app.services.cv_generator_b2b.prompts import get_prompt

    for language in ("pl", "en"):
        for mode in ("basic", "polished", "tailored"):
            prompt = get_prompt(language, False, mode)
            assert "[Biggest company]" not in prompt
            assert "[Największa firma]" not in prompt
            assert "ALL possessed must-have technologies MUST" not in prompt
            assert "WSZYSTKIE posiadane must-have technologie MUSZĄ" not in prompt
            assert "earliest start to the latest date" not in prompt
            assert "od najwcześniejszego startu do ostatniej daty" not in prompt
            assert "2–4" in prompt


def test_invalid_evidence_is_not_counted_as_a_correct_semantic_rejection(monkeypatch):
    monkeypatch.setattr(
        gate,
        "analyze_with_ai",
        lambda content, *a, **k: json.dumps(review_response(content, evidence=[])),
    )
    with pytest.raises(gate.FactualVerificationError) as caught:
        run_gate()
    assert caught.value.reason == "invalid_evidence"


def test_versioned_diagnostic_corpus_and_scoring_distinguish_errors():
    from scripts.eval_cv_factual_gate import load_cases, score

    cases, fingerprint = load_cases()
    assert len(cases) == 40 and len(fingerprint) == 64
    assert score(True, "accepted")
    assert score(False, "semantic_rejection")
    for broken in (
        "provider_error",
        "invalid_review",
        "invalid_evidence",
        "invalid_json",
        "invalid_schema",
        "invalid_coverage",
    ):
        assert not score(False, broken)
        assert not score(True, broken)


def test_limit_rewrite_is_reviewed_against_original_source_before_docx(monkeypatch):
    from app.services.cv_generator_b2b import editorial_limits

    original = "Jan Testowy. Testy migracji AWS wyłącznie w środowisku szkoleniowym, bez wdrożeń produkcyjnych."
    raw = {**DOCUMENT, "experience": [{"responsibilities": [original]}]}
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: original)
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(raw))
    monkeypatch.setattr(
        editorial_limits,
        "analyze_with_ai",
        lambda *a, **k: json.dumps(
            {
                "items": [
                    {
                        "path": "/experience/0/responsibilities/0",
                        "text": "Wdrażał produkcyjnie AWS.",
                    }
                ]
            }
        ),
    )
    requests = []

    def reject(content, *args, **kwargs):
        requests.append(json.loads(content))
        return json.dumps(review_response(content, status="unsupported", evidence=[]))

    monkeypatch.setattr(gate, "analyze_with_ai", reject)
    rendered = []
    monkeypatch.setattr(
        svc, "render_cv_to_bytes", lambda *a, **k: rendered.append(True)
    )
    with pytest.raises(svc.StandaloneGenerationError) as raised:
        run_pipeline(
            CvRuleSnapshot(None, False, None, False, False, max_bullet_chars=40)
        )
    assert raised.value.code == "source_verification_failed"
    assert requests[0]["sources"]["cv"] == original
    assert requests[0]["final_document"]["experience"][0]["responsibilities"] == [
        "Wdrażał produkcyjnie AWS."
    ]
    assert rendered == []


def test_two_variants_reuse_one_extraction_and_reject_different_sources(monkeypatch):
    from dataclasses import replace
    from unittest.mock import Mock

    extract_text = Mock(return_value=SOURCE)
    extract_facts = Mock(
        return_value={"version": 1, "document": copy.deepcopy(DOCUMENT)}
    )
    monkeypatch.setattr(svc, "extract_text_from_file", extract_text)
    monkeypatch.setattr(svc, "extract_source_facts", extract_facts)
    prepared = svc.prepare_source_facts(
        cv_bytes=b"cv",
        cv_filename="test.docx",
        screening_notes_text="",
        request_id="pair",
    )
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(DOCUMENT))
    monkeypatch.setattr(
        gate,
        "analyze_with_ai",
        lambda content, *a, **k: json.dumps(review_response(content)),
    )
    monkeypatch.setattr(svc, "render_cv_to_bytes", lambda *a, **k: b"docx")
    first = run_pipeline(prepared=prepared)
    first.render_payload["source_facts"]["document"]["why_points"].clear()
    second = run_pipeline(prepared=prepared)
    assert (
        second.render_payload["source_facts"]["document"]["why_points"]
        == DOCUMENT["why_points"]
    )
    extract_text.assert_called_once()
    extract_facts.assert_called_once()
    with pytest.raises(svc.StandaloneGenerationError) as error:
        run_pipeline(prepared=replace(prepared, cv_sha256="wrong-source"))
    assert error.value.code == "source_extraction_failed"
