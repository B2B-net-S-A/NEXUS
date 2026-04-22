from datetime import datetime, timezone
from pydantic import BaseModel
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    STAGE_CATEGORY,
    STAGE_ORDER,
)
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.notification import Notification, NotificationType
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
)
from app.schemas.pipeline import (
    CandidateStageResponse,
    KanbanColumn,
    KanbanView,
    StageMove,
    StageInfo,
    STAGE_LABELS,
)
from app.api.deps import CurrentUser, RecruiterPlus
from app.api import ws as ws_manager

router = APIRouter()


# ── Helpers to bridge legacy enum ↔ new stage_def FK ────────────────────────


async def _default_template_id(db: AsyncSession) -> Optional[int]:
    """Return id of the is_default=true template (or None if unseeded)."""
    return await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )


async def _resolve_stage_def(
    db: AsyncSession,
    job: Optional[Job],
    *,
    stage_def_id: Optional[int] = None,
    legacy_stage: Optional[PipelineStage] = None,
) -> Optional[PipelineStageDef]:
    """Resolve a StageDef from either explicit id or legacy enum (via template)."""
    if stage_def_id:
        return await db.scalar(
            select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
        )
    if legacy_stage is None:
        return None

    template_id = (
        job.pipeline_template_id if job else None
    ) or await _default_template_id(db)
    if not template_id:
        return None
    return await db.scalar(
        select(PipelineStageDef).where(
            PipelineStageDef.template_id == template_id,
            PipelineStageDef.legacy_enum_value == legacy_stage.value,
        )
    )


def _days_in_stage(moved_at: datetime) -> int:
    """Calculate days a candidate has been in the current stage."""
    now = datetime.now(timezone.utc)
    if moved_at.tzinfo is None:
        from datetime import timezone as tz

        moved_at = moved_at.replace(tzinfo=tz.utc)
    return max(0, (now - moved_at).days)


def _stage_response(stage: CandidateStage) -> dict:
    """Convert a CandidateStage to response dict with days_in_stage."""
    return {
        "id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        "stage": stage.stage,
        "stage_def_id": stage.stage_def_id,
        "rejection_reason_id": stage.rejection_reason_id,
        "moved_at": stage.moved_at,
        "moved_by": stage.moved_by,
        "notes": stage.notes,
        "rating": stage.rating,
        "created_at": stage.created_at,
        "days_in_stage": _days_in_stage(stage.moved_at),
    }


