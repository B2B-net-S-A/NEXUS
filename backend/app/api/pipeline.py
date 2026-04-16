from datetime import datetime, timezone
from pydantic import BaseModel
from typing import List

from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas.pipeline import (
    CandidateStageResponse,
    KanbanColumn,
    KanbanView,
    StageMove,
    StageInfo,
    STAGE_LABELS,
)
from app.api.deps import CurrentUser
from app.api import ws as ws_manager

router = APIRouter()


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
        "moved_at": stage.moved_at,
        "moved_by": stage.moved_by,
        "notes": stage.notes,
        "rating": stage.rating,
        "created_at": stage.created_at,
        "days_in_stage": _days_in_stage(stage.moved_at),
    }


@router.get("/stages", response_model=List[StageInfo])
async def list_stages(current_user: CurrentUser):
    """Return all pipeline stages with labels, categories, and order."""
    result = []
    for i, stage in enumerate(STAGE_ORDER):
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=i,
            )
        )
    # Add terminal stages
    for stage in [PipelineStage.rejected, PipelineStage.withdrawn]:
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=99,
            )
        )
    return result


@router.post("/move", response_model=CandidateStageResponse)
async def move_candidate(
    data: StageMove,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Move a candidate to a new pipeline stage for a given job."""
    stage = CandidateStage(
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=data.stage,
        moved_at=datetime.now(timezone.utc),
        moved_by=current_user.id,
        notes=data.notes,
        rating=data.rating,
    )
    db.add(stage)
    await db.flush()

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
                "stage": data.stage.value,
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
                "stage": data.stage.value,
            },
        )
    )

    # Notification for the recruiter assigned to the job (if different from current user)
    job_result = await db.execute(select(Job).where(Job.id == data.job_id))
    job = job_result.scalar_one_or_none()
    if job and job.recruiter_id and job.recruiter_id != current_user.id:
        notif = Notification(
            user_id=job.recruiter_id,
            title="Zmiana etapu kandydata",
            message=f"Kandydat #{data.candidate_id} → '{STAGE_LABELS.get(data.stage, data.stage.value)}' w ofercie #{data.job_id}.",
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

    await db.commit()
    await db.refresh(stage)
    resp = _stage_response(stage)
    return CandidateStageResponse(**resp)


@router.get("/kanban/{job_id}", response_model=KanbanView)
async def get_kanban(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return kanban view: all stages with latest candidate stage entries."""
    result = await db.execute(
        select(CandidateStage)
        .where(CandidateStage.job_id == job_id)
        .order_by(CandidateStage.candidate_id, CandidateStage.moved_at.desc())
    )
    all_stages = result.scalars().all()

    # Deduplicate: keep latest stage per candidate
    seen = {}
    for s in all_stages:
        if s.candidate_id not in seen:
            seen[s.candidate_id] = s

    # Group by stage (ordered)
    columns_map: dict[PipelineStage, list[CandidateStage]] = {
        s: [] for s in STAGE_ORDER
    }
    # Add terminal stages
    columns_map[PipelineStage.rejected] = []
    columns_map[PipelineStage.withdrawn] = []

    for stage_entry in seen.values():
        if stage_entry.stage in columns_map:
            columns_map[stage_entry.stage].append(stage_entry)

    columns = []
    for stage in list(STAGE_ORDER) + [PipelineStage.rejected, PipelineStage.withdrawn]:
        entries = columns_map.get(stage, [])
        columns.append(
            KanbanColumn(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                count=len(entries),
                items=[CandidateStageResponse(**_stage_response(e)) for e in entries],
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
    current_user: CurrentUser,
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
