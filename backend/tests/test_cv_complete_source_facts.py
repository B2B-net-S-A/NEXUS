"""Full history survives editorial limits; evidence validation is not model eval."""

import copy
from io import BytesIO
import json
import time

from docx import Document
import pytest

from app.services.cv_generator_b2b import source_facts as facts
from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b import factual_verification as gate
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.public_view import build_public_payload


SOURCE = """Jan Testowy
01.2018 – 12.2020 Firma B. Analityk. Przygotowywał zapytania SQL.
01.2010 – 12.2017 Firma A. Magazynier. Kompletował zamówienia.
2009 Uczelnia Testowa. Licencjat.
"""
FULL = {
    "name": "Jan Testowy",
    "first_name": "Jan",
    "position": "",
    "experience": [
        {
            "dates": "01.2018 – 12.2020",
            "company": "Firma B",
            "industry": "",
            "position": "Analityk",
            "responsibilities": ["Przygotowywał zapytania SQL."],
            "technologies": ["SQL"],
        },
        {
            "dates": "01.2010 – 12.2017",
            "company": "Firma A",
            "industry": "",
            "position": "Magazynier",
            "responsibilities": ["Kompletował zamówienia."],
            "technologies": [],
        },
    ],
    "education": [
        {
            "dates": "2009",
            "institution": "Uczelnia Testowa",
            "degree": "Licencjat",
            "location": "",
        }
    ],
    "skills": [],
    "certifications": [],
    "languages": [],
}


def response():
    return {
        "document": copy.deepcopy(FULL),
        "evidence": [
            {"path": "/name", "source": "cv", "quote": "Jan Testowy"},
            {"path": "/first_name", "source": "cv", "quote": "Jan Testowy"},
            {"path": "/experience/0", "source": "cv", "quote": SOURCE.splitlines()[1]},
            {"path": "/experience/1", "source": "cv", "quote": SOURCE.splitlines()[2]},
            {"path": "/education/0", "source": "cv", "quote": SOURCE.splitlines()[3]},
        ],
    }


def test_valid_source_ledger_covers_every_populated_field():
    result = facts.validate_extraction(
        json.dumps(response()), {"cv": SOURCE, "screening_notes": ""}
    )
    assert result["document"] == FULL
    assert set(result["field_evidence"]) == set(facts.source_leaves(FULL))
    for citation in result["evidence"]:
        assert SOURCE[citation["start"] : citation["end"]]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "invented_quote",
        "invented_value",
        "wrong_role_quote",
        "precision",
        "extra_key",
    ],
)
def test_unbound_or_mutated_facts_stop_before_editing(mutation):
    payload = response()
    if mutation == "missing":
        payload["evidence"].pop()
    elif mutation == "invented_quote":
        payload["evidence"][0]["quote"] = "Not in source"
    elif mutation == "invented_value":
        payload["document"]["experience"][0]["technologies"] = ["Kubernetes"]
    elif mutation == "wrong_role_quote":
        payload["evidence"][2]["quote"] = SOURCE.splitlines()[2]
    elif mutation == "precision":
        payload["document"]["education"][0]["dates"] = "01.2009 – 12.2009"
    elif mutation == "extra_key":
        payload["document"]["why_points"] = ["A fabricated marketing summary"]
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(
            json.dumps(payload), {"cv": SOURCE, "screening_notes": ""}
        )


