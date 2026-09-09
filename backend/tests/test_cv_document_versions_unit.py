from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from app.api import candidate_stage_cv as api
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_document_versions import freeze_approved_version
from app.schemas.candidate_stage_cv import (
    CVBrandedFinalize,
    CVBrandedNewDraft,
    CVBrandedUpdate,
)


def context(monkeypatch, status="draft"):
    csv = CandidateStageCV(
        id=1,
        candidate_stage_id=2,
        candidate_id=3,
        job_id=4,
        branded_status=status,
        branded_draft_html="<p>old</p>",
        edit_revision=5,
        branded_version=1,
        branded_language="pl",
        branded_template="standard",
        branded_finalized_at=datetime.now(timezone.utc)
        if status == "finalized"
        else None,
    )
    db = AsyncMock()

    def add(item):
        if isinstance(item, CvDocumentVersion):
            item.id = 10

    db.add = Mock(side_effect=add)
    db.scalar.return_value = None
    db.get.return_value = None
    loader = AsyncMock(return_value=csv)
    monkeypatch.setattr(api, "_load_csv_for_stage", loader)
    blobs = []

    def save(**kwargs):
        blob = kwargs["source"].read()
        blobs.append(blob)
        return "synthetic/version.html", len(blob)

    monkeypatch.setattr(api.storage_service, "save_branded_cv", save)
    return csv, db, SimpleNamespace(id=9), blobs, loader


async def test_finalization_saves_submitted_content_and_freezes_it(monkeypatch):
    csv, db, user, blobs, loader = context(monkeypatch)
    result = await api.finalize_branded_cv(
        2,
        CVBrandedFinalize(expected_revision=5, content_html="<p>just typed</p>"),
        user,
        db,
    )
    assert result.edit_revision == 6 and result.document_version_id == 10
    assert b"just typed" in blobs[0] and b">old<" not in blobs[0]
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    csv.branded_draft_html = "changed later"
    assert version.content_html == "<p>just typed</p>"
    loader.assert_awaited_once_with(db, 2, user, lock=True)


