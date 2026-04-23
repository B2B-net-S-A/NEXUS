import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_invalidate
from app.core.database import get_db
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.schemas.job import (
    CcOverrideRequest,
    CcSuggestion,
    CcSuggestionsResponse,
    JobCloseRequest,
    JobCollaboratorAdd,
    JobCreate,
    JobOwnerAssignment,
    JobResponse,
    JobUpdate,
    UserBrief,
)
from app.api.deps import CurrentUser, DeliveryLeadPlus, TacPlus
from app.api.notifications import create_notification
from app.api.ws import manager as ws_manager
from app.core.config import settings
from app.services.champion_profile_events import (
    diff_champion_profile,
    summarize_sections,
)
from app.services.marketplace_service import (
    is_significant_job_update,
    run_marketplace_scan_safe,
)
from app.tasks.compute_proposals import (
    compute_proposal_for_job,
    create_pending_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Fields that, when changed, should trigger re-embedding the job (Phase 2).
_EMBED_TRIGGER_FIELDS = {
    "title",
    "description",
    "requirements",
    "must_skills",
    "nice_skills",
    "seniority",
    "subcategory",
    "industry",
}


async def _maybe_embed_job(job_id: int, db: AsyncSession) -> None:
    """Fire-and-log job embedding; never raises."""
    try:
        from app.services.embedding_service import embed_job

        await embed_job(job_id, db)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[Job] embedding failed for job {job_id}: {e}")


# ── Recruiter ownership helpers ─────────────────────────────────────────────
# Primary owner lives on `jobs.recruiter_id` (nullable FK). Collaborators are
# rows in `job_collaborators` — same semantics for the "Moje projekty" filter
# but no write rights on the job itself.

_OWNERSHIP_ELIGIBLE_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}


async def _hydrate_owner_map(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, UserBrief]:
    """Batch-load UserBrief objects keyed by id for owner/collaborator embedding."""
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: UserBrief.model_validate(u) for u in result.scalars().all()}


async def _load_collaborator_map(
    db: AsyncSession, job_ids: list[int]
) -> dict[int, list[int]]:
    """Return {job_id: [user_id, ...]} for the given job ids."""
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(JobCollaborator.job_id, JobCollaborator.user_id).where(
                JobCollaborator.job_id.in_(job_ids)
            )
        )
    ).all()
    out: dict[int, list[int]] = {}
    for job_id, user_id in rows:
        out.setdefault(job_id, []).append(user_id)
    return out


async def _require_manage_ownership(
    job: Job, current_user: User
) -> None:
    """Gate for collaborator add/remove: admin, delivery_lead, or primary owner."""
    if current_user.role in (UserRole.admin, UserRole.delivery_lead):
        return
    if job.recruiter_id is not None and job.recruiter_id == current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires admin, delivery_lead, or primary owner of this job",
    )


