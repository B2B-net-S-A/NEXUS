"""Authorized editor review enqueue/status; caller owns the resource transaction."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_approval_job import CvApprovalJob
from app.models.cv_generated_draft import CvGeneratedDraft
from app.services.cv_document_versions import check_revision
from app.services.html_sanitizer import sanitize_cv_html
from app.services.cv_approval_review import prepare_approval_review
from app.services.cv_approval_snapshot import serialize_review, protocol
from app.services.cv_approval_leases import cancel_review


def owner_filter(draft):
    return (
        CvApprovalJob.generated_draft_id == draft.id
        if isinstance(draft, CvGeneratedDraft)
        else CvApprovalJob.candidate_stage_cv_id == draft.id
    )


def state(job, draft):
    stale = (
        job.expected_revision != draft.edit_revision
        or job.generated_document_id != draft.generated_document_id
    )
    return {
        "review_id": job.id,
        "status": "stale" if stale else job.status,
        "error_code": "draft_changed" if stale else job.error_code,
    }


async def enqueue_review(db, draft, payload, user_id):
    check_revision(draft, payload.expected_revision)
    if draft.branded_status != "draft":
        raise HTTPException(409, "CV jest już zatwierdzone.")
    content = sanitize_cv_html(payload.content_html)
    if not content.strip():
        raise HTTPException(422, "CV nie może być puste.")
    request_key = str(payload.request_key)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "owner": "generated"
                if isinstance(draft, CvGeneratedDraft)
                else "stage",
                "id": draft.id,
                "revision": draft.edit_revision,
                "generated_id": draft.generated_document_id,
                "html": content,
                "protocol": protocol(),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    # A receipt shared across resource URLs cannot charge a second review or
    # overwrite a first attempt after an uncertain response.
    lock = int.from_bytes(
        hashlib.sha256(f"cv-review:{user_id}:{request_key}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    await db.execute(select(func.pg_advisory_xact_lock(lock)))
    existing = await db.scalar(
        select(CvApprovalJob).where(
            CvApprovalJob.user_id == user_id, CvApprovalJob.request_key == request_key
        )
    )
    if existing is not None:
        if existing.request_sha256 != fingerprint:
            raise HTTPException(409, "Identyfikator kontroli dotyczy innej treści CV.")
        return state(existing, draft)
    # Erasure holds the candidate before checking/removing source jobs. Do not
    # enqueue a new private snapshot after that check or wait in reverse order
    # while the editor holds its document lock.
    try:
        await db.execute(
            select(Candidate.id)
            .where(
                (
                    Candidate.id
                    == select(CvGeneratedDocument.candidate_id)
                    .where(CvGeneratedDocument.id == draft.generated_document_id)
                    .scalar_subquery()
                )
                | (Candidate.id == getattr(draft, "candidate_id", None))
            )
            .with_for_update(nowait=True)
        )
    except DBAPIError as exc:
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code != "55P03":
            raise
        raise HTTPException(
            409, "Dane kandydata są aktualizowane. Ponów kontrolę za chwilę."
        ) from exc
    prepared = await prepare_approval_review(db, draft, content)
    if isinstance(prepared, dict):
        return {"review_id": None, "status": "verified", "error_code": None}
    raw, digest = serialize_review(prepared)
    job = CvApprovalJob(
        user_id=user_id,
        generated_draft_id=draft.id if isinstance(draft, CvGeneratedDraft) else None,
        candidate_stage_cv_id=None if isinstance(draft, CvGeneratedDraft) else draft.id,
        generated_document_id=draft.generated_document_id,
        expected_revision=draft.edit_revision,
        request_key=request_key,
        request_sha256=fingerprint,
        input_content=raw,
        input_sha256=digest,
        status="queued",
    )
    db.add(job)
    await db.flush()
    return state(job, draft)


async def review_state(db, draft, review_id, user_id, *, cancel=False):
    job = await db.scalar(
        select(CvApprovalJob).where(
            CvApprovalJob.id == review_id,
            CvApprovalJob.user_id == user_id,
            owner_filter(draft),
        )
    )
    if job is None:
        raise HTTPException(404, "Nie znaleziono kontroli tego CV.")
    if cancel:
        await cancel_review(db, review_id)
        await db.refresh(job)
    return state(job, draft)
