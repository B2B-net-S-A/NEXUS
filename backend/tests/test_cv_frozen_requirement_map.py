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