@router.get("")
async def list_jobs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[JobStatus] = None,
    recruitment_type: Optional[RecruitmentType] = None,
    client_id: Optional[int] = None,
    q: Optional[str] = None,
    owner_id: Optional[int] = Query(
        None, description="Filter by primary_owner user id (recruiter_id)."
    ),
    mine: bool = Query(
        False,
        description=(
            "Limit to jobs where current user is primary owner or collaborator."
        ),
    ),
):
    from app.models.recruitment_pipeline import CandidateStage

    query = select(Job)
    if status:
        query = query.where(Job.status == status)
    if recruitment_type:
        query = query.where(Job.recruitment_type == recruitment_type)
    if client_id:
        query = query.where(Job.client_id == client_id)
    if q:
        query = query.where(Job.title.ilike(f"%{q}%"))
    if owner_id is not None:
        query = query.where(Job.recruiter_id == owner_id)
    if mine:
        collab_subq = select(JobCollaborator.job_id).where(
            JobCollaborator.user_id == current_user.id
        )
        query = query.where(
            or_(Job.recruiter_id == current_user.id, Job.id.in_(collab_subq))
        )
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    jobs = list(result.scalars().all())

    # Candidate counts per job (distinct candidates in pipeline)
    job_ids = [j.id for j in jobs]
    counts: dict[int, int] = {}
    if job_ids:
        count_result = await db.execute(
            select(
                CandidateStage.job_id,
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(CandidateStage.job_id.in_(job_ids))
            .group_by(CandidateStage.job_id)
        )
        counts = dict(count_result.all())

    # Hydrate primary_owner + collaborators in one pass (avoid N+1).
    collab_map = await _load_collaborator_map(db, job_ids)
    user_ids: set[int] = set()
    for j in jobs:
        if j.recruiter_id is not None:
            user_ids.add(j.recruiter_id)
    for ids in collab_map.values():
        user_ids.update(ids)
    user_brief_map = await _hydrate_owner_map(db, user_ids)

    items = []
    for j in jobs:
        d = JobResponse.model_validate(j).model_dump()
        d["candidate_count"] = counts.get(j.id, 0)
        d["primary_owner"] = (
            user_brief_map.get(j.recruiter_id) if j.recruiter_id is not None else None
        )
        if d["primary_owner"] is not None:
            d["primary_owner"] = d["primary_owner"].model_dump()
        collab_ids = collab_map.get(j.id, [])
        d["collaborators"] = [
            user_brief_map[uid].model_dump()
            for uid in collab_ids
            if uid in user_brief_map
        ]
        items.append(d)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobCreate,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # AI CC matching (migracja 0041). If the caller didn't specify a CC and
    # opted into auto-suggest, we run the classifier *after* the embedding
    # has been generated (needs job text). For create we must persist first
    # to get `job.id`; classifier will be called below post-embed.
    payload = data.model_dump(
        exclude={"auto_suggest_cc", "secondary_cc_ids"}
    )
    secondary_cc_ids = data.secondary_cc_ids or []
    auto_suggest = data.auto_suggest_cc

    job = Job(**payload, created_by=current_user.id)
    db.add(job)
    await db.flush()

    # Persist secondary CC links (manual from caller, if any)
    if secondary_cc_ids:
        from app.models.cc_feedback import JobSecondaryCc

        for cc_id in secondary_cc_ids[:2]:  # cap at 2
            db.add(JobSecondaryCc(job_id=job.id, competence_category_id=cc_id))

    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="created",
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Phase 2: embed the job so reverse matching picks it up.
    await _maybe_embed_job(job.id, db)

    # AI CC classification + auto-add collaborators (post-embed so classifier
    # has both keyword + embedding signal). Any failure is non-fatal.
    try:
        if job.competence_category_id is None and auto_suggest:
            from app.services.cc_classifier import classify_job_to_cc

            result = await classify_job_to_cc(job, db)
            if result.top and not result.tie:
                job.competence_category_id = result.top.cc_id
                await db.commit()
                await db.refresh(job)
        if job.competence_category_id is not None:
            from app.services.auto_cc_collaborators import auto_add_cc_collaborators

            await auto_add_cc_collaborators(
                db,
                job_id=job.id,
                competence_category_id=job.competence_category_id,
                added_by=current_user.id,
            )
    except Exception as e:  # pragma: no cover — never block job creation
        logger.warning("[Job] CC auto-assignment failed for job %s: %s", job.id, e)

    # Phase 13: kick off AI candidate proposals for the freshly-created job.
    # Snapshot is created synchronously (so the UI can start polling), and the
    # expensive scoring pass runs in the background.
    try:
        snapshot_id = await create_pending_snapshot(
            job.id,
            top_k=20,
            source="create",
            created_by=current_user.id,
        )
        background_tasks.add_task(
            compute_proposal_for_job, snapshot_id, job.id, top_k=20
        )
    except Exception as e:  # pragma: no cover — never block job creation
        logger.warning(
            "[Job] proposal snapshot dispatch failed for job %s: %s", job.id, e
        )

    # Targ kandydatów (migracja 0052-0054): jeśli enabled, rescan puli marketplace
    # z tym nowym jobem i wygeneruj notyfikacje ≥ MARKETPLACE_SCORE_THRESHOLD.
    # Dedup przez uq_marketplace_alert_pair — ten sam job nigdy nie wygeneruje
    # drugiej notyfikacji dla tej samej pary (candidate_id, job_id).
    if settings.MARKETPLACE_ENABLED:
        background_tasks.add_task(run_marketplace_scan_safe, job.id)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    collab_map = await _load_collaborator_map(db, [job.id])
    collab_ids = collab_map.get(job.id, [])
    user_ids: set[int] = set(collab_ids)
    if job.recruiter_id is not None:
        user_ids.add(job.recruiter_id)
    user_brief_map = await _hydrate_owner_map(db, user_ids)

    payload = JobResponse.model_validate(job).model_dump()
    payload["primary_owner"] = (
        user_brief_map[job.recruiter_id].model_dump()
        if job.recruiter_id in user_brief_map
        else None
    )
    payload["collaborators"] = [
        user_brief_map[uid].model_dump() for uid in collab_ids if uid in user_brief_map
    ]
    return payload


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int,
    data: JobUpdate,
    current_user: TacPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updates = data.model_dump(exclude_unset=True)
    prev_status = job.status
    # Snapshot istotnych pól przed mutacją — potrzebne do marketplace diff.
    # Trzymamy kolumny z _SIGNIFICANT_FIELDS, nawet gdy nie ma ich w `updates`
    # (`is_significant_job_update` sam ignoruje niezmienione).
    _marketplace_snapshot_fields = (
        "must_skills",
        "nice_skills",
        "seniority",
        "subcategory",
        "industry",
        "title",
    )
    _before = {f: getattr(job, f) for f in _marketplace_snapshot_fields}
    for k, v in updates.items():
        setattr(job, k, v)

    # Track closed_at transitions so `/api/reports/clients` can filter by
    # real close date (not updated_at). See migration 0047_job_closed_at.
    new_status = job.status
    status_flipped = "status" in updates and prev_status != new_status
    if status_flipped:
        if new_status == JobStatus.closed:
            job.closed_at = datetime.now(timezone.utc)
        elif prev_status == JobStatus.closed:
            job.closed_at = None

    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="updated",
            user_id=current_user.id,
            details=updates,
        )
    )
    await db.commit()
    await db.refresh(job)

    # Invalidate client hit-ratio cache on status changes (affects aggregates).
    if status_flipped:
        await cache_invalidate("reports:clients")

    # Phase 2: re-embed if any embed-relevant field changed
    changed = set(updates.keys())
    if _EMBED_TRIGGER_FIELDS & changed:
        await _maybe_embed_job(job_id, db)

    # Phase C1: invalidate cached (*, job) match scores when any scoring input
    # changes (_EMBED_TRIGGER_FIELDS covers must/nice, seniority, salary, etc.)
    if _EMBED_TRIGGER_FIELDS & changed:
        from app.services.match_score_cache import mark_stale_for_job

        await mark_stale_for_job(db, job_id)
        await db.commit()

    # Targ kandydatów: rescan tylko gdy zmieniły się pola wpływające na scoring
    # (_SIGNIFICANT_FIELDS z marketplace_service). Ignoruje zwykłe edycje opisu.
    if settings.MARKETPLACE_ENABLED:
        _after = {f: getattr(job, f) for f in _before.keys()}
        if is_significant_job_update(_before, _after):
            background_tasks.add_task(run_marketplace_scan_safe, job_id)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="deleted",
            user_id=current_user.id,
        )
    )
    await db.delete(job)


