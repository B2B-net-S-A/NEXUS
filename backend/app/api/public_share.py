"""Public (no-auth) endpoints for externally shareable artifacts.

Only routes registered here should be exempt from auth. Each route validates
its own unguessable token and honours `revoked` + `expires_at`. Sensitive
fields (emails of internal users, private labels, internal ids) are never
exposed on these endpoints.
"""

import asyncio
import logging
import os
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

import aiofiles
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.champion_share import ChampionCardShareToken
from app.models.cv_share_token import CVShareToken
from app.services.html_sanitizer import sanitize_cv_html
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.services.recruitment_process_commands import open_process
from app.models.user import User
from app.models.user_activity import UserActionType, UserActivity

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Champion Card share (legacy Phase 12) ──────────────────────────────────


@router.get("/champion-card/{token}")
async def get_public_champion_card(
    token: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Client-facing read of a filled Champion card.

    Returns 404 when the token is unknown, revoked, or expired. The response
    shape is slimmed down — no internal fields (scores, stage ids) — so that
    the client only sees what the recruiter meant to share.
    """
    # Dual-read (same pattern as CVShareToken): v2 rows match the SHA-256 digest
    # of the incoming secret; legacy rows kept the raw secret in the PK and are
    # matched directly, scoped to token_sha256 IS NULL so they age out on expiry.
    import hashlib

    digest = hashlib.sha256(token.encode()).hexdigest()
    row: Optional[ChampionCardShareToken] = await db.scalar(
        select(ChampionCardShareToken).where(
            (ChampionCardShareToken.token_sha256 == digest)
            | (
                (ChampionCardShareToken.token == token)
                & (ChampionCardShareToken.token_sha256.is_(None))
            )
        )
    )
    if row is None or row.revoked:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Share link expired")

    stage = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == row.candidate_stage_id)
    )
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage disappeared")
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == stage.candidate_id)
    )
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))

    return {
        "candidate": {
            "name": candidate.name if candidate else None,
            "lastname": candidate.lastname if candidate else None,
            "competence_category": candidate.competence_category if candidate else None,
            "location": candidate.location if candidate else None,
            "years_it_experience": candidate.years_it_experience if candidate else None,
        },
        "job": {
            "title": job.title if job else None,
            "location": job.location if job else None,
            "seniority": job.seniority.value if job and job.seniority else None,
        },
        "champion_profile": (job.champion_profile if job else None) or {},
        "screening_answers": stage.screening_answers or None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


# ── CV per rekrutacja — public share (Faza 4) ──────────────────────────────


@router.get("/cv/{token}")
@limiter.limit("30/minute")
async def get_public_cv(
    token: str,
    request: Request,  # required by slowapi limiter
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Klient otwiera token-link i widzi brandowane CV — bez logowania.

    PII safety: response NIE zawiera email, phone, lastname kandydata. Tylko
    `candidate_first_name` + `job_title` + `cv_html` + `expires_at`.
    Test `test_public_cv_no_pii_leakage` jako safety net.

    Walidacja:
    * 404 gdy token nie istnieje lub został odwołany
    * 410 gdy token wygasł
    * 404 gdy CV przestało być finalized (np. recruiter zresetował)
    """
    # M4 PR-04 (audyt P1.9, token v2): dual-read — legacy wiersze trzymają raw
    # token w PK, v2 wyłącznie SHA-256. Prezentowany sekret dopasowujemy do
    # obu form.
    # PR1b (re-audyt M2): legacy-branch MUSI być zawężony do wierszy legacy
    # (``token_sha256 IS NULL``). Bez tego nie-sekretny ``revoke_key`` v2
    # (``v2$<hex>``, PK wiersza, trafia m.in. do Activity audit log) działał
    # jako pełnoprawny token dostępu — co znosiło gwarancję P1.9 „sekret nigdy
    # nie jest przechowywany". Klucz do odwoływania linku nie może być
    # jednocześnie kluczem dostępu do CV.
    digest = hashlib.sha256(token.encode()).hexdigest()
    row: Optional[CVShareToken] = await db.scalar(
        select(CVShareToken).where(
            (CVShareToken.token_sha256 == digest)
            | ((CVShareToken.token == token) & (CVShareToken.token_sha256.is_(None)))
        )
    )
    if row is None or row.revoked:
        raise HTTPException(
            status_code=404, detail="Link nie istnieje lub został odwołany."
        )
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link wygasł.")

    # Limit wyświetleń — atomowy UPDATE (bez race dwóch równoległych GET-ów):
    # inkrementacja przechodzi tylko, gdy licznik wciąż mieści się w limicie.
    claimed = (
        await db.execute(
            update(CVShareToken)
            .where(
                CVShareToken.token == row.token,
                (CVShareToken.max_views.is_(None))
                | (CVShareToken.view_count < CVShareToken.max_views),
            )
            .values(
                view_count=CVShareToken.view_count + 1,
                last_viewed_at=datetime.now(timezone.utc),
            )
            .returning(CVShareToken.view_count)
        )
    ).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(
            status_code=410, detail="Limit wyświetleń linku został wyczerpany."
        )

    csv: Optional[CandidateStageCV] = await db.scalar(
        select(CandidateStageCV).where(CandidateStageCV.id == row.candidate_stage_cv_id)
    )
    if csv is None or csv.branded_status != "finalized":
        raise HTTPException(
            status_code=404,
            detail="CV nie jest już dostępne (zostało zresetowane).",
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == csv.candidate_id)
    )
    job = await db.scalar(select(Job).where(Job.id == csv.job_id))

    # Access audit (bez PII): kto NIE jest znany (public), ale wiemy który
    # link, które CV i którym wyświetleniem to było.
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv.id,
            action="cv_share_viewed",
            user_id=None,
            # Never write the raw token here: for legacy rows row.token IS the
            # secret, so this used to copy a live capability secret into the
            # audit trail (widening its DB footprint). The SHA-256 digest is a
            # safe stable reference; legacy rows without one fall back to the id.
            details={
                "revoke_key": row.token_sha256 or f"legacy-cv-share:{csv.id}",
                "view_no": int(claimed),
            },
        )
    )
    await db.commit()

    # Source of truth: zapisany draft HTML (immutable po finalize) —
    # M4 PR-04: na wyjściu przechodzi allowlist sanitizer (stored XSS w
    # publicznym linku dla klienta).
    cv_html = sanitize_cv_html(csv.branded_draft_html)

    # no-store: publiczna treść z PII kandydata nie może lądować w cache'ach
    # pośredników/przeglądarki po odwołaniu linku.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"

    return {
        "candidate_first_name": candidate.name if candidate else None,
        "job_title": job.title if job else None,
        "cv_html": cv_html,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


# ── Candidate invite links (self-service apply) ────────────────────────────

_MAX_CV_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
_ALLOWED_CV_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED_CV_EXT = {".pdf", ".doc", ".docx"}
_PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{6,30}$")


async def _load_valid_link(token: str, db: AsyncSession) -> CandidateInviteLink:
    """Fetch an invite link and raise 404 if missing/revoked/expired.

    Shared by both GET and POST so failure modes stay consistent.
    """
    import hashlib

    # Dual-read: v2 by SHA-256 digest, legacy by raw token (token_sha256 NULL).
    digest = hashlib.sha256(token.encode()).hexdigest()
    link = await db.scalar(
        select(CandidateInviteLink).where(
            (CandidateInviteLink.token_sha256 == digest)
            | (
                (CandidateInviteLink.token == token)
                & (CandidateInviteLink.token_sha256.is_(None))
            )
        )
    )
    if link is None or link.revoked:
        raise HTTPException(status_code=404, detail="Invite link not found or revoked")
    if link.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Invite link expired")
    return link


@router.get("/apply/{token}")
@limiter.limit("30/minute")
async def get_public_apply_meta(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview metadata shown on the public /apply/{token} landing page.

    Exposes only what the candidate needs to decide whether to apply: who
    invited them (first name), which role, and when the link expires.
    Internal state — label, use_count, recruiter email — is never returned.
    """
    link = await _load_valid_link(token, db)

    job = await db.scalar(select(Job).where(Job.id == link.job_id))
    recruiter = await db.scalar(select(User).where(User.id == link.created_by))
    if job is None or recruiter is None:
        raise HTTPException(status_code=404, detail="Invite link no longer valid")

    # Use only the first name of the recruiter for the hero line.
    recruiter_first_name = (recruiter.name or "").strip().split(" ", 1)[0]

    return {
        "recruiter": {"first_name": recruiter_first_name or "Zespół"},
        "job": {
            "title": job.title,
            "location": job.location,
            "seniority": job.seniority.value if job.seniority else None,
            "remote_policy": (job.remote_policy.value if job.remote_policy else None),
        },
        "expires_at": link.expires_at.isoformat(),
    }


def _validate_cv_file(upload: UploadFile, content: bytes) -> None:
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="CV file is empty")
    if len(content) > _MAX_CV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"CV file too large (max {settings.MAX_UPLOAD_SIZE_MB} MB)",
        )
    filename = (upload.filename or "").lower()
    _, ext = os.path.splitext(filename)
    mime_ok = (upload.content_type or "") in _ALLOWED_CV_MIME
    ext_ok = ext in _ALLOWED_CV_EXT
    if not (mime_ok or ext_ok):
        raise HTTPException(
            status_code=415,
            detail="Unsupported CV format. Use PDF, DOC, or DOCX.",
        )


async def _persist_cv(
    candidate_id: int, upload: UploadFile, content: bytes
) -> tuple[str, Optional[str]]:
    """Write the CV bytes to disk and return (stored_filename, extracted_text).

    Mirrors backend/app/api/candidates.py::upload_cv so the rest of the
    product (download, enrichment, embedding) keeps working.
    """
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = upload.filename or "cv.pdf"
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{filename}"
    )
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    raw_text: Optional[str] = None
    try:
        from app.services import cv_text_extractor

        raw_text = await asyncio.to_thread(
            cv_text_extractor.extract_text, file_path, filename
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[apply] CV text extraction failed candidate=%s: %s", candidate_id, e
        )
    return filename, raw_text


async def _persist_submission_cv(
    upload: UploadFile, content: bytes
) -> tuple[Optional[str], Optional[bytes], Optional[str]]:
    """Store an applicant CV INERT — attached to no candidate.

    Returns ``(object_key, file_bytes, raw_text)``. When object storage is
    configured the bytes are uploaded there and ``file_bytes`` is None; in
    dev/CI (no object storage) the bytes come back to be stored in the BYTEA
    fallback column. ``raw_text`` is a best-effort text extraction kept for the
    later resolve step. Nothing here writes to a candidate or the shared CV
    upload dir — the CV stays inert until a recruiter resolves the submission.
    """
    filename = upload.filename or "cv.pdf"
    object_key: Optional[str] = None
    file_bytes: Optional[bytes] = content
    try:
        from app.services import object_storage

        if object_storage.is_available():
            object_key = await asyncio.to_thread(
                object_storage.upload_cv, content, filename, upload.content_type
            )
            file_bytes = None
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] inert CV object-store upload failed: %s", e)
        object_key = None
        file_bytes = content

    raw_text: Optional[str] = None
    try:
        import tempfile

        from app.services import cv_text_extractor

        def _extract() -> Optional[str]:
            suffix = os.path.splitext(filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                tmp.write(content)
                tmp.flush()
                return cv_text_extractor.extract_text(tmp.name, filename)

        raw_text = await asyncio.to_thread(_extract)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] inert CV text extraction failed: %s", e)

    return object_key, file_bytes, raw_text


@router.post(
    "/apply/{token}",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
@limiter.limit("5/minute; 30/hour")
async def submit_public_apply(
    request: Request,
    token: str,
    background_tasks: BackgroundTasks,
    first_name: str = Form(..., min_length=1, max_length=100),
    last_name: str = Form(..., min_length=1, max_length=100),
    email: EmailStr = Form(...),
    phone: Optional[str] = Form(None, max_length=30),
    linkedin: Optional[str] = Form(None, max_length=500),
    message: Optional[str] = Form(None, max_length=2000),
    cv: UploadFile = File(...),
    # UTM attribution (Traffit gap #4) — sent by the public /apply page from
    # the URL query string (?utm_source=linkedin&utm_campaign=...). All five
    # are optional Form fields so old applications without UTM still validate.
    utm_source: Optional[str] = Form(None, max_length=120),
    utm_medium: Optional[str] = Form(None, max_length=120),
    utm_campaign: Optional[str] = Form(None, max_length=120),
    utm_term: Optional[str] = Form(None, max_length=120),
    utm_content: Optional[str] = Form(None, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a public application via an invite link.

    Two outcomes, both returning an identical generic 201 — the response never
    reveals whether the e-mail already existed (the old ``created``/``updated``
    discriminator, an account-enumeration oracle, is gone):

    * **New e-mail (branch A)** — a fresh candidate is created and owned by the
      inviting recruiter, exactly as before.
    * **Duplicate e-mail (branch B, P0-CAND-01 containment)** — the existing
      candidate is NOT touched (no name/CV/contact/ownership/stage mutation).
      The applicant payload + CV are parked as a ``pending_review``
      ``ApplicationSubmission`` for recruiter triage (link / merge / create /
      reject) via ``/api/application-submissions``. A public, reusable invite
      link plus a known e-mail can no longer poison a canonical profile.
    """
    link = await _load_valid_link(token, db)

    if phone and not _PHONE_RE.match(phone.strip()):
        raise HTTPException(status_code=422, detail="Invalid phone format")

    content = await cv.read()
    _validate_cv_file(cv, content)

    # Identifies the link in rows that must not carry the raw secret. Both
    # branches below stamp it: a v2 link's `token` PK is a non-secret revoke
    # key, so the raw-token prefix they also record resolves nothing on its own.
    # Read side: `_resolve_invite_source` in api/candidates.
    token_digest = hashlib.sha256(token.encode()).hexdigest()

    # Duplicate-by-email — case-insensitive match.
    normalized_email = str(email).strip().lower()
    existing = await db.scalar(
        select(Candidate).where(func.lower(Candidate.email) == normalized_email)
    )

    if existing is not None:
        # ── Branch B: park the submission, never mutate the candidate ──────
        object_key, cv_bytes, submission_raw_text = await _persist_submission_cv(
            cv, content
        )
        submission = ApplicationSubmission(
            invite_link_token_sha256=token_digest,
            job_id=link.job_id,
            status=ApplicationSubmissionStatus.pending_review.value,
            submitted_first_name=first_name.strip(),
            submitted_last_name=last_name.strip(),
            submitted_email=str(email),
            submitted_phone=phone.strip() if phone else None,
            submitted_linkedin=linkedin.strip() if linkedin else None,
            submitted_message=message.strip() if message else None,
            matched_candidate_id=existing.id,
            cv_object_key=object_key,
            cv_file_content=cv_bytes,
            cv_filename=(cv.filename or "cv.pdf"),
            cv_content_type=cv.content_type,
            cv_size_bytes=len(content),
            raw_cv_text=submission_raw_text,
            raw_payload={
                "origin_assignment_id": link.origin_assignment_id,
                "priority_compliant_at_create": (link.priority_compliant_at_create),
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "email": str(email),
                "phone": phone.strip() if phone else None,
                "linkedin": linkedin.strip() if linkedin else None,
                "message": message.strip() if message else None,
                "utm": {
                    "source": utm_source,
                    "medium": utm_medium,
                    "campaign": utm_campaign,
                    "term": utm_term,
                    "content": utm_content,
                },
            },
        )
        db.add(submission)
        await db.flush()

        # Audit against the SUBMISSION, not the candidate (which is untouched):
        # no candidate history is rewritten and no candidate PII is exposed.
        db.add(
            Activity(
                entity_type="application_submission",
                entity_id=submission.id,
                action="submission_received",
                user_id=link.created_by,
                details={
                    "invite_token": token[:8],
                    "invite_token_sha256": token_digest,
                    "job_id": link.job_id,
                    "matched_candidate_id": existing.id,
                },
            )
        )

        # The link WAS used — count it, even though no candidate was created.
        link.use_count += 1
        link.last_used_at = datetime.now(timezone.utc)
        await db.commit()

        return {"ok": True, "status": "received"}

    # ── Branch A: genuinely new applicant — create the candidate ──────────
    candidate = Candidate(
        name=first_name.strip(),
        lastname=last_name.strip(),
        email=str(email),
        phone=phone.strip() if phone else None,
        linkedin=linkedin.strip() if linkedin else None,
        source=f"invite_link:{token[:8]}",
        status=CandidateStatus.active,
        created_by=link.created_by,
        profile_about=message.strip() if message else None,
    )
    db.add(candidate)
    await db.flush()

    # Persist CV onto the new candidate.
    stored_filename, raw_text = await _persist_cv(candidate.id, cv, content)
    candidate.cv_filename = stored_filename
    if raw_text:
        candidate.raw_cv_text = raw_text
    content_hash = hashlib.sha256(content).hexdigest()
    document = CandidateDocument(
        candidate_id=candidate.id,
        filename=stored_filename,
        file_content=content,
        content_type=cv.content_type,
        size_bytes=len(content),
        document_kind=CandidateDocumentKind.cv,
        is_primary=True,
        uploaded_at=datetime.now(timezone.utc),
        external_source="invite_link",
        content_sha256=content_hash,
    )
    db.add(document)
    await db.flush()

    # Ensure CandidateStage for (candidate, link.job_id) exists at stage="new".
    stage_exists = await db.scalar(
        select(CandidateStage).where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == link.job_id,
        )
    )
    if stage_exists is None:
        new_stage = await open_process(
            db,
            candidate_id=candidate.id,
            job_id=link.job_id,
            stage=PipelineStage.new,
            actor_user_id=link.created_by,
            origin_kind=PriorityOriginKind.external_inbound,
            frozen_origin_assignment_id=link.origin_assignment_id,
            frozen_priority_compliant=link.priority_compliant_at_create,
            notes="Aplikacja przez invite link",
        )
        # Snapshot CV — kandydat właśnie wgrał `stored_filename` powyżej, więc
        # `candidate.cv_file_content` już jest aktualny i pójdzie do snapshotu.
        await create_original_cv_snapshot(db, new_stage)
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=candidate.id,
            job_id=link.job_id,
            source="pipeline",
            occurred_at=new_stage.moved_at,
        )

    # Audit trail — link the Activity to the inviting recruiter.
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="applied_via_invite",
            user_id=link.created_by,
            details={
                "invite_token": token[:8],
                "invite_token_sha256": token_digest,
                "job_id": link.job_id,
                "was_duplicate": False,
            },
        )
    )
    db.add(
        UserActivity(
            user_id=link.created_by,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={
                "name": f"{candidate.name} {candidate.lastname}",
                "source": "invite_link",
                "invite_token": token[:8],
                "invite_token_sha256": token_digest,
                "was_duplicate": False,
            },
        )
    )

    # Increment usage counters on the link.
    link.use_count += 1
    link.last_used_at = datetime.now(timezone.utc)

    # Record source attribution event (Traffit gap #4). Channel is always
    # ``posting`` for invite-link apply — this is the public landing page
    # for a published job. UTM params come from the URL the candidate
    # followed; absent = direct apply.
    from app.models.candidate_source_event import (
        CandidateSourceEvent,
        SourceChannel,
    )

    db.add(
        CandidateSourceEvent(
            candidate_id=candidate.id,
            channel=SourceChannel.posting,
            job_id=link.job_id,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            utm_term=utm_term,
            utm_content=utm_content,
        )
    )

    await db.commit()

    # ── Post-apply enrichment pipeline ────────────────────────────────────
    # Inline: embedding so the candidate is immediately matchable against
    # other open jobs. Failures are logged but don't break the apply flow.
    try:
        from app.services.embedding_service import embed_candidate

        await embed_candidate(candidate.id, db)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[apply] embed_candidate failed candidate=%s: %s", candidate.id, e
        )

    # Background: CV parse (companies, skills, ai_summary) + CC auto-classify.
    # Runs in a fresh DB session after the response has been sent, so the
    # candidate sees a fast 201.
    background_tasks.add_task(_invite_post_apply_task, candidate.id)

    return {"ok": True, "status": "received"}


