"""Mapping a captured payload must not replace or read a generated document."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.cv_generator_b2b import requirement_map as mapping


async def test_map_result_is_bound_to_supplied_content_and_keeps_inputs(monkeypatch):
    payload = {"language": "pl", "why_points": ["Testy AWS tylko szkoleniowo."]}
    requirements = [{"name": "AWS", "kind": "must"}]
    original = copy.deepcopy(payload)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    provider = AsyncMock(
        return_value=SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "items": [
                                {
                                    "requirement": "AWS",
                                    "status": "partial",
                                    "evidence": [
                                        {
                                            "quote": "Testy AWS tylko szkoleniowo.",
                                            "experience_index": 3,
                                        },
                                        {
                                            "quote": "Production AWS ownership",
                                            "experience_index": 0,
                                        },
                                    ],
                                }
                            ]
                        }
                    )
                )
            ]
        )
    )
    monkeypatch.setattr(mapping, "run_in_threadpool", provider)
    result = await mapping.generate_map_result(payload, requirements)
    assert payload == original
    assert result["input_hash"] == mapping._input_hash(payload, requirements)
    assert result["items"][0]["evidence"] == [
        {"quote": "Testy AWS tylko szkoleniowo.", "experience_index": None}
    ]
    assert (
        "Testy AWS tylko szkoleniowo."
        in provider.call_args.kwargs["messages"][0]["content"]
    )


async def test_missing_provider_does_not_return_false_completed_map(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    assert await mapping.generate_map_result({"language": "pl"}, []) is None


@pytest.mark.parametrize(
    "index,expected", [(0, 0), (1, None), (True, None), (-1, None)]
)
def test_evidence_cannot_point_to_another_employer(index, expected):
    quote = "Testy AWS tylko szkoleniowo."
    payload = {
        "experience": [
            {"company": "Training", "responsibilities": [quote]},
            {"company": "Employer", "responsibilities": ["Tworzył API w Pythonie."]},
        ]
    }
    result = mapping._sanitize_items(
        {
            "items": [
                {
                    "requirement": "AWS",
                    "status": "partial",
                    "evidence": [{"quote": quote, "experience_index": index}],
                }
            ]
        },
        [{"name": "AWS", "kind": "must"}],
        payload,
    )
    assert result[0]["evidence"] == [{"quote": quote, "experience_index": expected}]


def test_long_quote_is_rejected_whole_without_losing_qualification():
    quote = "Testy AWS " * 25 + "wyłącznie szkoleniowo, bez wdrożeń produkcyjnych."
    result = mapping._sanitize_items(
        {
            "items": [
                {
                    "requirement": "AWS",
                    "status": "met",
                    "note": "Kandydat spełnia wymaganie.",
                    "evidence": [{"quote": quote}],
                }
            ]
        },
        [{"name": "AWS", "kind": "must"}],
        {"why_points": [quote]},
    )
    assert result[0]["evidence"] == []
    assert result[0]["status"] == "no_data"
    assert result[0]["note"] is None


def test_cached_map_rechecks_evidence_without_changing_history():
    cached = {
        "items": [
            {
                "requirement": "AWS",
                "kind": "must",
                "status": "met",
                "note": "Spełnia wymaganie",
                "evidence": [{"quote": "Removed claim"}],
            }
        ]
    }
    original = copy.deepcopy(cached)
    result = mapping.validated_cached_items(
        {"why_points": ["Approved current text"]}, cached
    )
    assert result[0]["status"] == "no_data"
    assert result[0]["evidence"] == []
    assert result[0]["note"] is None
    assert cached == original


async def test_downloaded_html_uses_same_evidence_validation(monkeypatch):
    from app.api import cv_generator_b2b as api
    from app.services.cv_generator_b2b import html_export
    from unittest.mock import Mock

    row = SimpleNamespace(
        status="ready",
        filename="cv.docx",
        render_payload={"language": "pl", "why_points": ["Current text"]},
        requirement_map={
            "items": [
                {
                    "requirement": "AWS",
                    "kind": "must",
                    "status": "met",
                    "evidence": [{"quote": "Removed text"}],
                }
            ]
        },
    )
    monkeypatch.setattr(api, "_load_generated_document", AsyncMock(return_value=row))
    monkeypatch.setattr(api, "_interactive_available", AsyncMock(return_value=True))
    renderer = Mock(return_value="<p>CV</p>")
    monkeypatch.setattr(html_export, "render_interactive_html", renderer)
    response = await api.download_generated_cv_html(7, object(), object())
    assert response.status_code == 200
    assert renderer.call_args.args[1][0]["status"] == "no_data"
    assert renderer.call_args.args[1][0]["evidence"] == []


def test_alternative_labels_get_recruitment_spelling(monkeypatch):
    """FIX-10 (audyt 22.09 r2): grupa LUB z kontraktu („java lub kotlin")
    dostaje pisownię z rekrutacji tak samo jak pojedyncze wymaganie."""
    from app.services import requirement_contract

    monkeypatch.setattr(requirement_contract, "stored_contract", lambda job: None)
    monkeypatch.setattr(requirement_contract, "requirements_for_job", lambda job: [])
    monkeypatch.setattr(
        requirement_contract,
        "requirement_labels",
        lambda reqs: {"must": ["java lub kotlin", "python"], "nice": []},
    )
    job = SimpleNamespace(
        must_skills=["Java", "Kotlin", "Python"],
        nice_skills=[],
        champion_profile=None,
    )
    names = [r["name"] for r in mapping.build_requirements(job)]
    assert names == ["Java lub Kotlin", "Python"]
