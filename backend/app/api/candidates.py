from datetime import date, datetime, timezone
from typing import Optional
import io
import logging
import re
import zipfile
import aiofiles
import os

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.contract import Contract, ContractStatus
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.job import Job, JobStatus
from app.models.talent_pool import TalentPoolMembership
from app.models.user import User
from app.schemas.candidate import (
    CandidateCreate,
    CandidateList,
    CandidateResponse,
    CandidateUpdate,
    EmploymentInfo,
    EmploymentState,
    MatchStats,
)
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    WeightProfile,
    rank_jobs_for_candidate,
    resolve_active_profile,
    summarize_match_stats,
)
from app.services.dedup_service import find_candidate_duplicates
from app.api.deps import CurrentUser, RecruiterPlus, DeliveryLeadPlus
from app.api import ws as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class DuplicateCheckPayload(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    name: Optional[str] = None
    lastname: Optional[str] = None
    exclude_candidate_id: Optional[int] = None


def _build_response(data: dict) -> dict:
    return {"success": True, "data": data}


# Cap on how many open jobs we score per candidate when populating match stats.
# Keeps worst-case latency bounded: page_size × _MATCH_STATS_JOB_CAP score computes.
_MATCH_STATS_JOB_CAP = 50
_MATCH_STATS_DEFAULT_THRESHOLD = 50.0


def _candidate_list_options():
    """Eager-load relations required to derive employment state without N+1 lazy loads."""
    return (
        selectinload(Candidate.contracts).selectinload(Contract.client),
        selectinload(Candidate.conflicts).selectinload(CandidateConflict.client),
        selectinload(Candidate.creator),
    )


def _at_client_predicate():
    """
    Derived SQL predicate: candidate has either an active Contract OR an active
    current_employment conflict. Used to filter the candidates list.
    """
    contract_exists = (
        select(1)
        .where(
            and_(
                Contract.candidate_id == Candidate.id,
                Contract.status == ContractStatus.active,
            )
        )
        .exists()
    )
    conflict_exists = (
        select(1)
        .where(
            and_(
                CandidateConflict.candidate_id == Candidate.id,
                CandidateConflict.type == ConflictType.current_employment,
                CandidateConflict.active.is_(True),
            )
        )
        .exists()
    )
    return or_(contract_exists, conflict_exists)


def _derive_employment(candidate: Candidate) -> EmploymentInfo:
    """
    Compute EmploymentInfo from eager-loaded `contracts` + `conflicts`.
    Preference order: active Contract (source of truth) → active
    current_employment conflict (manual flag) → on_bench (has history) →
    external (never engaged).
    """
    active_contracts = [
        c for c in (candidate.contracts or []) if c.status == ContractStatus.active
    ]
    if active_contracts:
        chosen = max(
            active_contracts,
            key=lambda c: (c.end_date or date.max),
        )
        return EmploymentInfo(
            state=EmploymentState.employed_at_client,
            client_id=chosen.client_id,
            client_name=chosen.client.name if chosen.client else None,
            contract_end_date=chosen.end_date,
            source="contract",
        )

    active_conflicts = [
        cf
        for cf in (candidate.conflicts or [])
        if cf.active and cf.type == ConflictType.current_employment
    ]
    if active_conflicts:
        chosen = active_conflicts[0]
        return EmploymentInfo(
            state=EmploymentState.employed_at_client,
            client_id=chosen.client_id,
            client_name=chosen.client.name if chosen.client else None,
            contract_end_date=None,
            source="conflict",
        )

    has_history = bool(candidate.contracts) or any(
        cf.type == ConflictType.current_employment for cf in (candidate.conflicts or [])
    )
    if has_history:
        return EmploymentInfo(state=EmploymentState.on_bench, source="none")
    return EmploymentInfo(state=EmploymentState.external, source="none")


@router.get("", response_model=CandidateList)
async def list_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[CandidateStatus] = None,
    location: Optional[str] = None,
    q: Optional[str] = None,
    skills: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by canonical skill names (resolved against the alias taxonomy "
            "on the scoring engine). Multiple values combined by `skill_combine`."
        ),
    ),
    skill_combine: str = Query(
        "and",
        pattern="^(and|or)$",
        description="How to combine multiple `skills` filters — 'and' or 'or'.",
    ),
    remote_policy: Optional[str] = Query(
        None,
        description="Filter by candidate remote preference (remote/hybrid/onsite).",
    ),
    min_salary: Optional[int] = Query(
        None,
        ge=0,
        description="Minimum salary expectation (PLN) — exclusive of nulls.",
    ),
    max_salary: Optional[int] = Query(
        None,
        ge=0,
        description="Maximum salary expectation (PLN) — exclusive of nulls.",
    ),
    include_match_stats: bool = Query(
        False,
        description=(
            "When true, each candidate gets a `match_stats` summary with the number "
            "of open jobs they match (score ≥ threshold) and their top match score. "
            "O(page_size × open_jobs) scoring work — enable lazily on the UI."
        ),
    ),
    match_threshold: float = Query(
        _MATCH_STATS_DEFAULT_THRESHOLD,
        ge=0.0,
        le=100.0,
        description="Minimum total score (0-100) to count an open job as matching.",
    ),
    profile_id: Optional[int] = Query(
        None,
        description="Phase D1 scoring weight profile id. None = auto-resolve by user.",
    ),
    employment: Optional[str] = Query(
        None,
        pattern="^(at_client|available)$",
        description=(
            "Derived employment filter: 'at_client' = consultant is employed at one "
            "of our clients (active contract OR active current_employment conflict); "
            "'available' = the inverse (on bench or external). None = no filter."
        ),
    ),
    availability: Optional[AvailabilityStatus] = Query(
        None,
        description=(
            "Filter by `availability_status` — actively_looking / open_to_offers / "
            "not_looking / unknown."
        ),
    ),
    added_by_user_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by `created_by` — one or more user ids. "
            "Sentinel `0` matches NULL (pre-backfill / system-imported rows)."
        ),
    ),
    talent_pool_id: Optional[list[int]] = Query(
        None,
        description=(
            "Filter by talent pool membership — one or more pool ids, OR-combined."
        ),
    ),
):
    query = select(Candidate).options(*_candidate_list_options())
    if status:
        query = query.where(Candidate.status == status)
    if employment == "at_client":
        query = query.where(_at_client_predicate())
    elif employment == "available":
        query = query.where(not_(_at_client_predicate()))
    if availability:
        query = query.where(Candidate.availability_status == availability)
    if location:
        query = query.where(Candidate.location.ilike(f"%{location}%"))
    if q:
        q_stripped = q.strip()
        # Phase B2: for longer queries use pg_trgm similarity over name+lastname+email
        # + raw_cv_text; fall back to ilike for 1-2 char queries where trigram
        # similarity is noisy.
        if len(q_stripped) >= 3:
            identity_expr = (
                func.coalesce(Candidate.name, "")
                + " "
                + func.coalesce(Candidate.lastname, "")
                + " "
                + func.coalesce(Candidate.email, "")
            )
            like_pat = f"%{q_stripped}%"
            # `func.similarity(a, q) > 0.2` uses the GIN trigram index on the
            # expression; robust against typos and case mismatches. Also keep
            # raw ilike on raw_cv_text (index-backed via ix_candidates_cv_trgm).
            query = query.where(
                or_(
                    func.similarity(identity_expr, q_stripped) > 0.2,
                    Candidate.raw_cv_text.ilike(like_pat),
                    Candidate.name.ilike(like_pat),
                    Candidate.lastname.ilike(like_pat),
                    Candidate.email.ilike(like_pat),
                )
            )
        else:
            like_pat = f"%{q_stripped}%"
            query = query.where(
                or_(
                    Candidate.name.ilike(like_pat),
                    Candidate.lastname.ilike(like_pat),
                    Candidate.email.ilike(like_pat),
                )
            )
    # Phase B3: structured filters over JSONB
    if skills:
        # skills is a list of canonical/alias names; normalize through the
        # scoring engine so UI can ship whatever the user typed.
        from app.services.scoring_service import canonical_skill_names

        wanted = [s for s in (canonical_skill_names(skills) or []) if s]
        if wanted:
            # Case-insensitive text LIKE on the JSONB payload — handles both
            # shapes the seed data ships with:
            #   [{"name": "Python"}, ...]             → matches "name": "python"
            #   {"technologies": ["Python", ...]}     → matches "python"
            # Also checks tags + verified_tech for a generous match.
            def _skill_predicate(s: str):
                pat = f"%{s.lower()}%"
                return or_(
                    func.lower(
                        Candidate.skills.cast(__import__("sqlalchemy").Text)
                    ).like(pat),
                    func.lower(
                        Candidate.verified_tech.cast(__import__("sqlalchemy").Text)
                    ).like(pat),
                    func.lower(Candidate.tags.cast(__import__("sqlalchemy").Text)).like(
                        pat
                    ),
                )

            skill_clauses = [_skill_predicate(s) for s in wanted]
            combiner = __import__("sqlalchemy").and_ if skill_combine == "and" else or_
            query = query.where(combiner(*skill_clauses))

    if remote_policy:
        # Stored inside `preferences.remote_modes` JSON array
        query = query.where(
            Candidate.preferences.op("@>")(
                func.jsonb_build_object(
                    "remote_modes", func.jsonb_build_array(remote_policy)
                )
            )
        )

    if min_salary is not None:
        query = query.where(Candidate.salary_expectation >= min_salary)
    if max_salary is not None:
        query = query.where(Candidate.salary_expectation <= max_salary)

    if added_by_user_id:
        # Sentinel 0 = "no created_by on record" (pre-backfill / system import).
        real_ids = [uid for uid in added_by_user_id if uid != 0]
        include_null = 0 in added_by_user_id
        if include_null and real_ids:
            query = query.where(
                or_(Candidate.created_by.is_(None), Candidate.created_by.in_(real_ids))
            )
        elif include_null:
            query = query.where(Candidate.created_by.is_(None))
        elif real_ids:
            query = query.where(Candidate.created_by.in_(real_ids))

    if talent_pool_id:
        pool_exists = (
            select(1)
            .where(
                and_(
                    TalentPoolMembership.candidate_id == Candidate.id,
                    TalentPoolMembership.talent_pool_id.in_(talent_pool_id),
                )
            )
            .exists()
        )
        query = query.where(pool_exists)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    # Phase D1: resolve which weight profile to use for the match-stats column.
    profile: WeightProfile = DEFAULT_PROFILE
    if include_match_stats and items:
        if profile_id is not None:
            from app.models.scoring_weight_profile import ScoringWeightProfile

            row = await db.scalar(
                select(ScoringWeightProfile).where(
                    ScoringWeightProfile.id == profile_id
                )
            )
            if row:
                profile = WeightProfile.from_record(row)
        else:
            profile = await resolve_active_profile(db, user_id=current_user.id)

    match_stats_by_candidate: dict[int, MatchStats] = {}
    if include_match_stats and items:
        open_jobs_stmt = (
            select(Job)
            .where(Job.status == JobStatus.published)
            .limit(_MATCH_STATS_JOB_CAP)
        )
        open_jobs = list((await db.execute(open_jobs_stmt)).scalars().all())
        total_open = len(open_jobs)
        if total_open:
            for cand in items:
                breakdowns = await rank_jobs_for_candidate(
                    cand, open_jobs, db, profile=profile
                )
                stats = summarize_match_stats(
                    breakdowns, total_open=total_open, min_score=match_threshold
                )
                match_stats_by_candidate[cand.id] = MatchStats(**stats)
        else:
            zero = MatchStats(open_count=0, total_open=0, top_score=0.0)
            for cand in items:
                match_stats_by_candidate[cand.id] = zero

    response_items: list[CandidateResponse] = []
    for cand in items:
        payload = CandidateResponse.model_validate(cand)
        updates: dict = {"employment": _derive_employment(cand)}
        stats = match_stats_by_candidate.get(cand.id)
        if stats is not None:
            updates["match_stats"] = stats
        payload = payload.model_copy(update=updates)
        response_items.append(payload)

    return CandidateList(
        items=response_items, total=total, page=page, page_size=page_size
    )


