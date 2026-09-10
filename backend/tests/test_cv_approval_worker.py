import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from app.services import cv_approval_worker as worker
from app.services.cv_approval_review import PreparedApprovalReview
from app.services.cv_approval_snapshot import serialize_review


@pytest.mark.parametrize(
    "outcome", ["verified", "rejected", "unavailable", "stale", "inactive"]
)
async def test_worker_uses_committed_snapshot_and_does_not_approve_draft(
    monkeypatch, outcome
):
    prepared = PreparedApprovalReview(
        "<p>Claim</p>", "Source", "Notes", "Person", 11, "a" * 64, "review:1:2", "{}"
    )
    raw, digest = serialize_review(prepared)
    job = SimpleNamespace(
        status="running",
        lease_token="owner",
        input_content=raw,
        input_sha256=digest,
        generated_draft_id=12,
        candidate_stage_cv_id=None,
        expected_revision=2,
        generated_document_id=11,
        user_id=7,
    )
    draft = SimpleNamespace(
        edit_revision=3 if outcome == "stale" else 2,
        branded_status="draft",
        generated_document_id=11,
    )
    db = AsyncMock()

    async def get(model, object_id):
        if model is worker.CvApprovalJob:
            return job
        if model is worker.CvGeneratedDraft:
            return draft
        return SimpleNamespace(id=7, is_active=outcome != "inactive")

    db.get.side_effect = get

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(worker.leases, "claim_review", AsyncMock(return_value="owner"))
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr(worker.leases, "finish_review", finish)

    async def renew(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "renew", renew)

    async def verify(db, captured, user_id):
        db.commit.assert_awaited_once()
        assert captured == prepared
        assert user_id == 7
        if outcome == "rejected":
            raise HTTPException(422, "unsupported")
        if outcome == "unavailable":
            raise HTTPException(503, "provider")
        return {"status": "verified"}

    verification = AsyncMock(side_effect=verify)
    monkeypatch.setattr(worker, "execute_approval_review", verification)
    await worker.execute_review_job(1)
    assert draft.branded_status == "draft"
    assert draft.edit_revision == (3 if outcome == "stale" else 2)
    assert finish.await_count == 1
    assert (
        finish.call_args.kwargs["status"]
        == {
            "verified": "verified",
            "rejected": "rejected",
            "unavailable": "failed",
            "stale": "failed",
            "inactive": "failed",
        }[outcome]
    )
    if outcome in {"stale", "inactive"}:
        verification.assert_not_awaited()
    else:
        verification.assert_awaited_once()


async def test_unclaimed_job_never_reads_private_input(monkeypatch):
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(worker.leases, "claim_review", AsyncMock(return_value=None))
    verification = AsyncMock()
    monkeypatch.setattr(worker, "execute_approval_review", verification)
    await worker.execute_review_job(1)
    db.get.assert_not_awaited()
    verification.assert_not_awaited()