@router.get("/stages", response_model=List[StageInfo])
async def list_stages(
    current_user: CurrentUser,
    job_id: Optional[int] = Query(
        None, description="If provided, return stages of this job's template."
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pipeline stages.

    - With `job_id`: stages of the template attached to that job.
    - Without: stages of the default template.

    Fallback: if no templates exist yet (e.g. during migration), returns the
    legacy hardcoded enum stages so the UI keeps rendering.
    """
    # Resolve template id
    template_id: Optional[int] = None
    if job_id is not None:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        template_id = job.pipeline_template_id
    if template_id is None:
        template_id = await _default_template_id(db)

    if template_id is not None:
        rows = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )
        result: list[StageInfo] = []
        for sd in rows:
            # Map new category enum → legacy StageCategory for BC
            legacy_enum = None
            if sd.legacy_enum_value:
                try:
                    legacy_enum = PipelineStage(sd.legacy_enum_value)
                except ValueError:
                    legacy_enum = None
            result.append(
                StageInfo(
                    stage=legacy_enum
                    or PipelineStage.new,  # fallback for custom stages
                    category=sd.category,
                    label=sd.name,
                    order=sd.order,
                    stage_def_id=sd.id,
                    is_terminal=sd.is_terminal,
                )
            )
        return result

    # Legacy fallback — pre-seed / no template world
    result = []
    for i, stage in enumerate(STAGE_ORDER):
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=i,
                is_terminal=False,
            )
        )
    for stage in [PipelineStage.rejected, PipelineStage.withdrawn]:
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=99,
                is_terminal=True,
            )
        )
    return result


@router.post("/move", response_model=CandidateStageResponse)
async def move_candidate(
    data: StageMove,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move a candidate to a new pipeline stage for a given job.

    Accepts either `stage` (legacy enum) or `stage_def_id` (new FK). For
    custom stages introduced via templates, the legacy enum is set to
    `PipelineStage.new` as a placeholder — the real identifier is stage_def_id.
    """
    if data.stage is None and data.stage_def_id is None:
        raise HTTPException(
            status_code=422,
            detail="Either `stage` (legacy enum) or `stage_def_id` must be provided",
        )

    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stage_def = await _resolve_stage_def(
        db, job, stage_def_id=data.stage_def_id, legacy_stage=data.stage
    )

    # Derive effective legacy-enum value for backward-compat column
    legacy_enum: PipelineStage = data.stage or PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = data.stage or PipelineStage.new

    # Terminal-move validation: require rejection_reason_id
    if (
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value
        in (
            "rejected",
            "withdrawn",
        )
    ):
        if not data.rejection_reason_id and not data.rejection_reason:
            raise HTTPException(
                status_code=422,
                detail=f"Terminal stage ({stage_def.terminal_type.value}) requires rejection_reason_id",
            )
        # Validate the FK
        if data.rejection_reason_id:
            reason = await db.scalar(
                select(RejectionReason).where(
                    RejectionReason.id == data.rejection_reason_id
                )
            )
            if not reason or not reason.active:
                raise HTTPException(
                    status_code=422,
                    detail="rejection_reason_id not found or inactive",
                )

    stage = CandidateStage(
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        rejection_reason_id=data.rejection_reason_id,
        moved_at=datetime.now(timezone.utc),
        moved_by=current_user.id,
        notes=data.notes,
        rating=data.rating,
    )
    db.add(stage)
    await db.flush()

    stage_display_name = (
        stage_def.name
        if stage_def
        else STAGE_LABELS.get(legacy_enum, legacy_enum.value)
    )

    # Activity log
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=current_user.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
                "stage_name": stage_display_name,
            },
        )
    )

    # UserActivity for leaderboard/performance tracking
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.stage_changed,
            entity_type="pipeline",
            entity_id=stage.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
            },
        )
    )

    # Notification for the recruiter assigned to the job (if different from current user)
    if job.recruiter_id and job.recruiter_id != current_user.id:
        notif = Notification(
            user_id=job.recruiter_id,
            title="Zmiana etapu kandydata",
            message=f"Kandydat #{data.candidate_id} → '{stage_display_name}' w ofercie #{data.job_id}.",
            link=f"/jobs/{data.job_id}",
            notification_type=NotificationType.stage_changed,
        )
        db.add(notif)
        await db.flush()
        await ws_manager.notify_user(
            job.recruiter_id,
            {
                "type": "notification",
                "data": {
                    "id": notif.id,
                    "title": notif.title,
                    "message": notif.message,
                    "link": notif.link,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )

    # Phase 10 A1: auto-add candidate to a talent pool when CV is sent to
    # the client. Pool is derived from JO subcategory + seniority (see
    # services/talent_pool_auto_add.py). Best-effort — pool-add failure
    # must NOT block the stage change, so errors are swallowed and logged.
    if legacy_enum == PipelineStage.cv_sent:
        import logging

        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        try:
            await auto_add_on_cv_sent(
                db=db,
                candidate_id=data.candidate_id,
                job=job,
                user_id=current_user.id,
            )
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "auto_add_on_cv_sent failed for candidate=%s job=%s: %s",
                data.candidate_id,
                job.id,
                e,
            )

    # Phase 9 A2: auto-create a draft Contract when the candidate is hired.
    # Staff fills in the rates + dates afterwards — this just removes the
    # "go to Contracts → create" click.
    if legacy_enum == PipelineStage.hired:
        from datetime import date as _date

        from app.models.contract import Contract, ContractStatus
        from app.models.user import User, UserRole

        existing_draft = await db.scalar(
            select(Contract).where(
                Contract.candidate_id == data.candidate_id,
                Contract.client_id == job.client_id,
                Contract.job_id == job.id,
                Contract.status == ContractStatus.draft,
            )
        )
        if existing_draft is None and job.client_id:
            draft = Contract(
                candidate_id=data.candidate_id,
                client_id=job.client_id,
                job_id=job.id,
                start_date=_date.today(),
                status=ContractStatus.draft,
            )
            db.add(draft)
            await db.flush()
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=draft.id,
                    action="auto_drafted_from_pipeline",
                    user_id=current_user.id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "stage": legacy_enum.value,
                    },
                )
            )
            staff_ids_res = await db.execute(
                select(User.id).where(
                    User.role.in_(
                        [UserRole.admin, UserRole.delivery_lead, UserRole.tac]
                    ),
                    User.is_active.is_(True),
                )
            )
            for (uid,) in staff_ids_res.all():
                db.add(
                    Notification(
                        user_id=uid,
                        title=f"Nowy draft kontraktu #{draft.id}",
                        message=(
                            f"Kandydat #{data.candidate_id} został zatrudniony "
                            f"na ofertę #{job.id}. Uzupełnij stawki i daty kontraktu."
                        ),
                        link=f"/contractors?tab=drafts",
                        notification_type=NotificationType.contract_activated,
                        related_entity_type="contract",
                        related_entity_id=draft.id,
                    )
                )

    # Automatic rejection-email scheduling (0045_rejection_emails).
    # Runs when the current move is a rejection AND the caller didn't
    # explicitly opt out. `maybe_schedule` is idempotent for non-eligible
    # moves (returns None for internal-only rejections, missing email, etc.)
    # so we can call it unconditionally when the flag allows.
    scheduled_rejection_email_id: Optional[int] = None
    if (
        legacy_enum == PipelineStage.rejected
        and data.send_rejection_email is not False
    ):
        from app.services.rejection_email_scheduler import maybe_schedule

        scheduled = await maybe_schedule(
            db,
            stage=stage,
            job=job,
            recruiter_id=job.recruiter_id,
            template_override_id=data.rejection_email_template_id,
        )
        if scheduled is not None:
            scheduled_rejection_email_id = scheduled.id

    await db.commit()
    await db.refresh(stage)
    resp = _stage_response(stage)
    resp["scheduled_rejection_email_id"] = scheduled_rejection_email_id
    return CandidateStageResponse(**resp)


