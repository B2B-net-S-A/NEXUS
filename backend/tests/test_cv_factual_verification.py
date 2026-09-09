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
    with pytest.raises(gate.FactualVerificationError):
        run_gate()


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


def run_pipeline(rule=None):
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
    )


def test_verifier_sees_glossary_result_and_never_receives_client_rules_as_evidence(
    monkeypatch,
):
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *a, **k: SOURCE)
    monkeypatch.setattr(svc, "analyze_with_ai", lambda *a, **k: json.dumps(DOCUMENT))
    requests = []

    def verdict(content, *args, **kwargs):
        requests.append(json.loads(content))
        return json.dumps(review_response(content, status="unsupported", evidence=[]))

    monkeypatch.setattr(gate, "analyze_with_ai", verdict)
    rule = CvRuleSnapshot(
        None, False, None, False, False, glossary=(("Pythonie", "Rust"),)
    )
    with pytest.raises(svc.StandaloneGenerationError):
        run_pipeline(rule)
    assert requests[0]["final_document"]["why_points"] == ["Tworzył API w Rust."]
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
