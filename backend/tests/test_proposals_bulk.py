"""Schema-level tests for ``/api/jobs/{id}/proposals/bulk``.

Pure Pydantic / response-shape tests — no DB roundtrip. Integration tests
that exercise the actual SQL path live in tests/test_api_integration.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.proposals_bulk import (
    BulkProposalsRequest,
    BulkProposalsResponse,
    BulkSkippedRow,
)


class TestRequestValidation:
    def test_minimal_request(self):
        req = BulkProposalsRequest(candidate_ids=[1])
        assert req.candidate_ids == [1]
        assert req.note is None
        assert req.tags == []
        assert req.initial_stage_def_id is None

    def test_rejects_empty_candidate_list(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=[])

    def test_caps_at_100_candidates(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=list(range(1, 102)))

    def test_accepts_exactly_100_candidates(self):
        req = BulkProposalsRequest(candidate_ids=list(range(1, 101)))
        assert len(req.candidate_ids) == 100

    def test_caps_tags_at_20(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(
                candidate_ids=[1], tags=[f"tag{i}" for i in range(21)]
            )

    def test_caps_note_at_2000_chars(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=[1], note="x" * 2001)

    def test_accepts_initial_stage_override(self):
        req = BulkProposalsRequest(candidate_ids=[1], initial_stage_def_id=42)
        assert req.initial_stage_def_id == 42


class TestResponseShape:
    def test_skip_reason_literals(self):
        # Sanity-check the Literal type — invalid reason should raise.
        with pytest.raises(ValidationError):
            BulkSkippedRow(candidate_id=1, reason="invalid_reason")  # type: ignore[arg-type]

    def test_full_response(self):
        resp = BulkProposalsResponse(
            added=[1, 2, 3],
            skipped=[
                BulkSkippedRow(candidate_id=4, reason="already_in_job"),
                BulkSkippedRow(candidate_id=5, reason="blacklisted"),
            ],
            total_added=3,
            total_skipped=2,
        )
        assert resp.total_added == 3
        assert resp.total_skipped == 2
        assert resp.skipped[0].reason == "already_in_job"
        assert resp.skipped[1].reason == "blacklisted"

    def test_serialization_roundtrip(self):
        resp = BulkProposalsResponse(
            added=[10],
            skipped=[BulkSkippedRow(candidate_id=11, reason="candidate_not_found")],
            total_added=1,
            total_skipped=1,
        )
        data = resp.model_dump()
        assert data["added"] == [10]
        assert data["skipped"][0]["reason"] == "candidate_not_found"
        # Round-trip
        rehydrated = BulkProposalsResponse.model_validate(data)
        assert rehydrated == resp