@router.get("/kanban/{job_id}", response_model=KanbanView)
async def get_kanban(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Return kanban view for a job — columns driven by the job's pipeline template.

    Backward-compat: rows whose stage_def_id is NULL are bucketed by legacy enum
    via PipelineStageDef.legacy_enum_value lookup.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Latest CandidateStage row per candidate for this job
    result = await db.execute(
        select(CandidateStage)
        .where(CandidateStage.job_id == job_id)
        .order_by(CandidateStage.candidate_id, CandidateStage.moved_at.desc())
    )
    all_stages = result.scalars().all()
    seen: dict[int, CandidateStage] = {}
    for s in all_stages:
        if s.candidate_id not in seen:
            seen[s.candidate_id] = s

    # Resolve target template
    template_id = job.pipeline_template_id or await _default_template_id(db)

    if template_id is not None:
        # Template-driven columns
        stage_defs = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )

        enum_to_def: dict[str, PipelineStageDef] = {
            sd.legacy_enum_value: sd for sd in stage_defs if sd.legacy_enum_value
        }

        columns_map: dict[int, list[CandidateStage]] = {sd.id: [] for sd in stage_defs}

        for entry in seen.values():
            # Prefer explicit FK; fall back to legacy enum mapping
            if entry.stage_def_id in columns_map:
                columns_map[entry.stage_def_id].append(entry)
            else:
                mapped = enum_to_def.get(entry.stage.value) if entry.stage else None
                if mapped:
                    columns_map[mapped.id].append(entry)

        columns = []
        for sd in stage_defs:
            entries = columns_map.get(sd.id, [])
            legacy = None
            if sd.legacy_enum_value:
                try:
                    legacy = PipelineStage(sd.legacy_enum_value)
                except ValueError:
                    legacy = PipelineStage.new
            columns.append(
                KanbanColumn(
                    stage=legacy or PipelineStage.new,
                    category=sd.category,
                    count=len(entries),
                    items=[
                        CandidateStageResponse(**_stage_response(e)) for e in entries
                    ],
                    stage_def_id=sd.id,
                    name=sd.name,
                    order=sd.order,
                )
            )
        return KanbanView(job_id=job_id, columns=columns)

    # ── Legacy fallback (no template seeded yet) ──────────────────────────────
    columns_map_legacy: dict[PipelineStage, list[CandidateStage]] = {
        s: [] for s in STAGE_ORDER
    }
    columns_map_legacy[PipelineStage.rejected] = []
    columns_map_legacy[PipelineStage.withdrawn] = []
    for stage_entry in seen.values():
        if stage_entry.stage in columns_map_legacy:
            columns_map_legacy[stage_entry.stage].append(stage_entry)

    columns = []
    for stage in list(STAGE_ORDER) + [PipelineStage.rejected, PipelineStage.withdrawn]:
        entries = columns_map_legacy.get(stage, [])
        columns.append(
            KanbanColumn(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                count=len(entries),
                items=[CandidateStageResponse(**_stage_response(e)) for e in entries],
                name=STAGE_LABELS[stage],
            )
        )
    return KanbanView(job_id=job_id, columns=columns)


