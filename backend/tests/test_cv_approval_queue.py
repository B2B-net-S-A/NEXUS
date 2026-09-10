from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.models.cv_generated_draft import CvGeneratedDraft
from app.schemas.candidate_stage_cv import CVBrandedReview
from app.services import cv_approval_queue as queue
from app.services.cv_approval_review import PreparedApprovalReview


@pytest.mark.parametrize("standalone", [True, False])
async def test_enqueue_receipt_reuses_same_attempt_and_rejects_changed_content(
    monkeypatch, standalone
):
    values = dict(
        id=12, edit_revision=3, branded_status="draft", generated_document_id=11
    )
    draft = CvGeneratedDraft(**values) if standalone else SimpleNamespace(**values)
    payload = CVBrandedReview(
        expected_revision=3, content_html="<p>Claim</p>", request_key=uuid4()
    )
    prepared = PreparedApprovalReview(
        "<p>Claim</p>", "Source", "", "", 11, "a" * 64, "review:12:3", "{}"
    )
    prepare = AsyncMock(return_value=prepared)
    monkeypatch.setattr(queue, "prepare_approval_review", prepare)
    db = AsyncMock()
    db.scalar.return_value = None
    db.add = Mock()

    async def flush():
        db.add.call_args.args[0].id = 21

    db.flush.side_effect = flush
    first = await queue.enqueue_review(db, draft, payload, 7)
    assert first == {"review_id": 21, "status": "queued", "error_code": None}
    job = db.add.call_args.args[0]
    assert (job.generated_draft_id == 12) is standalone
    assert (job.candidate_stage_cv_id == 12) is not standalone
    assert job.input_content
    db.scalar.return_value = job
    assert await queue.enqueue_review(db, draft, payload, 7) == first
    prepare.assert_awaited_once()
    db.add.assert_called_once()
    db.commit.assert_not_awaited()
    changed = payload.model_copy(update={"content_html": "<p>Different</p>"})
    with pytest.raises(HTTPException) as error:
        await queue.enqueue_review(db, draft, changed, 7)
    assert error.value.status_code == 409
    prepare.assert_awaited_once()


async def test_unchanged_verified_content_does_not_enqueue(monkeypatch):
    draft = SimpleNamespace(
        id=1, edit_revision=0, branded_status="draft", generated_document_id=11
    )
    monkeypatch.setattr(
        queue, "prepare_approval_review", AsyncMock(return_value={"status": "verified"})
    )
    db = AsyncMock()
    db.scalar.return_value = None
    db.add = Mock()
    result = await queue.enqueue_review(
        db,
        draft,
        CVBrandedReview(
            expected_revision=0, content_html="<p>Claim</p>", request_key=uuid4()
        ),
        7,
    )
    assert result["status"] == "verified"
    assert result["review_id"] is None
    db.add.assert_not_called()


@pytest.mark.parametrize("context", ["generated", "stage"])
@pytest.mark.parametrize("action", ["start", "get", "cancel"])
async def test_review_endpoints_require_resource_write_access(
    monkeypatch, context, action
):
    if context == "generated":
        from app.api import cv_generator_b2b as api

        loader = "_load_generated_editor"
    else:
        from app.api import candidate_stage_cv as api

        loader = "_load_csv_for_stage"
    monkeypatch.setattr(
        api, loader, AsyncMock(side_effect=HTTPException(403, "Denied"))
    )
    enqueue = AsyncMock()
    status = AsyncMock()
    monkeypatch.setattr(queue, "enqueue_review", enqueue)
    monkeypatch.setattr(queue, "review_state", status)
    db = AsyncMock()
    second = (
        CVBrandedReview(
            expected_revision=0, content_html="<p>Claim</p>", request_key=uuid4()
        )
        if action == "start"
        else 22
    )
    with pytest.raises(HTTPException) as error:
        await getattr(api, f"{action}_{context}_cv_review")(
            1, second, SimpleNamespace(id=7), db
        )
    assert error.value.status_code == 403
    enqueue.assert_not_awaited()
    status.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("code", ["55P03", "08006"])
async def test_candidate_lock_failure_cannot_create_review_snapshot(monkeypatch, code):
    from sqlalchemy.exc import DBAPIError

    class DatabaseFailure(RuntimeError):
        sqlstate = code

    failure = DBAPIError("SELECT", {}, DatabaseFailure("test"), False)
    db = AsyncMock()
    db.scalar.return_value = None
    db.execute.side_effect = [None, failure]
    db.add = Mock()
    prepare = AsyncMock()
    monkeypatch.setattr(queue, "prepare_approval_review", prepare)
    draft = SimpleNamespace(
        id=12,
        edit_revision=3,
        branded_status="draft",
        generated_document_id=11,
        candidate_id=5,
    )
    payload = CVBrandedReview(
        expected_revision=3, content_html="<p>Claim</p>", request_key=uuid4()
    )
    with pytest.raises(HTTPException if code == "55P03" else DBAPIError) as error:
        await queue.enqueue_review(db, draft, payload, 7)
    if code == "55P03":
        assert error.value.status_code == 409
    else:
        assert error.value is failure
    prepare.assert_not_awaited()
    db.add.assert_not_called()