# ── Bulk export (Phase 7b.4) ────────────────────────────────────────────────


_EXPORT_COLUMNS = [
    "id",
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "competence_category",
    "years_it_experience",
    "skills",
    "tags",
    "status",
    "source",
    "salary_expectation",
    "salary_currency",
    "availability_date",
    "champion",
    "created_at",
]


def _skill_names_flat(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, list):
        out: list[str] = []
        for it in raw:
            if isinstance(it, dict):
                v = it.get("name")
                if v:
                    out.append(str(v))
            elif isinstance(it, str):
                out.append(it)
        return ", ".join(out)
    return str(raw)


def _row_for_export(c: Candidate) -> list:
    return [
        c.id,
        c.name or "",
        c.lastname or "",
        c.email or "",
        c.phone or "",
        c.location or "",
        c.competence_category or "",
        c.years_it_experience if c.years_it_experience is not None else "",
        _skill_names_flat(c.skills),
        _skill_names_flat(c.tags),
        c.status.value if c.status else "",
        c.source or "",
        c.salary_expectation if c.salary_expectation is not None else "",
        c.salary_currency or "",
        c.availability_date.isoformat() if c.availability_date else "",
        "true" if c.champion else "false",
        c.created_at.isoformat() if c.created_at else "",
    ]


@router.get("/export")
async def export_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("csv", regex="^(csv|xlsx)$"),
    status_: Optional[CandidateStatus] = Query(None, alias="status"),
    q: Optional[str] = None,
    location: Optional[str] = None,
    limit: int = Query(10000, ge=1, le=50000),
):
    """Stream candidates as CSV or Excel file respecting the same filters as list."""
    query = select(Candidate)
    if status_:
        query = query.where(Candidate.status == status_)
    if location:
        query = query.where(Candidate.location.ilike(f"%{location}%"))
    if q:
        query = query.where(
            or_(
                Candidate.name.ilike(f"%{q}%"),
                Candidate.lastname.ilike(f"%{q}%"),
                Candidate.email.ilike(f"%{q}%"),
            )
        )
    query = query.order_by(Candidate.id).limit(limit)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "xlsx":
        from io import BytesIO
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Candidates"
        ws.append(_EXPORT_COLUMNS)
        for c in rows:
            ws.append(_row_for_export(c))

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"candidates_{ts}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV (default)
    import csv
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_EXPORT_COLUMNS)
    for c in rows:
        writer.writerow(_row_for_export(c))
    buf.seek(0)
    filename = f"candidates_{ts}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    data: CandidateCreate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    candidate = Candidate(**data.model_dump())
    candidate.created_by = current_user.id
    db.add(candidate)
    await db.flush()
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate.id,
        action="created",
        user_id=current_user.id,
        details={"name": f"{candidate.name} {candidate.lastname}"},
    )
    db.add(activity)
    user_activity = UserActivity(
        user_id=current_user.id,
        action_type=UserActionType.candidate_added,
        entity_type="candidate",
        entity_id=candidate.id,
        details={
            "name": f"{candidate.name} {candidate.lastname}",
            "source": candidate.source,
        },
    )
    db.add(user_activity)
    await db.flush()

    # Notify all managers/admins about new candidate (real-time)
    managers_result = await db.execute(
        select(User).where(User.is_active, User.role.in_(["admin", "manager"]))
    )
    managers = managers_result.scalars().all()
    notif_ids = []
    for mgr in managers:
        if mgr.id != current_user.id:
            notif = Notification(
                user_id=mgr.id,
                title="Nowy kandydat dodany",
                message=f"Kandydat {candidate.name} {candidate.lastname} został dodany do systemu.",
                link=f"/candidates/{candidate.id}",
                notification_type=NotificationType.candidate_added,
            )
            db.add(notif)
            notif_ids.append((mgr.id, notif))
    await db.flush()
    for mgr_id, notif in notif_ids:
        await ws_manager.notify_user(
            mgr_id,
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

    await db.refresh(candidate)
    # Reload with eager-loaded contracts/conflicts so _derive_employment has data.
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()
    payload = CandidateResponse.model_validate(full)
    return payload.model_copy(update={"employment": _derive_employment(full)})


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    payload = CandidateResponse.model_validate(candidate)
    return payload.model_copy(update={"employment": _derive_employment(candidate)})


@router.get("/{candidate_id}/timeline")
async def get_candidate_timeline(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Chronological feed of all activities for this candidate:
    notes, stage changes, calls, system events.
    GET /api/candidates/{id}/timeline
    """
    # Check candidate exists
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    timeline = []

    # Notes
    notes_result = await db.execute(
        select(Note)
        .where(Note.candidate_id == candidate_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    notes = notes_result.scalars().all()
    for note in notes:
        timeline.append(
            {
                "type": "note",
                "id": note.id,
                "timestamp": note.created_at.isoformat() if note.created_at else None,
                "note_type": note.note_type.value if note.note_type else None,
                "content": note.content,
                "author_id": note.author_id,
            }
        )

    # Stage changes
    stages_result = await db.execute(
        select(CandidateStage, Job.title)
        .join(Job, CandidateStage.job_id == Job.id)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
        .limit(limit)
    )
    for stage, job_title in stages_result.all():
        timeline.append(
            {
                "type": "stage_change",
                "id": stage.id,
                "timestamp": stage.moved_at.isoformat() if stage.moved_at else None,
                "stage": stage.stage.value,
                "job_id": stage.job_id,
                "job_title": job_title,
                "moved_by": stage.moved_by,
                "rating": stage.rating,
                "notes": stage.notes,
            }
        )

    # Activities (system events)
    activities_result = await db.execute(
        select(Activity)
        .where(Activity.entity_type == "candidate", Activity.entity_id == candidate_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    for act in activities_result.scalars().all():
        timeline.append(
            {
                "type": "activity",
                "id": act.id,
                "timestamp": act.created_at.isoformat() if act.created_at else None,
                "action": act.action,
                "user_id": act.user_id,
                "details": act.details,
            }
        )

    # User activities
    user_acts_result = await db.execute(
        select(UserActivity)
        .where(
            UserActivity.entity_type == "candidate",
            UserActivity.entity_id == candidate_id,
        )
        .order_by(UserActivity.created_at.desc())
        .limit(limit)
    )
    for ua in user_acts_result.scalars().all():
        timeline.append(
            {
                "type": "user_activity",
                "id": ua.id,
                "timestamp": ua.created_at.isoformat() if ua.created_at else None,
                "action_type": ua.action_type.value,
                "user_id": ua.user_id,
                "details": ua.details,
            }
        )

    # Sort chronologically (newest first)
    timeline.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "count": len(timeline),
        "timeline": timeline[:limit],
    }


@router.get("/{candidate_id}/history")
async def get_candidate_history(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Recruitment history — which jobs this candidate was in and what stages reached.
    GET /api/candidates/{id}/history
    """
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    stages_result = await db.execute(
        select(CandidateStage, Job.title, Job.status.label("job_status"))
        .join(Job, CandidateStage.job_id == Job.id)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
    )

    # Group by job
    jobs_map: dict = {}
    for stage, job_title, job_status in stages_result.all():
        job_id = stage.job_id
        if job_id not in jobs_map:
            jobs_map[job_id] = {
                "job_id": job_id,
                "job_title": job_title,
                "job_status": job_status,
                "stages": [],
                "latest_stage": None,
                "first_seen": None,
                "last_seen": None,
            }
        entry = jobs_map[job_id]
        entry["stages"].append(
            {
                "stage": stage.stage.value,
                "moved_at": stage.moved_at.isoformat() if stage.moved_at else None,
                "rating": stage.rating,
                "notes": stage.notes,
            }
        )
        # Track dates
        moved_at = stage.moved_at.isoformat() if stage.moved_at else None
        if moved_at:
            if not entry["first_seen"] or moved_at < entry["first_seen"]:
                entry["first_seen"] = moved_at
            if not entry["last_seen"] or moved_at > entry["last_seen"]:
                entry["last_seen"] = moved_at
                entry["latest_stage"] = stage.stage.value

    # Contracts
    from app.models.contract import Contract
    from app.models.client import Client

    contracts_result = await db.execute(
        select(Contract, Client.name.label("client_name"))
        .join(Client, Contract.client_id == Client.id)
        .where(Contract.candidate_id == candidate_id)
        .order_by(Contract.start_date.desc())
    )
    contracts_history = []
    for contract, client_name in contracts_result.all():
        contracts_history.append(
            {
                "contract_id": contract.id,
                "client_name": client_name,
                "start_date": contract.start_date.isoformat()
                if contract.start_date
                else None,
                "end_date": contract.end_date.isoformat()
                if contract.end_date
                else None,
                "status": contract.status.value,
                "rate_candidate": contract.rate_candidate,
                "rate_client": contract.rate_client,
                "currency": contract.currency,
            }
        )

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "jobs": list(jobs_map.values()),
        "contracts": contracts_history,
    }


# Fields that change the scoring inputs — mutating them invalidates cache entries.
_MATCH_CACHE_INVALIDATING_FIELDS = frozenset(
    {
        "skills",
        "verified_tech",
        "tags",
        "salary_expectation",
        "availability_date",
        "preferences",
        "location",
        "status",
    }
)


@router.patch("/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: int,
    data: CandidateUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updates = data.model_dump(exclude_unset=True)

    # Phase D4: flag manual edits to `experience` so a subsequent CV upload
    # does not silently overwrite recruiter-curated data with AI extraction.
    if "experience" in updates:
        current_extracted = dict(candidate.cv_extracted_data or {})
        current_extracted["_manual_override_experience"] = True
        updates["cv_extracted_data"] = current_extracted

    for field, value in updates.items():
        setattr(candidate, field, value)
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate.id,
        action="updated",
        user_id=current_user.id,
        details=updates,
    )
    db.add(activity)

    # Phase C1: invalidate cached (candidate, *) scores if matching-critical
    # fields changed. Cheap single UPDATE — much faster than refetching scores.
    if _MATCH_CACHE_INVALIDATING_FIELDS & set(updates.keys()):
        from app.services.match_score_cache import mark_stale_for_candidate

        await mark_stale_for_candidate(db, candidate.id)

    # Async SQLAlchemy doesn't autoflush before `refresh`, so setattr changes
    # could get overwritten by the in-memory state read. Flush first, then
    # reload with eager-loaded relations so `_derive_employment` sees current
    # contracts/conflicts.
    await db.flush()
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate.id)
    )
    full = reloaded.scalar_one()
    payload = CandidateResponse.model_validate(full)
    return payload.model_copy(update={"employment": _derive_employment(full)})


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate_id,
        action="deleted",
        user_id=current_user.id,
    )
    db.add(activity)
    await db.delete(candidate)