@router.post("/{job_id}/close", response_model=JobResponse)
async def close_job(
    job_id: int,
    data: JobCloseRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Close a job with a structured reason.

    Atomically: status → closed, closed_at = now, close_reason + close_notes
    persisted. Invalidates `reports:clients` cache so hit ratio reflects the
    change. For unstructured close (legacy) use PATCH /jobs/{id} with
    `status=closed` — setter still writes `closed_at` but leaves reason NULL.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.closed
    job.closed_at = datetime.now(timezone.utc)
    job.close_reason = data.reason
    job.close_notes = data.notes

    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="closed",
            user_id=current_user.id,
            details={
                "reason": data.reason.value,
                "notes": data.notes,
            },
        )
    )
    await db.commit()
    await db.refresh(job)

    await cache_invalidate("reports:clients")
    return job


@router.post("/{job_id}/publish")
async def publish_job(
    job_id: int, current_user: TacPlus, db: AsyncSession = Depends(get_db)
):
    """Publish job — mark as published and queue portal syndication."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.published
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="published",
            user_id=current_user.id,
        )
    )
    return {"status": "published", "job_id": job_id}


# ── Champion Profile (Phase 10) ─────────────────────────────────────────────


@router.get("/{job_id}/champion-profile")
async def get_champion_profile(
    job_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> dict:
    """Return the Delivery Lead's Champion Profile for this job (or {}).

    Side effect: any unread ``champion_profile_updated`` notifications
    addressed to the caller for this specific job are marked as read —
    this implements "powiadomienie znika jak Rekruter otworzy" regardless
    of whether the user arrived via the notification dropdown, a direct
    URL, or an internal link.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await db.execute(
        sql_update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.notification_type
            == NotificationType.champion_profile_updated,
            Notification.related_entity_type == "job",
            Notification.related_entity_id == job_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()

    return {
        "job_id": job.id,
        "job_title": job.title,
        "champion_profile": job.champion_profile or {},
    }


async def _champion_profile_recipients(
    db: AsyncSession, job: Job, exclude_user_id: int
) -> list[int]:
    """Return the distinct user ids that should be notified of a CP edit.

    The set is the primary ``recruiter_id`` plus everyone in
    ``job_collaborators`` — minus the editor themselves. Nulls are
    filtered out.
    """
    rows = await db.execute(
        select(JobCollaborator.user_id).where(JobCollaborator.job_id == job.id)
    )
    collaborator_ids = {uid for (uid,) in rows.all() if uid is not None}
    if job.recruiter_id is not None:
        collaborator_ids.add(job.recruiter_id)
    collaborator_ids.discard(exclude_user_id)
    return sorted(collaborator_ids)


@router.put("/{job_id}/champion-profile")
async def update_champion_profile(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
) -> dict:
    """Upsert Champion Profile (Delivery Lead / admin only).

    On a content change, notifies everyone assigned to the job
    (``recruiter_id`` + ``job_collaborators``) minus the editor. Emits
    both the standard ``notification`` WS event (for the bell badge) and
    a dedicated ``champion_profile_changed`` event so any open editor
    can refetch and show an inline "someone just updated this" banner.
    """
    from app.schemas.champion import ChampionProfile

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    old_profile = dict(job.champion_profile) if job.champion_profile else {}
    profile = ChampionProfile.model_validate(payload or {})
    new_profile = profile.model_dump()

    fields_changed = diff_champion_profile(old_profile, new_profile)
    if not fields_changed:
        return {"job_id": job.id, "champion_profile": job.champion_profile or {}}

    job.champion_profile = new_profile
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="champion_profile_updated",
            user_id=current_user.id,
        )
    )

    recipients = await _champion_profile_recipients(
        db, job, exclude_user_id=current_user.id
    )
    editor_name = (current_user.name or "Ktoś").strip() or "Ktoś"
    sections_pl = summarize_sections(fields_changed)
    title = "Profil Championa zaktualizowany"
    message_text = (
        f"{editor_name} zmienił {sections_pl} dla: {job.title}"
        if sections_pl
        else f"{editor_name} zaktualizował profil dla: {job.title}"
    )
    link = f"/jobs/{job.id}?tab=champion-profile"

    for recipient_id in recipients:
        await create_notification(
            db=db,
            user_id=recipient_id,
            title=title,
            message=message_text,
            notification_type=NotificationType.champion_profile_updated,
            link=link,
            related_entity_type="job",
            related_entity_id=job.id,
            dedupe_resurface=True,
        )

    await db.commit()
    await db.refresh(job)

    now_iso = datetime.now(timezone.utc).isoformat()
    bell_event = {
        "type": "notification",
        "data": {
            "title": title,
            "message": message_text,
            "link": link,
            "notification_type": NotificationType.champion_profile_updated.value,
            "related_entity_type": "job",
            "related_entity_id": job.id,
            "created_at": now_iso,
        },
    }
    live_event = {
        "type": "champion_profile_changed",
        "data": {
            "job_id": job.id,
            "updated_by_user_id": current_user.id,
            "updated_by_name": editor_name,
            "updated_at": now_iso,
            "fields_changed": fields_changed,
        },
    }
    for recipient_id in recipients:
        try:
            await ws_manager.notify_user(recipient_id, bell_event)
            await ws_manager.notify_user(recipient_id, live_event)
        except Exception as e:  # pragma: no cover — WS push must never 500 the write
            logger.warning(
                "[Champion Profile] WS notify failed user=%s job=%s: %s",
                recipient_id,
                job.id,
                e,
            )

    return {"job_id": job.id, "champion_profile": job.champion_profile}


