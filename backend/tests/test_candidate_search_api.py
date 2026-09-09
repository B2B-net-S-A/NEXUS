from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import candidate_search as api
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
async def test_details_require_candidate_read_before_loading_any_results(monkeypatch):
    monkeypatch.setattr(api, "_search_access", lambda user: None)
    guard = AsyncMock(side_effect=HTTPException(403, "Denied"))
    monkeypatch.setattr(api, "require_candidate_read", guard)
    db = SimpleNamespace()
    with pytest.raises(HTTPException) as error:
        await api.search_results(
            "run", SimpleNamespace(id=1), include_candidate_details=True, db=db
        )
    assert error.value.status_code == 403
    guard.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [True, False])
async def test_changed_profile_keeps_snapshot_readable_without_old_positive_evidence(
    monkeypatch,
    changed,
):
    from app.services import pipeline_eligibility

    monkeypatch.setattr(api, "_search_access", lambda user: None)
    job = make_job(must_skills=["Python"])
    job.id = None
    context = build_request_context(job, DEFAULT_PROFILE)
    candidate = make_candidate(skills=["Python"])
    candidate.updated_at = datetime.now(timezone.utc)
    row = SimpleNamespace(
        candidate_id=candidate.id,
        candidate_version=str(candidate.updated_at - timedelta(days=int(changed))),
        fit_score=91,
        measurement="measured",
        evidence={
            "breakdown": {"total": 91, "matching_must": ["python"]},
            "requirements": [
                {
                    "any_of": ["python"],
                    "status": "met",
                    "matched": ["python"],
                    "candidate_evidence": "Private interview detail",
                    "usage_context": "Private project",
                    "verification_id": 9,
                }
            ],
        },
    )
    run = SimpleNamespace(
        id="r",
        job_id=None,
        client_id=job.client_id,
        request_context=context.as_dict(),
        request_fingerprint=context.fingerprint,
        version_trace=context.versions,
        state="complete",
        metrics={"cost_complete": False},
    )
    counts = dict(
        population=1,
        pending=0,
        failed=0,
        evaluated=1,
        eligible=1,
        excluded=0,
        needs_verification=0,
    )
    monkeypatch.setattr(api.store, "owned_run", AsyncMock(return_value=run))
    monkeypatch.setattr(api.store, "run_counts", AsyncMock(return_value=counts))
    monkeypatch.setattr(api.store, "population_changed", AsyncMock(return_value=False))
    monkeypatch.setattr(api.store, "result_page", AsyncMock(return_value=([row], 1)))
    monkeypatch.setattr(
        api, "resolve_active_profile", AsyncMock(return_value=DEFAULT_PROFILE)
    )
    monkeypatch.setattr(
        pipeline_eligibility,
        "evaluate_candidates_for_job",
        AsyncMock(
            return_value={
                candidate.id: SimpleNamespace(
                    visibility="visible", eligible=True, secondary_reasons=[]
                ),
            }
        ),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [candidate]),
            )
        )
    )
    result = await api.search_results(
        "r", SimpleNamespace(id=1), offset=0, limit=20, min_score=0, db=db
    )
    assert result["coverage_complete"]
    item = result["results"][0]
    if changed:
        assert result["data_changed"] and not result["ranking_complete"]
        assert item["fit_score"] is None and item["measurement"] == "stale"
        assert "matching_must" not in item["breakdown"]
        assert item["requirements"][0]["status"] == "unknown"
        assert item["requirements"][0]["matched"] == []
    else:
        assert item["fit_score"] == 91
        assert item["requirements"][0]["status"] == "met"
    for private_key in ("candidate_evidence", "usage_context", "verification_id"):
        assert private_key not in item["requirements"][0]
    assert item["match"] is None
    # Rendering the response must not mutate the persisted historical evidence.
    assert row.evidence["requirements"][0]["status"] == "met"