def _apply_cv_enrichment(candidate: Candidate, parsed: dict) -> int:
    """Pure function: mutate `candidate` fields from a `parse_cv()` result.

    Returns the number of companies that were written into `experience`
    (zero when the recruiter has manually curated it, or the AI returned no
    companies). This function is the unit-testable seam for Phase D4 — it
    has zero DB or async concerns.

    Contract:
      * Never clobbers recruiter-curated data (`_manual_override_experience`).
      * Never downgrades a rich `experience` record (with roles) to a flat
        company-name list — bulk imports from Traffit are protected.
      * Preserves the manual-override flag across writes so the guard
        survives future uploads.
    """
    existing_extracted = dict(candidate.cv_extracted_data or {})
    manual_override = bool(
        existing_extracted.get("_manual_override_experience", False)
    )

    if parsed.get("years_it_experience") is not None:
        candidate.years_it_experience = parsed["years_it_experience"]
    if parsed.get("skills"):
        candidate.skills = parsed["skills"]
    if parsed.get("education"):
        candidate.education = parsed["education"]
    if parsed.get("languages"):
        candidate.languages = parsed["languages"]
    if parsed.get("career_summary"):
        candidate.ai_summary = parsed["career_summary"]

    next_extracted = dict(parsed)
    if manual_override:
        next_extracted["_manual_override_experience"] = True
    candidate.cv_extracted_data = next_extracted

    companies = parsed.get("companies") or []
    has_rich_experience = bool(candidate.experience) and any(
        isinstance(e, dict) and e.get("role")
        for e in (candidate.experience or [])
    )
    written = 0
    if companies and not manual_override and not has_rich_experience:
        candidate.experience = [
            {
                "company": name,
                "role": None,
                "start": None,
                "end": None,
                "desc": None,
            }
            for name in companies
        ]
        written = len(companies)

    candidate.cv_parsed_at = datetime.now(timezone.utc)
    return written


