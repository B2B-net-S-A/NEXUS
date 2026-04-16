from datetime import datetime, timezone
from typing import Optional
import logging
import aiofiles
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.job import Job
from app.models.user import User
from app.schemas.candidate import (
    CandidateCreate,
    CandidateList,
    CandidateResponse,
    CandidateUpdate,
)
from app.services.dedup_service import find_candidate_duplicates
from app.api.deps import CurrentUser
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


@router.get("", response_model=CandidateList)
async def list_candidates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[CandidateStatus] = None,
    location: Optional[str] = None,
    q: Optional[str] = None,
):
    query = select(Candidate)
    if status:
        query = query.where(Candidate.status == status)
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
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()
    return CandidateList(items=list(items), total=total, page=page, page_size=page_size)


@router.post("", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    data: CandidateCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    candidate = Candidate(**data.model_dump())
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
    return candidate


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


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


@router.patch("/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: int,
    data: CandidateUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updates = data.model_dump(exclude_unset=True)
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
    await db.refresh(candidate)
    return candidate


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
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


@router.post("/{candidate_id}/cv", response_model=CandidateResponse)
async def upload_cv(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Upload CV file for a candidate. Stores file, records filename."""
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

    return candidate


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


@router.post("/bulk-import", status_code=status.HTTP_201_CREATED)
async def bulk_import_candidates(
    data: list[CandidateCreate],
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Import multiple candidates at once."""
    created = []
    for item in data:
        candidate = Candidate(**item.model_dump())
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