async def _invite_post_apply_task(
    candidate_id: int,
    source_document_id: Optional[int] = None,
    source_hash: Optional[str] = None,
) -> None:
    """After-response pipeline for invite-link applications.

    Steps:
    1. Run the same CV enrichment used by authenticated `POST /candidates/{id}/cv`
       (parse companies/skills, flag `cv_parsed_at`, invalidate match cache).
    2. Classify the candidate into Competence Categories. When the top-1
       score is ≥ 0.30 and `competence_category` is still empty, auto-assign
       it so the candidate shows up in matching right away.

    Never raises — every failure is logged so the original apply response
    stays successful.
    """
    from app.core.database import AsyncSessionLocal

    # (1) Reuse the authenticated-flow enrichment task — it already runs in
    # a fresh session and is the single source of truth for CV parsing.
    try:
        from app.api.candidates import _enrich_candidate_cv_task

        if source_document_id is None:
            async with AsyncSessionLocal() as db:
                primary = (
                    await db.execute(
                        select(
                            CandidateDocument.id,
                            CandidateDocument.content_sha256,
                        ).where(
                            CandidateDocument.candidate_id == candidate_id,
                            CandidateDocument.document_kind == CandidateDocumentKind.cv,
                            CandidateDocument.is_primary.is_(True),
                            CandidateDocument.source_deleted_at.is_(None),
                        )
                    )
                ).first()
            if primary is not None:
                source_document_id = primary.id
                source_hash = primary.content_sha256
        if source_document_id is None:
            await _enrich_candidate_cv_task(candidate_id)
        else:
            await _enrich_candidate_cv_task(
                candidate_id,
                source_document_id,
                source_hash,
            )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] CV enrichment failed candidate=%s: %s", candidate_id, e)

    # (2) CC classification + auto-assign. Needs its own session because the
    # previous task committed and closed its session. Routes through the shared
    # writer (M2M primary + up to 2 secondary, synced legacy fields), same as
    # the authenticated CV path; `overwrite=False` fills only when empty.
    try:
        from app.services.candidate_cc_assignment import apply_candidate_cc_scores
        from app.services.cc_classifier import classify_candidate_to_cc

        async with AsyncSessionLocal() as db:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            if candidate is None:
                return
            scores = await classify_candidate_to_cc(candidate, db)
            summary = await apply_candidate_cc_scores(
                candidate, scores, db, overwrite=False
            )
            if summary:
                await db.commit()
                logger.info(
                    "[apply] auto-assigned CC candidate=%s primary=%s score=%.3f",
                    candidate_id,
                    summary["primary"],
                    summary["primary_score"],
                )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] CC classify failed candidate=%s: %s", candidate_id, e)
