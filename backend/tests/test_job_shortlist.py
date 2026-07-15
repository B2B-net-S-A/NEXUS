"""Schema-level tests for the job shortlist (SEARCH-P1-05).

Pure Pydantic — no DB. Integration (add/list/optimistic-lock update/delete)
runs against Postgres in CI via the endpoints in app/api/job_shortlist.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.job_shortlist import (
    ShortlistAddRequest,
    ShortlistAddResponse,
    ShortlistPromoteResponse,
    ShortlistUpdateRequest,
)


class TestAddRequest:
    def test_minimal(self):
        req = ShortlistAddRequest(candidate_ids=[1, 2])
        assert req.candidate_ids == [1, 2]
        assert req.note is None

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            ShortlistAddRequest(candidate_ids=[])

    def test_caps_at_100(self):
        with pytest.raises(ValidationError):
            ShortlistAddRequest(candidate_ids=list(range(1, 102)))

    def test_caps_note(self):
        with pytest.raises(ValidationError):
            ShortlistAddRequest(candidate_ids=[1], note="x" * 2001)


class TestUpdateRequest:
    def test_version_is_required(self):
        with pytest.raises(ValidationError):
            ShortlistUpdateRequest(evaluation_status="zatwierdzony")  # type: ignore[call-arg]

    def test_accepts_valid_statuses(self):
        req = ShortlistUpdateRequest(
            version=3,
            evaluation_status="zatwierdzony",
            outreach_status="kontakt_w_toku",
        )
        assert req.evaluation_status == "zatwierdzony"
        assert req.outreach_status == "kontakt_w_toku"

    def test_rejects_invalid_evaluation_status(self):
        with pytest.raises(ValidationError):
            ShortlistUpdateRequest(version=1, evaluation_status="maybe")  # type: ignore[arg-type]

    def test_rejects_invalid_outreach_status(self):
        with pytest.raises(ValidationError):
            ShortlistUpdateRequest(version=1, outreach_status="ghosted")  # type: ignore[arg-type]

    def test_partial_update_only_dumps_set_fields(self):
        # The endpoint relies on exclude_unset to apply ONLY provided fields.
        req = ShortlistUpdateRequest(version=2, evaluation_status="potencjalny")
        changes = req.model_dump(exclude_unset=True, exclude={"version"})
        assert changes == {"evaluation_status": "potencjalny"}


class TestAddResponse:
    def test_shape(self):
        resp = ShortlistAddResponse(
            added=[1, 2], skipped=[3], total_added=2, total_skipped=1
        )
        assert resp.total_added == 2
        assert resp.skipped == [3]


class TestPromoteResponse:
    def test_defaults(self):
        resp = ShortlistPromoteResponse(
            entry_id=1, candidate_id=2, job_id=3, stage_id=4
        )
        assert resp.already_promoted is False
        assert resp.already_in_pipeline is False

    def test_idempotent_flags(self):
        resp = ShortlistPromoteResponse(
            entry_id=1,
            candidate_id=2,
            job_id=3,
            stage_id=4,
            already_promoted=True,
            already_in_pipeline=True,
        )
        assert resp.already_promoted and resp.already_in_pipeline