def test_limited_cv_keeps_eleven_years_and_full_private_history(monkeypatch):
    calls = []

    def extract(content, request_id, system):
        calls.append(("extract", json.loads(content), system))
        return json.dumps(response())

    def edit(content, request_id, system):
        calls.append(("edit", content, system))
        # This is the audit reproduction: the model obeyed max_roles=1 already.
        return json.dumps(
            {
                **copy.deepcopy(FULL),
                "education": [],
                "experience": [FULL["experience"][0]],
                "why_points": ["11 lat doświadczenia zawodowego."],
            }
        )

    def review(content, request_id, system, response_schema):
        assert response_schema is gate.REVIEW_RESPONSE_SCHEMA
        data = json.loads(content)
        return json.dumps(
            {
                "claims": [
                    {
                        "path": path,
                        "status": "supported",
                        "evidence": [{"source": "cv", "quote": SOURCE}],
                    }
                    for path in data["claims"]
                ]
            }
        )

    monkeypatch.setattr(svc, "extract_text_from_file", lambda *args: SOURCE)
    monkeypatch.setattr(facts, "analyze_with_ai", extract)
    monkeypatch.setattr(svc, "analyze_with_ai", edit)
    monkeypatch.setattr(gate, "analyze_with_ai", review)
    rule = CvRuleSnapshot(
        None, False, None, False, False, max_roles=1, omit_sections=("education",)
    )
    result = svc._run_generation_pipeline(
        cv_bytes=b"synthetic",
        cv_filename="cv.docx",
        champion_dto=None,
        screening_notes_text="PRIVATE INTERNAL NOTE",
        language="pl",
        blind_cv=False,
        request_id="synthetic",
        fallback_name="Jan Testowy",
        started_at=time.time(),
        job_id=None,
        job_title="",
        client_rule=rule,
    )
    payload = result.render_payload
    assert payload["why_points"] == ["11 lat doświadczenia zawodowego."]
    assert len(payload["experience"]) == 1 and payload["education"] == []
    assert payload["source_facts"]["document"] == FULL
    assert payload["source_facts"]["tenure"]["career_months"] == 132
    assert calls[0][1] == {"cv": SOURCE, "screening_notes": "PRIVATE INTERNAL NOTE"}
    assert "max_roles" not in str(calls[0]) and "maksymalnie 1" not in str(calls[0])
    assert "PRIVATE INTERNAL NOTE" not in calls[1][1]
    assert "source_facts" not in build_public_payload(payload)
    assert "editorial_provenance" not in build_public_payload(payload)
    provenance = payload["editorial_provenance"]
    assert provenance["prompt_version"] == svc.PROMPT_VERSION
    import hashlib

    assert (
        provenance["system_prompt_sha256"]
        == hashlib.sha256(svc.get_prompt("pl", False, "polished").encode()).hexdigest()
    )
    assert len(provenance["rule_sha256"]) == 64
    assert len(provenance["input_sha256"]) == 64
    doc = Document(BytesIO(result.docx_bytes))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "11 lat doświadczenia zawodowego." in text
    assert "Firma A" not in text and "Uczelnia Testowa" not in text


def test_unreadable_full_extraction_cannot_fall_back_to_truncated_history(monkeypatch):
    monkeypatch.setattr(svc, "extract_text_from_file", lambda *args: SOURCE)
    monkeypatch.setattr(facts, "analyze_with_ai", lambda *args, **kwargs: "not JSON")
    edited = []
    monkeypatch.setattr(
        svc, "analyze_with_ai", lambda *args, **kwargs: edited.append(True)
    )
    with pytest.raises(svc.StandaloneGenerationError) as error:
        svc._run_generation_pipeline(
            cv_bytes=b"cv",
            cv_filename="cv.docx",
            champion_dto=None,
            screening_notes_text="",
            language="pl",
            blind_cv=False,
            request_id="synthetic",
            fallback_name=None,
            started_at=time.time(),
            job_id=None,
            job_title="",
        )
    assert error.value.code == "source_extraction_failed"
    assert edited == []


def test_oversized_response_is_rejected_before_json_model_allocation(monkeypatch):
    from unittest.mock import Mock

    parse = Mock(side_effect=AssertionError("Oversized input reached JSON parser"))
    monkeypatch.setattr(facts.Extraction, "model_validate_json", parse)
    with pytest.raises(facts.SourceFactsError):
        facts.validate_extraction(" " * (facts.MAX_EXTRACTION_RESPONSE_CHARS + 1), {})
    parse.assert_not_called()