@pytest.mark.parametrize("expected", [0, 4, 6])
async def test_stale_finalize_rejected_before_snapshot(monkeypatch, expected):
    csv, db, user, blobs, _ = context(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await api.finalize_branded_cv(
            2,
            CVBrandedFinalize(expected_revision=expected, content_html="<p>new</p>"),
            user,
            db,
        )
    assert error.value.status_code == 409
    assert csv.branded_draft_html == "<p>old</p>" and blobs == []
    db.commit.assert_not_awaited()


async def test_new_draft_archives_legacy_version_before_clearing_status(monkeypatch):
    csv, db, user, _, loader = context(monkeypatch, "finalized")
    response = await api.new_branded_cv_draft(
        2, CVBrandedNewDraft(expected_revision=5), user, db
    )
    assert (
        response.version == 2
        and response.edit_revision == 6
        and response.status == "draft"
    )
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    assert version.version == 1 and version.content_html == "<p>old</p>"
    # Only unpinned tokens for this stage are attached to that frozen version.
    statement = db.execute.call_args.args[0]
    assert "document_version_id IS NULL" in str(statement)
    assert statement.compile().params["document_version_id"] == 10
    loader.assert_awaited_once_with(db, 2, user, lock=True)


async def test_existing_version_is_never_overwritten(monkeypatch):
    csv, db, _, _, _ = context(monkeypatch, "finalized")
    version = CvDocumentVersion(id=10, content_html="frozen")
    db.scalar.return_value = version
    assert await freeze_approved_version(db, csv) is version
    assert version.content_html == "frozen"
    db.add.assert_not_called()


async def test_save_uses_revision_and_rejects_stale_response(monkeypatch):
    csv, db, user, _, _ = context(monkeypatch)
    result = await api.update_branded_cv(
        2, CVBrandedUpdate(expected_revision=5, content_html="new"), user, db
    )
    assert result.edit_revision == 6
    with pytest.raises(HTTPException) as error:
        await api.update_branded_cv(
            2, CVBrandedUpdate(expected_revision=5, content_html="older"), user, db
        )
    assert error.value.status_code == 409 and csv.branded_draft_html == "new"


def test_legacy_request_without_current_content_or_revision_is_not_accepted():
    with pytest.raises(ValidationError):
        CVBrandedFinalize(expected_revision=5)
    with pytest.raises(ValidationError):
        CVBrandedUpdate(content_html="new")


@pytest.mark.parametrize(
    "candidate_id,job_id,status,code",
    [
        (99, 4, "ready", 404),
        (3, 99, "ready", 404),
        (None, None, "ready", 404),
        (3, 4, "processing", 422),
    ],
)
async def test_selection_rejects_foreign_or_incomplete_document(
    monkeypatch, candidate_id, job_id, status, code
):
    from app.schemas.candidate_stage_cv import CVBrandedSelectGenerated

    csv, db, user, _, _ = context(monkeypatch)
    db.get.return_value = SimpleNamespace(
        id=42,
        candidate_id=candidate_id,
        job_id=job_id,
        status=status,
        render_payload={"why_points": ["selected source"]},
    )
    with pytest.raises(HTTPException) as exc:
        await api.select_generated_cv(
            2,
            CVBrandedSelectGenerated(expected_revision=5, generated_document_id=42),
            user,
            db,
        )
    assert exc.value.status_code == code
    assert csv.branded_draft_html == "<p>old</p>"
    db.commit.assert_not_awaited()


async def test_selection_archives_old_approval_and_uses_exact_generated_content(
    monkeypatch,
):
    from app.schemas.candidate_stage_cv import CVBrandedSelectGenerated

    csv, db, user, _, loader = context(monkeypatch, "finalized")
    csv.generated_document_id = 41
    generated = SimpleNamespace(
        id=42,
        candidate_id=3,
        job_id=4,
        status="ready",
        render_payload={
            "name": "Secret Person",
            "language": "en",
            "blind_cv": True,
            "why_points": ["Selected Python experience"],
            "highlight_keywords": ["Python"],
            "warnings": ["PRIVATE WARNING"],
            "_full_source": "PRIVATE SOURCE",
        },
    )

    async def get(model, key):
        return generated if model is api.CvGeneratedDocument else None

    db.get.side_effect = get
    result = await api.select_generated_cv(
        2,
        CVBrandedSelectGenerated(expected_revision=5, generated_document_id=42),
        user,
        db,
    )
    assert result.generated_document_id == 42 and result.from_generator
    assert (
        result.version == 2 and result.edit_revision == 6 and result.status == "draft"
    )
    assert "Selected <b>Python</b> experience" in result.content_html
    assert all(
        value not in result.content_html
        for value in ("Secret Person", "PRIVATE", "<script", "<button", ">old<")
    )
    assert result.template == "blind" and result.language == "en"
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    assert version.content_html == "<p>old</p>" and version.generated_document_id == 41
    loader.assert_awaited_once_with(db, 2, user, lock=True)
    with pytest.raises(HTTPException) as exc:
        await api.select_generated_cv(
            2,
            CVBrandedSelectGenerated(expected_revision=5, generated_document_id=42),
            user,
            db,
        )
    assert exc.value.status_code == 409


async def test_selected_content_cannot_be_silently_regenerated_from_profile(
    monkeypatch,
):
    csv, db, user, _, _ = context(monkeypatch)
    csv.branded_from_generator = True
    csv.generated_document_id = None  # Even after source deletion.
    with pytest.raises(HTTPException) as exc:
        await api.update_branded_cv(
            2, CVBrandedUpdate(expected_revision=5, language="en"), user, db
        )
    assert exc.value.status_code == 409
    assert csv.branded_draft_html == "<p>old</p>"
    db.commit.assert_not_awaited()