@router.get(
    "/history/{candidate_id}/{job_id}", response_model=List[CandidateStageResponse]
)
async def get_stage_history(
    candidate_id: int,
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Full stage history for a candidate in a specific job."""
    result = await db.execute(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id, CandidateStage.job_id == job_id
        )
        .order_by(CandidateStage.moved_at.asc())
    )
    stages = result.scalars().all()
    return [CandidateStageResponse(**_stage_response(s)) for s in stages]


# ── Champion-profile screening answers (Phase 10) ───────────────────────────


@router.get("/stages/{stage_id}/screening")
async def get_stage_screening(
    stage_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return recruiter screening answers + the job's Champion Profile."""
    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))
    return {
        "stage_id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        "champion_profile": (job.champion_profile if job else None) or {},
        "screening_answers": stage.screening_answers or None,
    }


@router.post("/stages/{stage_id}/screening")
async def submit_stage_screening(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Recruiter records answers to the Champion Profile screening questions.
    Also invalidates the (candidate, *) match score cache so the next
    recommendation read recomputes `champion_fit`.
    """
    from app.schemas.champion import ScreeningAnswers
    from app.services.match_score_cache import mark_stale_for_candidate

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    answers = ScreeningAnswers.model_validate(payload or {})
    answers.answered_at = datetime.now(timezone.utc)
    answers.answered_by = current_user.id

    stage.screening_answers = answers.model_dump(mode="json")
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="screening_answered",
            user_id=current_user.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "overall_fit": answers.overall_fit,
                "match_percent": answers.match_percent(),
            },
        )
    )
    await db.commit()

    # Mark cached scores stale — champion_fit layer depends on these answers.
    try:
        await mark_stale_for_candidate(db, stage.candidate_id)
        await db.commit()
    except Exception:
        await db.rollback()

    await db.refresh(stage)
    return {
        "stage_id": stage.id,
        "match_percent": answers.match_percent(),
        "screening_answers": stage.screening_answers,
    }


# ── Champion Card share tokens (Phase 12) ───────────────────────────────────


@router.post("/stages/{stage_id}/share-token")
async def create_share_token(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    expires_in_days: int = Query(30, ge=1, le=365),
):
    """Generate a shareable token for this CandidateStage's Champion card."""
    import secrets
    from datetime import timedelta

    from app.models.champion_share import ChampionCardShareToken

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    token = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    row = ChampionCardShareToken(
        token=token,
        candidate_stage_id=stage_id,
        created_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(row)
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage_id,
            action="champion_share_created",
            user_id=current_user.id,
            details={"expires_at": expires_at.isoformat()},
        )
    )
    await db.commit()
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "share_url_suffix": f"/share/champion-card/{token}",
    }