# ── Champion Profile AI Intake (Phase 14) ───────────────────────────────────


@router.post("/{job_id}/champion-profile/generate-from-jd")
async def generate_champion_from_jd(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Kick off LLM-based Champion Profile draft from a raw job description.

    Returns the newly-created `ChampionProfileSuggestion` (status=pending,
    unless the LLM / validation fails — then status=rejected).
    """
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionOut,
        GenerateFromJdPayload,
        patches_from_payload,
    )
    from app.services.champion_draft_service import generate_from_jd

    body = GenerateFromJdPayload.model_validate(payload or {})
    suggestion = await generate_from_jd(
        db,
        job_id=job_id,
        raw_description=body.raw_description,
        user_id=current_user.id,
    )
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.post("/{job_id}/champion-profile/generate-from-history")
async def generate_champion_from_history(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Generate a Champion Profile draft from top-K similar closed jobs (Phase 15).

    Mirrors `generate-from-jd` but sources narrative + sourcing + screening
    data from historical roles with populated `champion_profile`. When there
    are too few matches for the job's client, returns a `rejected` suggestion
    with an explanatory `error_message` so the UI can tell the DL why.
    """
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionOut,
        GenerateFromHistoryPayload,
        patches_from_payload,
    )
    from app.services.champion_draft_service import generate_from_historical_jobs

    body = GenerateFromHistoryPayload.model_validate(payload or {})
    suggestion = await generate_from_historical_jobs(
        db,
        job_id=job_id,
        raw_description=body.raw_description,
        top_k=body.top_k,
        cross_client=body.cross_client,
        user_id=current_user.id,
    )
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return out


