"""Recruiter triage for parked public-apply submissions (P0-CAND-01).

When a public ``/apply/{token}`` submission matches an existing candidate by
e-mail, the applicant data is parked as a ``pending_review``
``ApplicationSubmission`` instead of overwriting the candidate. This router
lets a recruiter act on that queue:

* ``GET  /api/application-submissions?status=pending_review`` — list.
* ``POST /api/application-submissions/{id}/resolve`` — one of:
    - ``link``   attach the submission CV as a document to the matched
                 candidate, without overwriting any field;
    - ``merge``  attach the CV and fill only EMPTY contact fields (+ append the
                 applicant message) on the matched candidate;
    - ``create`` create a brand-new candidate from the submission;
    - ``reject`` dismiss the submission, changing no candidate.

Every resolve is audited (``Activity``). This is intentionally a minimal but
functional API — the full frontend review queue is a follow-up.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.candidate_access import CandidateWriteAccess
from app.api.recruitment_access import (
    ensure_optional_job_membership,
    job_read_scope_clause,
)
from app.core.database import get_db
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.services.recruitment_process_commands import open_process

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class ApplicationSubmissionOut(BaseModel):
    id: int
    status: str
    submitted_first_name: str
    submitted_last_name: str
    submitted_email: str
    submitted_phone: Optional[str] = None
    submitted_linkedin: Optional[str] = None
    submitted_message: Optional[str] = None
    matched_candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    cv_filename: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


ResolveAction = Literal["link", "merge", "create", "reject"]


class ResolveRequest(BaseModel):
    action: ResolveAction


class ResolveResponse(BaseModel):
    id: int
    status: str
    candidate_id: Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _load_submission_cv_bytes(
    submission: ApplicationSubmission,
) -> Optional[bytes]:
    """Return the inert CV bytes, whether stored in BYTEA or object storage."""
    if submission.cv_file_content is not None:
        return submission.cv_file_content
    if submission.cv_object_key:
        try:
            import asyncio

            from app.services import object_storage

            if object_storage.is_available():
                return await asyncio.to_thread(
                    object_storage.download_cv, submission.cv_object_key
                )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "[submission] CV fetch failed submission=%s: %s", submission.id, e
            )
    return None


async def _attach_cv_as_document(
    db: AsyncSession,
    candidate_id: int,
    submission: ApplicationSubmission,
    *,
    is_primary: bool = False,
) -> Optional[CandidateDocument]:
    """Attach the submission CV to a candidate as a (non-primary) document.

    Reuses the object-storage key when present (no re-upload); otherwise stores
    the BYTEA fallback. Never touches the candidate's primary CV fields.
    """
    if not submission.cv_filename:
        return None
    file_bytes = await _load_submission_cv_bytes(submission)
    content_hash = hashlib.sha256(file_bytes).hexdigest() if file_bytes else None
    existing = (
        await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.content_sha256 == content_hash,
                CandidateDocument.source_deleted_at.is_(None),
            )
        )
        if content_hash
        else None
    )
    if is_primary:
        await db.execute(
            update(CandidateDocument)
            .where(
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.document_kind == CandidateDocumentKind.cv,
                CandidateDocument.source_deleted_at.is_(None),
            )
            .values(is_primary=False)
        )
    document = existing or CandidateDocument(
        candidate_id=candidate_id,
        filename=submission.cv_filename,
        file_content=file_bytes if not submission.cv_object_key else None,
        storage_key=submission.cv_object_key,
        content_type=submission.cv_content_type,
        size_bytes=submission.cv_size_bytes,
        document_kind=CandidateDocumentKind.cv,
        is_primary=is_primary,
        uploaded_at=datetime.now(timezone.utc),
        external_source="apply_submission",
        content_sha256=content_hash,
    )
    document.document_kind = CandidateDocumentKind.cv
    if is_primary or existing is None:
        document.is_primary = is_primary
    if existing is None:
        db.add(document)
    await db.flush()
    return document


def _origin_assignment_id(
    submission: ApplicationSubmission,
) -> Optional[int]:
    payload = submission.raw_payload if isinstance(submission.raw_payload, dict) else {}
    value = payload.get("origin_assignment_id")
    try:
        assignment_id = int(value)
    except (TypeError, ValueError):
        return None
    return assignment_id if assignment_id > 0 else None


def _priority_compliant_at_create(
    submission: ApplicationSubmission,
) -> Optional[bool]:
    payload = submission.raw_payload if isinstance(submission.raw_payload, dict) else {}
    value = payload.get("priority_compliant_at_create")
    return value if isinstance(value, bool) else None


async def _ensure_submission_process(
    db: AsyncSession,
    *,
    submission: ApplicationSubmission,
    candidate_id: int,
    actor_user_id: int,
) -> Optional[CandidateStage]:
    """Route a resolved job application into the canonical pipeline once."""
    if submission.job_id is None:
        return None
    existing = await db.scalar(
        select(CandidateStage.id).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == submission.job_id,
        )
    )
    if existing is not None:
        return None
    stage = await open_process(
        db,
        candidate_id=candidate_id,
        job_id=submission.job_id,
        stage=PipelineStage.new,
        actor_user_id=actor_user_id,
        origin_kind=PriorityOriginKind.external_inbound,
        frozen_origin_assignment_id=_origin_assignment_id(submission),
        frozen_priority_compliant=_priority_compliant_at_create(submission),
        notes="Rozstrzygnięto aplikację (application submission)",
    )
    return stage


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ApplicationSubmissionOut])
async def list_application_submissions(
    current_user: CandidateWriteAccess,
    status_filter: Optional[str] = Query(
        default=ApplicationSubmissionStatus.pending_review.value,
        alias="status",
        description="Filter by lifecycle status; omit/empty for all.",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ApplicationSubmission]:
    """List parked submissions (default: pending_review). Recruiter+ only.

    Zawężone do ofert wołającego — zgłoszenie niesie dane osobowe kandydata
    (imię, e-mail, telefon, LinkedIn, CV), więc lista nie może być globalna.
    Zgłoszenia bez `job_id` zostają widoczne dla ról operacyjnych.
    """
    stmt = select(ApplicationSubmission).where(
        job_read_scope_clause(current_user, ApplicationSubmission.job_id)
    )
    if status_filter:
        valid = {s.value for s in ApplicationSubmissionStatus}
        if status_filter not in valid:
            raise HTTPException(status_code=422, detail="Unknown status filter")
        stmt = stmt.where(ApplicationSubmission.status == status_filter)
    stmt = (
        stmt.order_by(ApplicationSubmission.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows)


@router.post("/{submission_id}/resolve", response_model=ResolveResponse)
async def resolve_application_submission(
    submission_id: int,
    payload: ResolveRequest,
    background_tasks: BackgroundTasks,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ResolveResponse:
    """Resolve a pending submission: link / merge / create / reject.

    Every action is audited. A submission can only be resolved once — a second
    attempt returns 409.
    """
    # F-03: lock the row for the transaction. Resolve reads the submission and
    # then mutates its status; without SELECT ... FOR UPDATE two concurrent
    # resolves both pass the pending_review check and double-process (double
    # link/merge/create). The lock serialises them so the loser sees the
    # already-resolved status and 409s.
    submission = await db.scalar(
        select(ApplicationSubmission)
        .where(ApplicationSubmission.id == submission_id)
        .options(undefer(ApplicationSubmission.cv_file_content))
        .with_for_update()
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Resource scope: rozstrzygnięcie zgłoszenia zakłada kandydata, scala go z
    # istniejącym albo odrzuca — to działanie NA rekrutacji, nie ogólna operacja
    # rekrutera. Sprawdzenie idzie PRZED bramką `already resolved`, żeby ta
    # gałąź nie zdradzała obcemu użytkownikowi stanu cudzego zgłoszenia.
    # `job_id` jest nullable (zgłoszenie spoza konkretnej oferty) — patrz
    # `ensure_optional_job_membership`.
    await ensure_optional_job_membership(db, current_user, submission.job_id)

    if submission.status != ApplicationSubmissionStatus.pending_review.value:
        raise HTTPException(
            status_code=409,
            detail=f"Submission already resolved (status={submission.status})",
        )

    action = payload.action
    resolved_candidate_id: Optional[int] = None
    primary_document: Optional[CandidateDocument] = None
    opened_stage: Optional[CandidateStage] = None

    if action == "reject":
        submission.status = ApplicationSubmissionStatus.rejected.value

    elif action in ("link", "merge"):
        if submission.matched_candidate_id is None:
            raise HTTPException(
                status_code=409,
                detail="No matched candidate to link/merge into",
            )
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == submission.matched_candidate_id)
        )
        if candidate is None:
            raise HTTPException(
                status_code=409, detail="Matched candidate no longer exists"
            )
        await _attach_cv_as_document(db, candidate.id, submission)
        if action == "merge":
            # Fill ONLY empty fields — never overwrite existing candidate data.
            if not candidate.phone and submission.submitted_phone:
                candidate.phone = submission.submitted_phone
            if not candidate.linkedin and submission.submitted_linkedin:
                candidate.linkedin = submission.submitted_linkedin
            if submission.submitted_message:
                prefix = (
                    candidate.profile_about.strip() + "\n\n"
                    if candidate.profile_about
                    else ""
                )
                stamp = datetime.now(timezone.utc).date().isoformat()
                candidate.profile_about = (
                    f"{prefix}[{stamp}] {submission.submitted_message.strip()}"
                )
            submission.status = ApplicationSubmissionStatus.merged.value
        else:
            submission.status = ApplicationSubmissionStatus.linked.value
        resolved_candidate_id = candidate.id
        opened_stage = await _ensure_submission_process(
            db,
            submission=submission,
            candidate_id=candidate.id,
            actor_user_id=current_user.id,
        )

    elif action == "create":
        # candidates.email is UNIQUE. A submission almost always carries the
        # e-mail of the candidate it MATCHED, so a fresh record can't reuse it.
        # Withhold the colliding e-mail (recruiter reconciles later) rather than
        # 500 on the unique constraint.
        email_val: Optional[str] = submission.submitted_email
        if email_val:
            clash = await db.scalar(
                select(Candidate.id).where(
                    func.lower(Candidate.email) == email_val.strip().lower()
                )
            )
            if clash is not None:
                email_val = None
        candidate = Candidate(
            name=submission.submitted_first_name,
            lastname=submission.submitted_last_name,
            email=email_val,
            phone=submission.submitted_phone,
            linkedin=submission.submitted_linkedin,
            source="apply_submission",
            status=CandidateStatus.active,
            created_by=current_user.id,
            profile_about=submission.submitted_message,
            cv_filename=submission.cv_filename,
            cv_storage_key=submission.cv_object_key,
            cv_file_content=(
                submission.cv_file_content if not submission.cv_object_key else None
            ),
            raw_cv_text=submission.raw_cv_text,
        )
        db.add(candidate)
        await db.flush()
        primary_document = await _attach_cv_as_document(
            db,
            candidate.id,
            submission,
            is_primary=True,
        )
        opened_stage = await _ensure_submission_process(
            db,
            submission=submission,
            candidate_id=candidate.id,
            actor_user_id=current_user.id,
        )
        submission.status = ApplicationSubmissionStatus.created.value
        resolved_candidate_id = candidate.id

    if opened_stage is not None:
        # Keep the per-recruitment CV snapshot in this transaction and make
        # the stage identity guarantee explicit at the endpoint boundary.
        # `open_process` flushes internally, but this flush documents and
        # preserves the invariant relied on by the snapshot FK.
        await db.flush()
        await create_original_cv_snapshot(db, opened_stage)
        # Wspólny blok dla obu gałęzi (link i create) — wcześniej hook kolejki
        # kontaktu wisiał tylko przy tworzeniu kandydata, więc zgłoszenie
        # podpięte pod istniejącego kandydata nie zakładało okazji kontaktu.
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=opened_stage.candidate_id,
            job_id=opened_stage.job_id,
            source="pipeline",
            occurred_at=opened_stage.moved_at,
        )

    submission.reviewed_by = current_user.id
    submission.reviewed_at = datetime.now(timezone.utc)

    # Audit: on the affected candidate when there is one, else on the submission.
    if resolved_candidate_id is not None:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=resolved_candidate_id,
                action="application_submission_resolved",
                user_id=current_user.id,
                details={
                    "submission_id": submission.id,
                    "resolve_action": action,
                    "matched_candidate_id": submission.matched_candidate_id,
                },
            )
        )
    else:
        db.add(
            Activity(
                entity_type="application_submission",
                entity_id=submission.id,
                action="application_submission_resolved",
                user_id=current_user.id,
                details={
                    "resolve_action": action,
                    "matched_candidate_id": submission.matched_candidate_id,
                },
            )
        )

    await db.commit()
    if primary_document is not None:
        from app.api.candidates import _enrich_candidate_from_document_task

        background_tasks.add_task(
            _enrich_candidate_from_document_task,
            resolved_candidate_id,
            primary_document.id,
            primary_document.content_sha256,
        )

    return ResolveResponse(
        id=submission.id,
        status=submission.status,
        candidate_id=resolved_candidate_id,
    )
