"""Fixed protocol diagnostics expose no candidate/model response text."""

import json

import pytest

from app.services.cv_generator_b2b import factual_verification as gate


@pytest.mark.parametrize(
    "response, reason",
    [
        ("Private source content", "invalid_json"),
        (json.dumps({"claims": [{"path": "/name"}]}), "invalid_schema"),
        (json.dumps({"claims": []}), "invalid_coverage"),
        (
            json.dumps(
                {
                    "claims": [
                        {"path": "/other", "status": "unsupported", "evidence": []}
                    ]
                }
            ),
            "invalid_coverage",
        ),
        (
            json.dumps(
                {
                    "claims": [
                        {"path": "/name", "status": "unsupported", "evidence": []}
                    ]
                    * 2
                }
            ),
            "invalid_coverage",
        ),
    ],
)
def test_invalid_response_reports_only_fixed_failure_kind(
    monkeypatch, response, reason
):
    monkeypatch.setattr(gate, "analyze_with_ai", lambda *a, **kw: response)
    with pytest.raises(gate.FactualVerificationError) as error:
        gate.verify_final_cv(
            {"name": "Synthetic Candidate"},
            cv_text="Synthetic Candidate",
            screening_notes="",
            identity="Synthetic Candidate",
            request_id="protocol-test",
        )
    assert error.value.reason == reason
    assert error.value.paths == []
    assert str(error.value) == "CV source verification did not pass"
