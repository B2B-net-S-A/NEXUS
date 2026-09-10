"""A served full-search page writes match impressions — and only that page.

`AI_MATCH_TELEMETRY_ENABLED=true` on production produced ZERO impressions: the
only writer was `matching_orchestrator._emit`, which no live surface calls. The
page GET of the durable full search (`candidate_search_runs.id` = run id) is
the ranking recruiters actually see in C2 and Radar, so that is where the
exposure is recorded. Telemetry must never break the page.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import candidate_search as api
from app.core.config import settings
from app.services import match_telemetry_service as tel
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


def _world(monkeypatch, *, hidden_id: int | None = None):
    """A complete saved-recruitment run with three stored rows (one hidden)."""
    from app.services import pipeline_eligibility
    from app.services.candidate_job_eligibility import (
        EligibilityInput,
        evaluate_eligibility,
    )

    monkeypatch.setattr(api, "_search_access", lambda user: None)
    job = make_job(id=31, client_id=5, must_skills=["Python"])
    context = build_request_context(job, DEFAULT_PROFILE)
    now = datetime.now(timezone.utc)
    candidates = []
    rows = []
    for cid, score in ((11, 88.0), (12, 61.5), (13, 40.0)):
        candidate = make_candidate(id=cid, skills=["Python"])
        candidate.updated_at = now
        candidates.append(candidate)
        rows.append(
            SimpleNamespace(
                candidate_id=cid,
                candidate_version=str(now),
                fit_score=score,
                measurement="measured",
                evidence={
                    "eligibility": None,
                    "breakdown": {
                        "total": score,
                        "semantic": {"points": 30, "max": 60, "reason": "sim 0.5"},
                        "matching_must": ["python"],
                    },
                    "requirements": [],
                },
            )
        )
    run = SimpleNamespace(
        id="run-uuid-1",
        job_id=job.id,
        client_id=job.client_id,
        request_context=context.as_dict(),
        request_fingerprint=context.fingerprint,
        version_trace={**context.versions, "eligibility_fingerprint": "e"},
        state="complete",
        metrics={},
    )
    counts = dict(
        population=3,
        pending=0,
        failed=0,
        evaluated=3,
        eligible=3,
        excluded=0,
        needs_verification=0,
    )
    monkeypatch.setattr(api, "_authorized_job", AsyncMock(return_value=job))
    monkeypatch.setattr(api, "eligibility_fingerprint", AsyncMock(return_value="e"))
    monkeypatch.setattr(api.store, "owned_run", AsyncMock(return_value=run))
    monkeypatch.setattr(api.store, "run_counts", AsyncMock(return_value=counts))
    monkeypatch.setattr(api.store, "population_changed", AsyncMock(return_value=False))
    monkeypatch.setattr(api.store, "result_page", AsyncMock(return_value=(rows, 3)))
    monkeypatch.setattr(
        api, "resolve_active_profile", AsyncMock(return_value=DEFAULT_PROFILE)
    )

    def decision(cid):
        return evaluate_eligibility(
            EligibilityInput(
                candidate_status="blacklisted" if cid == hidden_id else "active"
            ),
            now=now,
        )

    monkeypatch.setattr(
        pipeline_eligibility,
        "evaluate_candidates_for_job",
        AsyncMock(return_value={c.id: decision(c.id) for c in candidates}),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: candidates)
            )
        )
    )
    return run, db


@pytest.mark.asyncio
async def test_page_records_the_served_rows_with_their_rank(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run, db = _world(monkeypatch, hidden_id=12)
    record = AsyncMock(return_value=2)
    monkeypatch.setattr(tel, "record_full_search_page", record)

    result = await api.search_results(
        "run-uuid-1", SimpleNamespace(id=77), offset=40, limit=20, min_score=0, db=db
    )

    served = [r["candidate"]["id"] for r in result["results"]]
    assert served == [11, 13], "the hidden (blacklisted) row is not served"
    record.assert_awaited_once()
    kwargs = record.await_args.kwargs
    assert kwargs["run_id"] == "run-uuid-1"
    assert kwargs["job_id"] == 31 and kwargs["client_id"] == 5
    assert kwargs["user_id"] == 77
    assert kwargs["version_trace"] is run.version_trace
    # A row hidden since the scan means the snapshot no longer matches current
    # eligibility (`data_changed`), so this exposure is flagged as degraded.
    assert kwargs["degraded"] is True
    entries = kwargs["entries"]
    # Exactly the served rows, at their position on the served list.
    assert [(e.candidate_id, e.rank) for e in entries] == [(11, 40), (13, 41)]
    assert [e.fit_score for e in entries] == [88.0, 40.0]
    assert all(e.eligible for e in entries)
    # Numbers only: the salary redaction survives, reasons and skills do not.
    assert entries[0].fit_breakdown == {
        "semantic": {"points": 30.0, "max": 60.0},
        "salary": {"points": None, "max": None},
        "total": 88.0,
        "measurement": "measured",
    }


@pytest.mark.asyncio
async def test_a_telemetry_failure_never_breaks_the_page(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run, db = _world(monkeypatch)
    monkeypatch.setattr(
        tel, "record_full_search_page", AsyncMock(side_effect=RuntimeError("db gone"))
    )

    result = await api.search_results(
        "run-uuid-1", SimpleNamespace(id=77), offset=0, limit=20, min_score=0, db=db
    )

    assert [r["candidate"]["id"] for r in result["results"]] == [11, 12, 13]
    assert result["ranking_complete"] is True


@pytest.mark.asyncio
async def test_clean_complete_page_is_not_degraded(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    run, db = _world(monkeypatch)
    record = AsyncMock(return_value=3)
    monkeypatch.setattr(tel, "record_full_search_page", record)

    await api.search_results(
        "run-uuid-1", SimpleNamespace(id=77), offset=0, limit=20, min_score=0, db=db
    )

    kwargs = record.await_args.kwargs
    assert kwargs["degraded"] is False
    assert [(e.candidate_id, e.rank) for e in kwargs["entries"]] == [
        (11, 0),
        (12, 1),
        (13, 2),
    ]


@pytest.mark.asyncio
async def test_flag_off_writes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", False)
    run, db = _world(monkeypatch)
    record = AsyncMock()
    monkeypatch.setattr(tel, "record_full_search_page", record)

    await api.search_results(
        "run-uuid-1", SimpleNamespace(id=77), offset=0, limit=20, min_score=0, db=db
    )

    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_add_emits_outcomes_only_after_commit_for_added_ids():
    """C2 adds to the pipeline through the bulk route: the outcome must follow
    the commit (it can neither delay nor undo the add) and cover only ids that
    actually entered the pipeline."""
    import ast
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "proposals_bulk.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "bulk_add_proposals"
    )
    calls = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    ]

    def name(call):
        return call.func.id if isinstance(call.func, ast.Name) else call.func.attr

    commit = next(c for c in calls if name(c) == "commit")
    emit = next(c for c in calls if name(c) == "emit_pipeline_additions")
    assert emit.lineno > commit.lineno
    ids = next(kw.value for kw in emit.keywords if kw.arg == "candidate_ids")
    assert isinstance(ids, ast.Name) and ids.id == "added"
