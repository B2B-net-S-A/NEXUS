"""Schema-level tests for bulk candidate actions (#3 from Traffit gap roadmap)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.candidates_bulk import (
    BulkAction,
    BulkActionItemResult,
    BulkActionRequest,
    BulkActionResponse,
)


class TestBulkActionEnum:
    def test_known_actions(self):
        assert {a.value for a in BulkAction} == {
            "add_tags",
            "assign_talent_pool",
            "assign_to_job",
            "anonymize_pii",
        }


class TestRequestPayload:
    def test_minimal_add_tags(self):
        req = BulkActionRequest(
            action=BulkAction.add_tags,
            candidate_ids=[1, 2, 3],
            params={"tags": ["senior", "python"]},
        )
        assert req.action is BulkAction.add_tags
        assert req.params["tags"] == ["senior", "python"]

    def test_rejects_empty_id_list(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(action=BulkAction.add_tags, candidate_ids=[], params={})

    def test_caps_at_500(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(
                action=BulkAction.add_tags,
                candidate_ids=list(range(1, 502)),
                params={},
            )

    def test_accepts_exactly_500(self):
        req = BulkActionRequest(
            action=BulkAction.anonymize_pii,
            candidate_ids=list(range(1, 501)),
        )
        assert len(req.candidate_ids) == 500

    def test_unknown_action_rejected(self):
        with pytest.raises(ValidationError):
            BulkActionRequest.model_validate(
                {"action": "delete_everything", "candidate_ids": [1]}
            )

    def test_params_default_empty_dict(self):
        req = BulkActionRequest(action=BulkAction.assign_to_job, candidate_ids=[1])
        assert req.params == {}


class TestResponseShape:
    def test_round_trip(self):
        resp = BulkActionResponse(
            action=BulkAction.add_tags,
            requested=3,
            succeeded=2,
            skipped=1,
            items=[
                BulkActionItemResult(candidate_id=1, ok=True),
                BulkActionItemResult(candidate_id=2, ok=True),
                BulkActionItemResult(candidate_id=99, ok=False, reason="not_found"),
            ],
        )
        assert resp.succeeded == 2
        assert resp.items[2].reason == "not_found"

    def test_item_default_ok(self):
        item = BulkActionItemResult(candidate_id=1, ok=True)
        assert item.reason is None