@router.get("/{job_id}/champion-profile/historical-matches")
async def get_champion_historical_matches(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    top_k: int = Query(default=5, ge=1, le=15),
    cross_client: bool = Query(default=False),
):
    """Preview the top-K historical matches for an existing Job (no LLM).

    Powers the side-panel cards DLs see before deciding whether to trigger
    generate-from-history. Cheap — only runs Voyage embed + Qdrant search +
    one SQL round-trip. Does NOT persist anything.
    """
    from app.schemas.champion_suggestion import (
        HistoricalMatchesResponse,
        HistoricalMatchPreview,
    )
    from app.services.historical_jobs_retrieval import (
        find_similar_historical_jobs,
        skill_frequency,
    )

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    matches = await find_similar_historical_jobs(
        db,
        client_id=job.client_id,
        title=job.title or "",
        raw_description=job.description or "",
        top_k=top_k,
        cross_client=cross_client,
        exclude_job_id=job.id,
    )

    previews = [
        HistoricalMatchPreview(
            job_id=m.job_id,
            title=m.title,
            similarity=m.similarity,
            closed_at=m.closed_at,
            client_id=m.client_id,
            client_name=m.client_name,
            seniority=m.seniority,
            same_train=m.same_train,
            has_champion_profile=bool(m.champion_profile),
            must_skills_count=len(m.must_skills or []),
            nice_skills_count=len(m.nice_skills or []),
        )
        for m in matches
    ]
    return HistoricalMatchesResponse(
        matches=previews,
        skill_frequency=skill_frequency(matches),
    )


