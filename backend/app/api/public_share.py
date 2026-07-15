"""Public (no-auth) endpoints for externally shareable artifacts.

Only routes registered here should be exempt from auth. Each route validates
its own unguessable token and honours `revoked` + `expires_at`. Sensitive
fields (emails of internal users, private labels, internal ids) are never
exposed on these endpoints.
"""

import asyncio
import logging
import os
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
    UploadFile,
    status,
)
from pydantic import EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.champion_share import ChampionCardShareToken
from app.models.cv_share_token import CVShareToken
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
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
    row: Optional[ChampionCardShareToken] = await db.scalar(
        select(ChampionCardShareToken).where(ChampionCardShareToken.token == token)
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
    row: Optional[CVShareToken] = await db.scalar(
        select(CVShareToken).where(CVShareToken.token == token)
    )
    if row is None or row.revoked:
        raise HTTPException(
            status_code=404, detail="Link nie istnieje lub został odwołany."
        )
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link wygasł.")

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

    # Source of truth: zapisany draft HTML (immutable po finalize). Storage
    # plik ma to samo, ale czytanie z DB jest szybsze i bezpieczniejsze
    # (brak ryzyka stale path traversal).
    cv_html = csv.branded_draft_html or ""

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
    link = await db.scalar(
        select(CandidateInviteLink).where(CandidateInviteLink.token == token)
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

    Creates a new candidate (branch A) or merges into an existing one by
    email (branch B, per user decision: "Zaktualizuj istniejący rekord").
    Ownership (`created_by`) is reassigned to the inviting recruiter so the
    candidate appears under their name in the list.
    """
    link = await _load_valid_link(token, db)

    if phone and not _PHONE_RE.match(phone.strip()):
        raise HTTPException(status_code=422, detail="Invalid phone format")

    content = await cv.read()
    _validate_cv_file(cv, content)

    # Duplicate-by-email — case-insensitive match.
    normalized_email = str(email).strip().lower()
    existing = await db.scalar(
        select(Candidate).where(func.lower(Candidate.email) == normalized_email)
    )

    branch: str  # "created" or "updated"
    previous_created_by: Optional[int] = None
    previous_cv_filename: Optional[str] = None

    if existing is None:
        candidate = Candidate(
            name=first_name.strip(),
            lastname=last_name.strip(),
            email=str(email),
            phone=phone.strip() if phone else None,
            linkedin=linkedin.strip() if linkedin else None,
            source=f"invite_link:{token[:8]}",
            status=CandidateStatus.active,
            created_by=link.created_by,
            ai_summary=message.strip() if message else None,
        )
        db.add(candidate)
        await db.flush()
        branch = "created"
    else:
        candidate = existing
        previous_created_by = candidate.created_by
        previous_cv_filename = candidate.cv_filename
        # Name: always refresh to whatever the candidate just typed.
        candidate.name = first_name.strip()
        candidate.lastname = last_name.strip()
        # Optional fields: only write when the existing value is empty.
        if not candidate.phone and phone:
            candidate.phone = phone.strip()
        if not candidate.linkedin and linkedin:
            candidate.linkedin = linkedin.strip()
        if message:
            # Append applicant message to ai_summary without destroying prior notes.
            prefix = (
                candidate.ai_summary.strip() + "\n\n" if candidate.ai_summary else ""
            )
            candidate.ai_summary = f"{prefix}[{datetime.now(timezone.utc).date().isoformat()}] {message.strip()}"
        # Ownership: reassign to the recruiter who posted the link.
        candidate.created_by = link.created_by
        branch = "updated"

    # Persist CV (always — both branches).
    stored_filename, raw_text = await _persist_cv(candidate.id, cv, content)
    candidate.cv_filename = stored_filename
    if raw_text:
        candidate.raw_cv_text = raw_text

    # Ensure CandidateStage for (candidate, link.job_id) exists at stage="new".
    stage_exists = await db.scalar(
        select(CandidateStage).where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == link.job_id,
        )
    )
    if stage_exists is None:
        new_stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=link.job_id,
            stage=PipelineStage.new,
            moved_by=link.created_by,
            notes="Aplikacja przez invite link",
        )
        db.add(new_stage)
        await db.flush()
        # Snapshot CV — kandydat właśnie wgrał `stored_filename` powyżej, więc
        # `candidate.cv_file_content` już jest aktualny i pójdzie do snapshotu.
        await create_original_cv_snapshot(db, new_stage)

    # Audit trail — link the Activity to the inviting recruiter.
    activity_details: dict = {
        "invite_token": token[:8],
        "job_id": link.job_id,
        "was_duplicate": branch == "updated",
    }
    if previous_created_by and previous_created_by != link.created_by:
        activity_details["previous_created_by"] = previous_created_by
    if previous_cv_filename and previous_cv_filename != stored_filename:
        activity_details["previous_cv_filename"] = previous_cv_filename
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="applied_via_invite",
            user_id=link.created_by,
            details=activity_details,
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
                "was_duplicate": branch == "updated",
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

    return {"ok": True, "status": branch}


async def _invite_post_apply_task(candidate_id: int) -> None:
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

        await _enrich_candidate_cv_task(candidate_id)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] CV enrichment failed candidate=%s: %s", candidate_id, e)

    # (2) CC classification + auto-assign. Needs its own session because the
    # previous task committed and closed its session.
    try:
        from app.services.cc_classifier import classify_candidate_to_cc

        async with AsyncSessionLocal() as db:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            if candidate is None:
                return
            scores = await classify_candidate_to_cc(candidate, db)
            if scores and scores[0].score >= 0.30 and not candidate.competence_category:
                candidate.competence_category = scores[0].slug
                candidate.competence_category_id = scores[0].cc_id
                await db.commit()
                logger.info(
                    "[apply] auto-assigned CC candidate=%s slug=%s score=%.3f",
                    candidate_id,
                    scores[0].slug,
                    scores[0].score,
                )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[apply] CC classify failed candidate=%s: %s", candidate_id, e)
