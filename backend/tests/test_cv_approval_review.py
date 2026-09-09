from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.services import cv_approval_review as review
from app.services.cv_generator_b2b.factual_verification import FactualVerificationError


@pytest.mark.parametrize("unsupported", [False, True])
async def test_edited_content_is_reviewed_against_frozen_source(
    monkeypatch, unsupported
):
    source = SimpleNamespace(
        cv_bytes=b"original",
        cv_filename="cv.docx",
        screening_notes="confirmed notes",
        identity="Person",
        snapshot_sha256="hash",
    )
    monkeypatch.setattr(review, "load_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(
        review, "extract_text_from_file", Mock(return_value="original source text")
    )
    events = []

    @asynccontextmanager
    async def quota(*args, **kwargs):
        events.append("admitted")
        yield

    monkeypatch.setattr(review, "ai_feature", quota)

    def verify(content, **kwargs):
        assert events == ["admitted"]
        assert content == "<p>Changed claim</p>"
        assert kwargs["cv_text"] == "original source text"
        assert kwargs["screening_notes"] == "confirmed notes"
        if unsupported:
            raise FactualVerificationError(reason="semantic_rejection")
        return {"version": 2, "prompt_sha256": "prompt"}

    monkeypatch.setattr(review, "verify_editor_content", verify)
    csv = SimpleNamespace(
        id=1, edit_revision=3, generated_document_id=11, branded_render_metadata={}
    )
    if unsupported:
        with pytest.raises(HTTPException) as error:
            await review.review_for_approval(
                AsyncMock(), csv, "<p>Changed claim</p>", 7
            )
        assert error.value.status_code == 422
    else:
        result = await review.review_for_approval(
            AsyncMock(), csv, "<p>Changed claim</p>", 7
        )
        assert result["method"] == "edited_source_review"
        assert result["source_snapshot_sha256"] == "hash"


async def test_rejected_review_prevents_finalized_version_and_snapshot(monkeypatch):
    from tests.test_cv_document_versions_unit import context
    from app.api import candidate_stage_cv as api
    from app.schemas.candidate_stage_cv import CVBrandedFinalize

    csv, db, user, blobs, _ = context(monkeypatch)
    guard = AsyncMock(side_effect=HTTPException(422, "Unsupported facts"))
    monkeypatch.setattr(review, "review_for_approval", guard)
    with pytest.raises(HTTPException):
        await api.finalize_branded_cv(
            2,
            CVBrandedFinalize(
                expected_revision=5, content_html="<p>Invented claim</p>"
            ),
            user,
            db,
        )
    assert csv.branded_status == "draft"
    assert not blobs
    db.commit.assert_not_awaited()
    guard.assert_awaited_once_with(db, csv, "<p>Invented claim</p>", user.id)
