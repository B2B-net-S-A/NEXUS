from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.services import cv_approval_review as review
from app.services.cv_generator_b2b.factual_verification import FactualVerificationError


async def test_prepared_review_survives_draft_changes_without_reading_them(monkeypatch):
    from dataclasses import FrozenInstanceError, asdict
    import json

    source = SimpleNamespace(
        cv_bytes=b"source",
        cv_filename="cv.docx",
        screening_notes="original notes",
        identity="Original person",
        snapshot_sha256="original-hash",
    )
    monkeypatch.setattr(review, "load_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(
        review, "extract_text_from_file", Mock(return_value="original text")
    )
    quota_calls = []

    @asynccontextmanager
    async def quota(*args, **kwargs):
        quota_calls.append(kwargs["user_id"])
        yield

    monkeypatch.setattr(review, "ai_feature", quota)
    verify = Mock(return_value={"version": 2, "prompt_sha256": "prompt"})
    monkeypatch.setattr(review, "verify_editor_content", verify)
    draft = SimpleNamespace(
        id=5, edit_revision=7, generated_document_id=11, branded_render_metadata={}
    )
    prepared = await review.prepare_approval_review(
        AsyncMock(), draft, "<p>Original claim</p>"
    )
    assert not quota_calls
    verify.assert_not_called()
    with pytest.raises(FrozenInstanceError):
        prepared.content_html = "changed"
    # Durable transport must not require a live ORM object or source file.
    restored = review.PreparedApprovalReview(**json.loads(json.dumps(asdict(prepared))))
    draft.generated_document_id = 99
    draft.edit_revision = 100
    source.screening_notes = "changed notes"
    source.snapshot_sha256 = "changed-hash"
    result = await review.execute_approval_review(AsyncMock(), restored, 17)
    assert quota_calls == [17]
    verify.assert_called_once_with(
        "<p>Original claim</p>",
        cv_text="original text",
        screening_notes="original notes",
        identity="Original person",
        request_id="cv-approval:5:7",
    )
    assert result["generated_document_id"] == 11
    assert result["source_snapshot_sha256"] == "original-hash"


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


async def test_provider_failure_does_not_approve_document(monkeypatch):
    from app.services.cv_generator_b2b.provider import CVGeneratorAIError

    source = SimpleNamespace(
        cv_bytes=b"source",
        cv_filename="source.docx",
        screening_notes="",
        identity="",
        snapshot_sha256="hash",
    )
    monkeypatch.setattr(review, "load_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(
        review, "extract_text_from_file", Mock(return_value="source text")
    )

    @asynccontextmanager
    async def quota(*args, **kwargs):
        yield

    monkeypatch.setattr(review, "ai_feature", quota)
    monkeypatch.setattr(
        review,
        "verify_editor_content",
        Mock(side_effect=CVGeneratorAIError("provider unavailable")),
    )
    csv = SimpleNamespace(
        id=1, edit_revision=3, generated_document_id=11, branded_render_metadata={}
    )
    with pytest.raises(HTTPException) as error:
        await review.review_for_approval(AsyncMock(), csv, "<p>Claim</p>", 7)
    assert error.value.status_code == 503
    assert "Nie zatwierdzono" in error.value.detail