@router.delete("/stages/share-token/{token}")
async def revoke_share_token(
    token: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) a previously issued share token."""
    from app.models.champion_share import ChampionCardShareToken

    row = await db.scalar(
        select(ChampionCardShareToken).where(ChampionCardShareToken.token == token)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")
    row.revoked = True
    await db.commit()
    return {"status": "revoked", "token": token}


@router.get("/overview")
async def pipeline_overview(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Manager dashboard: bird's eye view across ALL jobs.
    Returns per-job stage counts + bottleneck alerts + workload per recruiter.
    """

    # Get latest stage per candidate per job
    result = await db.execute(
        select(CandidateStage).order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
        )
    )
    all_entries = result.scalars().all()

    # Deduplicate: latest stage per (candidate, job) pair
    seen_keys: set[tuple[int, int]] = set()
    latest: list[CandidateStage] = []
    for entry in all_entries:
        key = (entry.candidate_id, entry.job_id)
        if key not in seen_keys:
            seen_keys.add(key)
            latest.append(entry)

    # ── Per-job breakdown ──
    jobs_data: dict[int, dict] = {}
    for entry in latest:
        jid = entry.job_id
        if jid not in jobs_data:
            jobs_data[jid] = {"stages": {}, "total": 0}
        stage_val = entry.stage.value
        jobs_data[jid]["stages"][stage_val] = (
            jobs_data[jid]["stages"].get(stage_val, 0) + 1
        )
        jobs_data[jid]["total"] += 1

    # Fetch job titles
    job_ids = list(jobs_data.keys())
    job_titles: dict[int, str] = {}
    job_recruiters: dict[int, int | None] = {}
    if job_ids:
        jobs_result = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        for job in jobs_result.scalars().all():
            job_titles[job.id] = job.title
            job_recruiters[job.id] = job.recruiter_id

    # ── Bottleneck detection ──
    BOTTLENECK_THRESHOLD = 3  # More than 3 candidates in prep_call/screening → alert
    AGING_THRESHOLD_DAYS = 5  # Candidate stuck > 5 days → aging alert
    bottlenecks = []
    aging_alerts = []

    for entry in latest:
        days = _days_in_stage(entry.moved_at)
        if days > AGING_THRESHOLD_DAYS and entry.stage not in (
            PipelineStage.hired,
            PipelineStage.rejected,
            PipelineStage.withdrawn,
        ):
            aging_alerts.append(
                {
                    "candidate_id": entry.candidate_id,
                    "job_id": entry.job_id,
                    "stage": entry.stage.value,
                    "days": days,
                    "job_title": job_titles.get(entry.job_id, "?"),
                }
            )

    for jid, data in jobs_data.items():
        for stage_key in ["prep_call", "screening", "cv_sent"]:
            count = data["stages"].get(stage_key, 0)
            if count >= BOTTLENECK_THRESHOLD:
                bottlenecks.append(
                    {
                        "job_id": jid,
                        "job_title": job_titles.get(jid, "?"),
                        "stage": stage_key,
                        "count": count,
                        "message": f"Dużo kandydatów ({count}) czeka na {STAGE_LABELS.get(PipelineStage(stage_key), stage_key)} — potrzebna pomoc!",
                    }
                )

    # ── Workload per recruiter (by moved_by of latest entries) ──
    from app.models.user import User

    recruiter_load: dict[int, int] = {}
    for entry in latest:
        if entry.stage not in (
            PipelineStage.hired,
            PipelineStage.rejected,
            PipelineStage.withdrawn,
        ):
            rid = entry.moved_by or 0
            recruiter_load[rid] = recruiter_load.get(rid, 0) + 1

    recruiter_ids = [r for r in recruiter_load if r > 0]
    recruiter_names: dict[int, str] = {}
    if recruiter_ids:
        users_result = await db.execute(select(User).where(User.id.in_(recruiter_ids)))
        for u in users_result.scalars().all():
            recruiter_names[u.id] = u.name

    workload = [
        {
            "recruiter_id": rid,
            "name": recruiter_names.get(rid, "Nieprzypisany"),
            "active_candidates": count,
        }
        for rid, count in sorted(recruiter_load.items(), key=lambda x: -x[1])
    ]

    # ── Opportunity alerts (acceptance/negotiation → help close!) ──
    opportunities = []
    for jid, data in jobs_data.items():
        acceptance_count = data["stages"].get("acceptance", 0) + data["stages"].get(
            "negotiation", 0
        )
        if acceptance_count > 0:
            opportunities.append(
                {
                    "job_id": jid,
                    "job_title": job_titles.get(jid, "?"),
                    "count": acceptance_count,
                    "message": f"{acceptance_count} kandydat(ów) do domknięcia w {job_titles.get(jid, '?')} — manager, pomóż!",
                }
            )

    # Sort aging by days desc
    aging_alerts.sort(key=lambda x: -x["days"])

    return {
        "jobs": [
            {
                "job_id": jid,
                "title": job_titles.get(jid, "?"),
                "recruiter_id": job_recruiters.get(jid),
                "stages": data["stages"],
                "total": data["total"],
            }
            for jid, data in jobs_data.items()
        ],
        "bottlenecks": bottlenecks,
        "aging_alerts": aging_alerts[:20],  # Top 20
        "opportunities": opportunities,
        "workload": workload,
        "stage_labels": {s.value: STAGE_LABELS[s] for s in PipelineStage},
    }


class BulkMoveRequest(BaseModel):
    candidate_ids: list[int]
    job_id: int
    stage: PipelineStage
    notes: str | None = None


@router.post("/bulk-move")
async def bulk_move_candidates(
    data: BulkMoveRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move multiple candidates to a stage at once."""
    if not data.candidate_ids or not data.job_id:
        raise HTTPException(status_code=400, detail="candidate_ids and job_id required")

    moved = 0
    for cid in data.candidate_ids:
        entry = CandidateStage(
            candidate_id=cid,
            job_id=data.job_id,
            stage=data.stage,
            moved_at=datetime.now(timezone.utc),
            moved_by=current_user.id,
            notes=data.notes,
        )
        db.add(entry)
        moved += 1

    await db.commit()
    return {"moved": moved, "stage": data.stage.value, "job_id": data.job_id}
