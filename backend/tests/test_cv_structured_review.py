"""Provider JSON grammar is explicit; local evidence checks remain mandatory."""

import json
from unittest.mock import Mock

import pytest

from app.services.cv_generator_b2b import factual_verification as review, provider


def test_review_schema_reaches_shared_provider_without_changing_plain_calls(
    monkeypatch,
):
    monkeypatch.setattr(provider, "_api_key", lambda: "unit")
    call = Mock(return_value="{}")
    monkeypatch.setattr(provider, "call_claude_text", call)
    provider.analyze_with_ai(
        "synthetic", "unit", response_schema=review.REVIEW_RESPONSE_SCHEMA
    )
    assert call.call_args.kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": review.REVIEW_RESPONSE_SCHEMA}
    }
    provider.analyze_with_ai("synthetic", "unit")
    assert "output_config" not in call.call_args.kwargs


def test_supported_review_records_schema_fingerprint(monkeypatch):
    response = {
        "claims": [
            {
                "path": "/name",
                "status": "supported",
                "evidence": [{"source": "identity", "quote": "Synthetic Person"}],
            }
        ]
    }
    call = Mock(return_value=json.dumps(response))
    monkeypatch.setattr(review, "analyze_with_ai", call)
    result = review.verify_final_cv(
        {"name": "Synthetic Person"},
        cv_text="",
        screening_notes="",
        identity="Synthetic Person",
        request_id="unit",
    )
    assert call.call_args.kwargs["response_schema"] == review.REVIEW_RESPONSE_SCHEMA
    assert result["response_schema_sha256"] == review.REVIEW_RESPONSE_SCHEMA_SHA256
    assert result["version"] == 2


def test_provider_schema_does_not_replace_local_limits(monkeypatch):
    response = {
        "claims": [{"path": "/name", "status": "unsupported", "evidence": []}] * 41
    }
    monkeypatch.setattr(
        review, "analyze_with_ai", Mock(return_value=json.dumps(response))
    )
    with pytest.raises(review.FactualVerificationError) as error:
        review.verify_final_cv(
            {"name": "Synthetic Person"},
            cv_text="",
            screening_notes="",
            identity="Synthetic Person",
            request_id="unit",
        )
    assert error.value.reason == "invalid_schema"
