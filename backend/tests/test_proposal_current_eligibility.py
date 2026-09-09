from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import proposals
from app.models.candidate import Candidate
from app.services.candidate_job_eligibility import (
    EligibilityInput,
    evaluate_eligibility,
)


@pytest.mark.asyncio
async def test_snapshot_read_rechecks_added_removed_and_hidden_blocks(monkeypatch):
    now = datetime.now(timezone.utc)
    snap = SimpleNamespace(
        breakdowns=[
            {"candidate_id": i, "total": 75, "eligibility": {"reason": "old"}}
            for i in [1, 2, 3, 4]
        ]
    )
    candidates = {
        i: Candidate(id=i, name="Test", lastname="Candidate") for i in [1, 2, 3, 4]
    }
    monkeypatch.setattr(
        proposals, "_load_snapshot_candidates", AsyncMock(return_value=candidates)
    )
    clean = evaluate_eligibility(EligibilityInput(candidate_status="active"), now=now)
    blocked = evaluate_eligibility(
        EligibilityInput(candidate_status="active", rejected_by_hiring_manager=True),
        now=now,
    )
    hidden = evaluate_eligibility(
        EligibilityInput(candidate_status="blacklisted"), now=now
    )
    gate = AsyncMock(
        side_effect=[
            {1: blocked, 2: hidden, 3: clean},
            {1: clean, 2: hidden, 3: blocked},
        ]
    )
    monkeypatch.setattr(
        "app.services.pipeline_eligibility.evaluate_candidates_for_job", gate
    )
    first = await proposals._hydrate_current_items(None, SimpleNamespace(id=7), snap)
    assert [item.candidate.id for item in first] == [1, 3]
    assert first[0].eligibility["assignment_allowed"] is False
    assert first[1].eligibility is None
    second = await proposals._hydrate_current_items(None, SimpleNamespace(id=7), snap)
    assert second[0].eligibility is None
    assert second[1].eligibility["assignment_allowed"] is False
    assert second[1].breakdown["eligibility"] == second[1].eligibility
    assert snap.breakdowns[0]["eligibility"] == {"reason": "old"}


@pytest.mark.asyncio
async def test_snapshot_read_does_not_swallow_eligibility_failure(monkeypatch):
    monkeypatch.setattr(
        proposals,
        "_load_snapshot_candidates",
        AsyncMock(return_value={1: Candidate(id=1)}),
    )
    monkeypatch.setattr(
        "app.services.pipeline_eligibility.evaluate_candidates_for_job",
        AsyncMock(side_effect=RuntimeError("gate failed")),
    )
    with pytest.raises(RuntimeError, match="gate failed"):
        await proposals._hydrate_current_items(
            None, SimpleNamespace(id=7), SimpleNamespace()
        )