@router.post("/champion-profile/historical-matches")
async def preview_historical_matches_for_new_role(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Preview historical matches for an UNSAVED role (new-role wizard).

    Takes title/client_id/raw_description straight from the form, so the DL
    can see "you have 3 similar closed roles at this client" before even
    saving a draft. No persistence, no LLM.
    """
    from app.schemas.champion_suggestion import (
        HistoricalMatchesPreviewRequest,
        HistoricalMatchesResponse,
        HistoricalMatchPreview,
    )
    from app.services.historical_jobs_retrieval import (
        find_similar_historical_jobs,
        skill_frequency,
    )

    body = HistoricalMatchesPreviewRequest.model_validate(payload or {})

    matches = await find_similar_historical_jobs(
        db,
        client_id=body.client_id,
        title=body.title,
        raw_description=body.raw_description,
        top_k=body.top_k,
        cross_client=body.cross_client,
    )

    previews = [
        HistoricalMatchPreview(
            job_id=m.job_id,
            title=m.title,
            similarity=m.similarity,
            closed_at=m.closed_at,
            client_id=m.client_id,
            client_name=m.client_name,
            seniority=m.seniority,
            same_train=m.same_train,
            has_champion_profile=bool(m.champion_profile),
            must_skills_count=len(m.must_skills or []),
            nice_skills_count=len(m.nice_skills or []),
        )
        for m in matches
    ]
    return HistoricalMatchesResponse(
        matches=previews,
        skill_frequency=skill_frequency(matches),
    )


@router.get("/{job_id}/champion-profile/suggestions")
async def list_champion_suggestions(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List Champion Profile suggestions for a job, newest first."""
    from app.models.champion_suggestion import ChampionProfileSuggestion, SuggestionStatus
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionListOut,
        ChampionProfileSuggestionOut,
        patches_from_payload,
    )

    stmt = select(ChampionProfileSuggestion).where(
        ChampionProfileSuggestion.job_id == job_id
    )
    if status_filter:
        try:
            status_enum = SuggestionStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        stmt = stmt.where(ChampionProfileSuggestion.status == status_enum)
    stmt = stmt.order_by(ChampionProfileSuggestion.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for row in rows:
        out = ChampionProfileSuggestionOut.model_validate(row)
        out.patches = patches_from_payload(row.payload or {})
        items.append(out)
    return ChampionProfileSuggestionListOut(items=items, total=len(items))


# ── Recruiter ownership endpoints ───────────────────────────────────────────
# Primary owner (`recruiter_id`) is changed by Admin + Delivery Lead only.
# "Claim" is self-assign on an unassigned job — open to anyone who can write
# to jobs (admin/DL/TAC/recruiter/sourcer). The `user` read-only role is
# blocked.


@router.post("/{job_id}/owner", response_model=JobResponse)
async def assign_owner(
    job_id: int,
    payload: JobOwnerAssignment,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Set/change the primary owner (recruiter_id). Admin + Delivery Lead only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if target.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot own a job",
        )

    job.recruiter_id = target.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="owner_assigned",
            user_id=current_user.id,
            details={"new_owner_id": target.id},
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.delete("/{job_id}/owner", response_model=JobResponse)
async def release_owner(
    job_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Unassign the primary owner (sets recruiter_id = NULL). Admin + DL only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    previous = job.recruiter_id
    job.recruiter_id = None
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="owner_released",
            user_id=current_user.id,
            details={"previous_owner_id": previous},
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.post("/{job_id}/claim", response_model=JobResponse)
async def claim_job(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Self-assign an unassigned job to the current user.

    Rejects if the job already has a primary owner (409) or the current user
    is a read-only viewer (403). Any user in the ownership-eligible role set
    can claim.
    """
    if current_user.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Read-only viewers cannot claim jobs",
        )

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.recruiter_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job already has a primary owner",
        )

    job.recruiter_id = current_user.id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="claimed",
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(job)
    return await get_job(job_id, current_user, db)


@router.get("/{job_id}/collaborators", response_model=list[UserBrief])
async def list_collaborators(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List collaborators (read-only participants) on a job."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = (
        await db.execute(
            select(User)
            .join(JobCollaborator, JobCollaborator.user_id == User.id)
            .where(JobCollaborator.job_id == job_id)
            .order_by(User.name)
        )
    ).scalars().all()
    return [UserBrief.model_validate(u) for u in rows]


@router.post(
    "/{job_id}/collaborators",
    response_model=UserBrief,
    status_code=status.HTTP_201_CREATED,
)
async def add_collaborator(
    job_id: int,
    payload: JobCollaboratorAdd,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Add a collaborator. Admin/DL always; otherwise primary owner only.

    Idempotent at the DB layer via UNIQUE(job_id, user_id) — duplicate inserts
    return the existing row instead of raising.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await _require_manage_ownership(job, current_user)

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if not target or not target.is_active:
        raise HTTPException(status_code=409, detail="Target user not found or inactive")
    if target.role not in _OWNERSHIP_ELIGIBLE_ROLES:
        raise HTTPException(
            status_code=409,
            detail=f"Role {target.role.value} cannot be a collaborator",
        )
    if job.recruiter_id == target.id:
        raise HTTPException(
            status_code=409,
            detail="User is already the primary owner of this job",
        )

    existing = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job_id,
            JobCollaborator.user_id == target.id,
        )
    )
    if existing is None:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=target.id,
                added_by=current_user.id,
            )
        )
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="collaborator_added",
                user_id=current_user.id,
                details={"collaborator_id": target.id},
            )
        )
        await db.commit()
    return UserBrief.model_validate(target)


@router.delete(
    "/{job_id}/collaborators/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collaborator(
    job_id: int,
    user_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Remove a collaborator. Admin/DL always; otherwise primary owner only."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await _require_manage_ownership(job, current_user)

    link = await db.scalar(
        select(JobCollaborator).where(
            JobCollaborator.job_id == job_id,
            JobCollaborator.user_id == user_id,
        )
    )
    if link is None:
        # Idempotent: deleting a missing link is a success (204).
        return
    removed_source = link.source.value if link.source else "manual"
    await db.delete(link)
    # Feedback loop: when an auto_cc collaborator is removed we log to Activity
    # so Head of Recruitment can spot patterns (e.g. one sourcer removed 10×
    # from the same CC → revise user↔CC mapping). Stored on the Activity row
    # rather than the deleted row for queryability.
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=(
                "collaborator_removed_auto_cc"
                if removed_source == "auto_cc"
                else "collaborator_removed"
            ),
            user_id=current_user.id,
            details={
                "collaborator_id": user_id,
                "source": removed_source,
            },
        )
    )
    await db.commit()


# ── AI CC classification (migracja 0041) ────────────────────────────────────


def _cc_score_to_schema(score) -> CcSuggestion:
    """Map `cc_classifier.CcScore` → `CcSuggestion` pydantic schema."""
    return CcSuggestion(
        competence_category_id=score.cc_id,
        slug=score.slug,
        name_pl=score.name_pl,
        score=score.score,
        confidence_band=score.confidence_band,
        keywords_matched=score.keywords_matched,
    )


@router.post("/{job_id}/classify-cc", response_model=CcSuggestionsResponse)
async def classify_job_cc(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CcSuggestionsResponse:
    """Return top-3 CC suggestions for a job (current state, no DB write)."""
    from app.services.cc_classifier import classify_job_to_cc

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await classify_job_to_cc(job, db)
    top_schema = _cc_score_to_schema(result.top) if result.top else None
    alternatives = [_cc_score_to_schema(s) for s in result.alternatives]
    return CcSuggestionsResponse(top=top_schema, alternatives=alternatives, tie=result.tie)


@router.post("/{job_id}/cc-override", status_code=status.HTTP_201_CREATED)
async def log_cc_override(
    job_id: int,
    body: CcOverrideRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Log that a DL changed the AI-suggested CC. Used for feedback loop."""
    from app.models.cc_feedback import CcSuggestionOverride

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    override = CcSuggestionOverride(
        job_id=job_id,
        suggested_cc_id=body.suggested_cc_id,
        final_cc_id=body.final_cc_id,
        suggested_score=body.suggested_score,
        user_id=current_user.id,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return {
        "id": override.id,
        "job_id": job_id,
        "suggested_cc_id": body.suggested_cc_id,
        "final_cc_id": body.final_cc_id,
    }
