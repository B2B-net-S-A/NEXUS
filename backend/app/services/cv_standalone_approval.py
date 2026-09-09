"""Approve the exact verified generation without inventing a recruitment stage."""

import hashlib
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.cv_document_version import CvDocumentVersion
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_generator_b2b.public_view import build_public_payload
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.html_sanitizer import sanitize_cv_html


async def approve_unchanged_generation(db, generated, user_id):
    """Caller holds the authorized generation row lock; retries reuse approval."""
    if generated.status != "ready" or not generated.render_payload:
        raise HTTPException(409, "CV nie jest gotowe do zatwierdzenia.")
    if (
        not generated.docx_content
        or hashlib.sha256(generated.docx_content).hexdigest() != generated.docx_sha256
    ):
        raise HTTPException(
            409, "Brak poprawnego zapisanego dokumentu. Wygeneruj CV ponownie."
        )
    public = build_public_payload(generated.render_payload)
    html = sanitize_cv_html(render_interactive_html(public, [], document_only=True))
    metadata = capture_editor_origin(html, generated.render_payload)
    if not metadata["generation_review_available"]:
        raise HTTPException(
            409,
            "Brak potwierdzonej kontroli treści tej generacji. Wygeneruj CV ponownie.",
        )
    existing = await db.scalar(
        select(CvDocumentVersion).where(
            CvDocumentVersion.generated_owner_id == generated.id,
            CvDocumentVersion.version == 1,
        )
    )
    if existing is not None:
        return existing
    from app.models.cv_generated_draft import CvGeneratedDraft

    if await db.scalar(
        select(CvGeneratedDraft.id).where(
            CvGeneratedDraft.generated_document_id == generated.id
        )
    ):
        raise HTTPException(
            409, "To CV ma zapisany szkic. Zatwierdź jego treść w edytorze."
        )
    version = CvDocumentVersion(
        generated_owner_id=generated.id,
        generated_document_id=generated.id,
        candidate_stage_cv_id=None,
        version=1,
        content_html=html,
        content_sha256=hashlib.sha256(html.encode()).hexdigest(),
        docx_content=generated.docx_content,
        docx_sha256=generated.docx_sha256,
        docx_filename=generated.filename,
        render_metadata={
            **metadata,
            "editorial_provenance": generated.render_payload.get(
                "editorial_provenance"
            ),
            "artifact_provenance": generated.render_payload.get("artifact_provenance"),
        },
        language=public["language"],
        candidate_first_name=public["candidate_name"],
        job_title=public["position"],
        template="blind" if public["blind"] else "standard",
        approved_at=datetime.now(timezone.utc),
        approved_by=user_id,
    )
    db.add(version)
    await db.flush()
    return version