async def test_unchanged_verified_content_does_not_charge_or_reload_sources(
    monkeypatch,
):
    import hashlib
    import json
    from app.services.cv_approval_provenance import capture_editor_origin
    from app.services.cv_generator_b2b.factual_verification import factual_projection

    content = "<p>Python</p>"
    payload = {"why_points": ["Python"]}
    payload["factual_verification"] = {
        "status": "verified",
        "document_sha256": hashlib.sha256(
            json.dumps(
                factual_projection(payload), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest(),
    }
    csv = SimpleNamespace(
        branded_render_metadata=capture_editor_origin(content, payload)
    )
    load = AsyncMock(side_effect=AssertionError("must not reload"))
    quota = Mock(side_effect=AssertionError("must not charge"))
    monkeypatch.setattr(review, "load_review_source", load)
    monkeypatch.setattr(review, "ai_feature", quota)
    result = await review.review_for_approval(AsyncMock(), csv, content, 7)
    assert result["method"] == "unchanged_generation"
    load.assert_not_awaited()
    quota.assert_not_called()


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "html_sha256",
        "source_snapshot_sha256",
        "generated_document_id",
        "verifier_version",
        "editor_review_version",
        "prompt_sha256",
        "response_schema_sha256",
        "status",
        "method",
    ],
)
async def test_only_exact_current_source_review_can_be_reused(monkeypatch, changed):
    import hashlib

    content = "<p>Reviewed statement</p>"
    receipt = {
        "status": "verified",
        "method": "edited_source_review",
        "generated_document_id": 11,
        "html_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "source_snapshot_sha256": "snapshot",
        "verifier_version": review.VERIFIER_VERSION,
        "editor_review_version": review.EDITOR_REVIEW_VERSION,
        "prompt_sha256": hashlib.sha256(
            review.VERIFICATION_PROMPT.encode()
        ).hexdigest(),
        "response_schema_sha256": review.REVIEW_RESPONSE_SCHEMA_SHA256,
    }
    if changed:
        receipt[changed] = "different"
    csv = SimpleNamespace(
        id=1,
        edit_revision=3,
        generated_document_id=11,
        branded_render_metadata={"content_review": receipt},
    )
    monkeypatch.setattr(
        review,
        "load_review_source",
        AsyncMock(
            return_value=SimpleNamespace(
                snapshot_sha256="snapshot",
                cv_bytes=b"source",
                cv_filename="cv.txt",
                screening_notes="",
                identity="",
            )
        ),
    )
    monkeypatch.setattr(
        review, "extract_text_from_file", Mock(return_value="source text")
    )
    quota = Mock(side_effect=RuntimeError("fresh review required"))
    monkeypatch.setattr(review, "ai_feature", quota)
    if changed:
        with pytest.raises(RuntimeError, match="fresh review required"):
            await review.review_for_approval(AsyncMock(), csv, content, 7)
        quota.assert_called_once()
    else:
        result = await review.review_for_approval(AsyncMock(), csv, content, 7)
        assert result["reused"] is True
        assert result["html_sha256"] == receipt["html_sha256"]
        quota.assert_not_called()
        assert "reused" not in receipt


async def test_unreadable_frozen_source_does_not_consume_review_quota(monkeypatch):
    source = SimpleNamespace(
        cv_bytes=b"invalid",
        cv_filename="cv.docx",
        screening_notes="",
        identity="Person",
        snapshot_sha256="hash",
    )
    monkeypatch.setattr(review, "load_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(
        review,
        "extract_text_from_file",
        Mock(side_effect=review.CVTextExtractionError("unreadable")),
    )
    admission = Mock(side_effect=AssertionError("Must not charge unreadable source"))
    verification = Mock()
    monkeypatch.setattr(review, "ai_feature", admission)
    monkeypatch.setattr(review, "verify_editor_content", verification)
    draft = SimpleNamespace(
        id=1,
        edit_revision=3,
        generated_document_id=11,
        branded_render_metadata={},
    )
    with pytest.raises(HTTPException) as error:
        await review.review_for_approval(AsyncMock(), draft, "<p>Changed claim</p>", 7)
    assert error.value.status_code == 422
    admission.assert_not_called()
    verification.assert_not_called()


@pytest.mark.parametrize("generated_id", [None, 11])
async def test_missing_source_returns_recovery_code_without_charging(
    monkeypatch, generated_id
):
    monkeypatch.setattr(
        review,
        "load_review_source",
        AsyncMock(side_effect=review.ReviewSourceMissing("Wygeneruj CV ponownie.")),
    )
    admission = Mock()
    monkeypatch.setattr(review, "ai_feature", admission)
    draft = SimpleNamespace(
        generated_document_id=generated_id, branded_render_metadata={}
    )
    with pytest.raises(HTTPException) as error:
        await review.review_for_approval(AsyncMock(), draft, "<p>Changed claim</p>", 7)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "cv_source_regeneration_required"
    assert error.value.detail["message"]
    admission.assert_not_called()
