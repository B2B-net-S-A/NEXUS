"""Standalone draft lifecycle, using the shared editor renderer and factual gate."""

import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_document_assets import generated_assets, CvAssetsError
from app.services.cv_document_versions import check_revision
from app.services.cv_approval_provenance import (
    capture_editor_origin,
    approval_provenance,
)
from app.services.cv_approval_review import review_for_approval
from app.services.cv_approved_docx import (
    render_approved_docx,
    ApprovedDocxError,
    RENDERER_VERSION,
)
from app.services.cv_generator_b2b.public_view import build_public_payload
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.html_sanitizer import sanitize_cv_html


async def load_draft(db, generated):
    """Caller locks and authorizes the parent generation for every mutation."""
    draft = await db.scalar(
        select(CvGeneratedDraft)
        .where(CvGeneratedDraft.generated_document_id == generated.id)
        .with_for_update()
    )
    if draft is not None:
        return draft
    if generated.status != "ready" or not generated.render_payload:
        raise HTTPException(409, "CV nie jest gotowe do edycji.")
    latest = await db.scalar(
        select(CvDocumentVersion)
        .where(CvDocumentVersion.generated_owner_id == generated.id)
        .order_by(CvDocumentVersion.version.desc())
        .limit(1)
    )
    public = build_public_payload(generated.render_payload)
    try:
        if latest is not None:
            from app.services.cv_document_assets import approved_assets

            template, consent, metadata = approved_assets(latest)
            html = latest.content_html
            public["language"] = latest.language or public["language"]
            public["blind"] = latest.template == "blind"
        else:
            template, consent, metadata = await run_in_threadpool(
                generated_assets, generated
            )
            html = sanitize_cv_html(
                render_interactive_html(public, [], document_only=True)
            )
            metadata.update(capture_editor_origin(html, generated.render_payload))
    except CvAssetsError as exc:
        raise HTTPException(422, str(exc)) from exc
    draft = CvGeneratedDraft(
        generated_document_id=generated.id,
        edit_revision=0,
        branded_version=latest.version if latest else 1,
        branded_status="finalized" if latest else "draft",
        branded_draft_html=latest.content_html if latest else html,
        branded_template_content=template,
        branded_consent_content=consent,
        branded_render_metadata=metadata,
        branded_language=public["language"],
        branded_template="blind" if public["blind"] else "standard",
        branded_docx_filename=generated.filename,
    )
    db.add(draft)
    await db.flush()
    return draft


def state(draft):
    from app.services.cv_editor_rules import editor_rule_feedback

    return {
        "presentation_review": editor_rule_feedback(
            draft.branded_draft_html, draft.branded_render_metadata
        ),
        "docx_available": draft.branded_status == "finalized",
        "docx_filename": draft.branded_docx_filename,
        "updated_at": None,
        "updated_by": None,
        "updated_by_name": None,
        "finalized_at": None,
        "finalized_by": None,
        "finalized_by_name": None,
        "snapshot_filename": draft.branded_docx_filename
        if draft.branded_status == "finalized"
        else None,
        "rendered_from_default": False,
        "generated_document_id": draft.generated_document_id,
        "candidate_stage_id": None,
        "from_generator": True,
        "edit_revision": draft.edit_revision,
        "version": draft.branded_version,
        "status": draft.branded_status,
        "content_html": draft.branded_draft_html,
        "template": draft.branded_template,
        "language": draft.branded_language,
    }


def save(draft, expected_revision, html):
    check_revision(draft, expected_revision)
    if draft.branded_status != "draft":
        raise HTTPException(409, "Utwórz nowy szkic przed edycją zatwierdzonego CV.")
    cleaned = sanitize_cv_html(html)
    if not cleaned.strip():
        raise HTTPException(422, "CV nie może być puste.")
    draft.branded_draft_html = cleaned
    draft.edit_revision += 1


def new_draft(draft, expected_revision):
    check_revision(draft, expected_revision)
    if draft.branded_status != "finalized":
        raise HTTPException(409, "Bieżące CV jest już szkicem.")
    draft.branded_status = "draft"
    draft.branded_version += 1
    draft.edit_revision += 1


async def render(draft, html):
    try:
        return await run_in_threadpool(
            render_approved_docx,
            sanitize_cv_html(html),
            draft.branded_template_content,
            consent=draft.branded_consent_content,
            language=draft.branded_language,
        )
    except ApprovedDocxError as exc:
        raise HTTPException(422, str(exc)) from exc


async def finalize(db, draft, expected_revision, html, user_id):
    check_revision(draft, expected_revision)
    if draft.branded_status != "draft":
        raise HTTPException(409, "CV jest już zatwierdzone.")
    cleaned = sanitize_cv_html(html)
    if not cleaned.strip():
        raise HTTPException(422, "CV nie może być puste.")
    docx = await render(draft, cleaned)
    review = await review_for_approval(db, draft, cleaned, user_id)
    metadata = {
        **draft.branded_render_metadata,
        **approval_provenance(cleaned, draft.branded_render_metadata),
        "content_review": review,
        "requires_content_review": False,
        "consent_sha256": hashlib.sha256(draft.branded_consent_content).hexdigest()
        if draft.branded_consent_content
        else None,
        "renderer_version": RENDERER_VERSION,
        "template_sha256": hashlib.sha256(draft.branded_template_content).hexdigest(),
    }
    version = CvDocumentVersion(
        generated_owner_id=draft.generated_document_id,
        generated_document_id=draft.generated_document_id,
        version=draft.branded_version,
        content_html=cleaned,
        content_sha256=hashlib.sha256(cleaned.encode()).hexdigest(),
        template_content=draft.branded_template_content,
        consent_content=draft.branded_consent_content,
        docx_content=docx,
        docx_sha256=hashlib.sha256(docx).hexdigest(),
        docx_filename=draft.branded_docx_filename,
        render_metadata=metadata,
        language=draft.branded_language,
        template=draft.branded_template,
        approved_at=datetime.now(timezone.utc),
        approved_by=user_id,
    )
    db.add(version)
    await db.flush()
    draft.branded_draft_html = cleaned
    draft.branded_render_metadata = metadata
    draft.branded_status = "finalized"
    draft.edit_revision += 1
    return version