async def _enrich_candidate_cv_task(candidate_id: int) -> None:
    """Background task: parse `raw_cv_text` and fan out to candidate fields.

    Runs with a fresh DB session because FastAPI's per-request session is
    closed once the response is returned. Never raises — every failure is
    logged and the upload response stays successful.
    """
    from app.core.database import AsyncSessionLocal
    from app.services.cv_parser import parse_cv
    from app.services.match_score_cache import mark_stale_for_candidate

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            candidate = result.scalar_one_or_none()
            if not candidate or not candidate.raw_cv_text:
                return

            parsed = await parse_cv(candidate.raw_cv_text)
            written = _apply_cv_enrichment(candidate, parsed)
            await db.commit()

            await mark_stale_for_candidate(db, candidate_id)
            await db.commit()

            logger.info(
                "[cv_enrich] source=%s candidate=%s companies_written=%d",
                parsed.get("_source"),
                candidate_id,
                written,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                f"[cv_enrich] failed for candidate {candidate_id}: {e}"
            )
            await db.rollback()


@router.post("/{candidate_id}/cv", response_model=CandidateResponse)
async def upload_cv(
    candidate_id: int,
    current_user: RecruiterPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Upload CV file for a candidate.

    Saves the file, extracts text (PDF/DOCX/TXT) into `raw_cv_text`, and
    schedules an async enrichment task that populates AI summary, companies
    and skill facts in the background. Response returns as soon as the file
    is on disk — callers don't block on the LLM.
    """
    import asyncio

    from app.services import cv_text_extractor

    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{file.filename}"
    )
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Phase D4: extract text from PDF/DOCX/TXT so the enrichment task has
    # something to work with. Heavy libraries run in a thread to keep the
    # event loop responsive.
    try:
        raw_text = await asyncio.to_thread(
            cv_text_extractor.extract_text, file_path, file.filename or ""
        )
        if raw_text:
            candidate.raw_cv_text = raw_text
    except cv_text_extractor.UnsupportedCvFormat as e:
        logger.info(f"[CV upload] unsupported format for {candidate_id}: {e}")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[CV upload] text extraction failed for candidate {candidate_id}: {e}"
        )

    candidate.cv_filename = file.filename
    activity = Activity(
        entity_type="candidate",
        entity_id=candidate_id,
        action="cv_uploaded",
        user_id=current_user.id,
        details={"filename": file.filename},
    )
    db.add(activity)
    user_activity = UserActivity(
        user_id=current_user.id,
        action_type=UserActionType.cv_uploaded,
        entity_type="candidate",
        entity_id=candidate_id,
        details={"filename": file.filename},
    )
    db.add(user_activity)
    await db.commit()
    await db.refresh(candidate)

    # Phase 1: auto-embed candidate after CV upload.
    # Non-blocking — CV is already saved; embedding failures are logged but not raised.
    try:
        from app.services.embedding_service import embed_candidate

        await embed_candidate(candidate_id, db)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            f"[CV upload] embedding failed for candidate {candidate_id}: {e}"
        )

    # Phase D4: schedule AI enrichment off the request path. Task runs in a
    # fresh DB session so it survives the response lifecycle.
    if candidate.raw_cv_text:
        background_tasks.add_task(_enrich_candidate_cv_task, candidate_id)

    # Re-fetch with eager-loaded relations so CandidateResponse can build
    # the derived `employment` field; upload_cv used to return the bare
    # Candidate, which tripped the response schema when strict validation
    # was introduced.
    reloaded = await db.execute(
        select(Candidate)
        .options(*_candidate_list_options())
        .where(Candidate.id == candidate_id)
    )
    full = reloaded.scalar_one()
    payload = CandidateResponse.model_validate(full)
    return payload.model_copy(update={"employment": _derive_employment(full)})


@router.get("/{candidate_id}/cv-download")
async def download_cv(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Download CV file for a candidate."""
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not candidate.cv_filename:
        raise HTTPException(status_code=404, detail="No CV uploaded for this candidate")
    file_path = os.path.join(
        settings.UPLOAD_DIR, f"candidate_{candidate_id}_{candidate.cv_filename}"
    )
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="CV file not found on disk")
    return FileResponse(
        path=file_path,
        filename=candidate.cv_filename,
        media_type="application/octet-stream",
    )


class BulkCvDownloadRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=200)


_FILENAME_UNSAFE_RE = re.compile(r"[^\w\-. ]", re.UNICODE)


def _sanitize_zip_component(value: str) -> str:
    cleaned = _FILENAME_UNSAFE_RE.sub("_", (value or "").strip())
    cleaned = cleaned.replace("..", "_")
    return cleaned[:200] or "_"


@router.post("/bulk-cv-download")
async def bulk_cv_download(
    payload: BulkCvDownloadRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download multiple candidate CVs as a single ZIP archive.

    Skips candidates without an uploaded CV or missing file on disk and reports
    them in the `_manifest.txt` entry included at the archive root.
    """
    requested_ids = list(dict.fromkeys(payload.candidate_ids))

    result = await db.execute(
        select(Candidate).where(Candidate.id.in_(requested_ids))
    )
    candidates_by_id = {c.id: c for c in result.scalars().all()}

    manifest_rows: list[str] = ["id\tfirst\tlast\tcv_filename\tstatus"]
    included = 0
    skipped = 0

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for cid in requested_ids:
            candidate = candidates_by_id.get(cid)
            if candidate is None:
                manifest_rows.append(f"{cid}\t\t\t\tskipped_not_found")
                skipped += 1
                continue
            if not candidate.cv_filename:
                manifest_rows.append(
                    f"{cid}\t{candidate.name}\t{candidate.lastname}\t\tskipped_no_cv"
                )
                skipped += 1
                continue

            file_path = os.path.join(
                settings.UPLOAD_DIR,
                f"candidate_{candidate.id}_{candidate.cv_filename}",
            )
            data: bytes | None = None
            if os.path.exists(file_path):
                try:
                    async with aiofiles.open(file_path, "rb") as f:
                        data = await f.read()
                except OSError as err:
                    logger.warning(
                        "bulk_cv_download: failed to read %s: %s", file_path, err
                    )
            elif candidate.cv_file_content:
                data = candidate.cv_file_content

            if data is None:
                manifest_rows.append(
                    f"{cid}\t{candidate.name}\t{candidate.lastname}\t"
                    f"{candidate.cv_filename}\tskipped_file_missing"
                )
                skipped += 1
                continue

            ext = os.path.splitext(candidate.cv_filename)[1] or ".pdf"
            entry_name = (
                f"{_sanitize_zip_component(candidate.lastname)}_"
                f"{_sanitize_zip_component(candidate.name)}_"
                f"{candidate.id}{ext}"
            )
            zf.writestr(entry_name, data)
            manifest_rows.append(
                f"{cid}\t{candidate.name}\t{candidate.lastname}\t"
                f"{candidate.cv_filename}\tincluded"
            )
            included += 1

        zf.writestr("_manifest.txt", "\n".join(manifest_rows) + "\n")

    archive_name = f"nexus-cvs-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{archive_name}"',
        "X-Included-Count": str(included),
        "X-Skipped-Count": str(skipped),
        "Access-Control-Expose-Headers": "Content-Disposition, X-Included-Count, X-Skipped-Count",
    }
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers=headers,
    )


@router.post("/bulk-import", status_code=status.HTTP_201_CREATED)
async def bulk_import_candidates(
    data: list[CandidateCreate],
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Import multiple candidates at once."""
    created = []
    for item in data:
        candidate = Candidate(**item.model_dump())
        candidate.created_by = current_user.id
        db.add(candidate)
        await db.flush()
        created.append(candidate.id)
        user_activity = UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.candidate_added,
            entity_type="candidate",
            entity_id=candidate.id,
            details={"name": f"{candidate.name} {candidate.lastname}", "bulk": True},
        )
        db.add(user_activity)
    activity = Activity(
        entity_type="candidate",
        entity_id=0,
        action="bulk_import",
        user_id=current_user.id,
        details={"count": len(created), "ids": created},
    )
    db.add(activity)
    return {"created": len(created), "ids": created}


@router.post("/check-duplicates")
async def check_duplicates(
    payload: DuplicateCheckPayload,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Return candidates matching the provided identifiers (email/phone/linkedin/name+lastname).

    Non-blocking — the API does not reject on duplicates. Callers (UI import modals,
    create/update flows) decide how to react. Used for duplicate-warning banners.
    """
    return await find_candidate_duplicates(
        db,
        email=payload.email,
        phone=payload.phone,
        linkedin=payload.linkedin,
        name=payload.name,
        lastname=payload.lastname,
        exclude_candidate_id=payload.exclude_candidate_id,
    )
