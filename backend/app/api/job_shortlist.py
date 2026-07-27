"""Job shortlist API (SEARCH-P1-05).

A pre-pipeline evaluation list per job. Recruiters add candidates from search,
track evaluation + outreach status, then promote approved entries into the
pipeline (promotion lands in a follow-up). Updates use optimistic locking:
the client echoes the ``version`` it read and a stale PATCH 409s.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.proposals_bulk import _resolve_initial_stage
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job
from app.models.job_shortlist import JobShortlistEntry
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.schemas.job_shortlist import (
    ShortlistAddRequest,
    ShortlistAddResponse,
    ShortlistEntryResponse,
    ShortlistPromoteResponse,
    ShortlistUpdateRequest,
)
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityInput,
    EligibilityReason,
    evaluate_eligibility,
    extract_excluded_client_ids,
)
from app.services.hiring_manager_verdicts import load_manager_rejections

router = APIRouter()


def _to_response(
    entry: JobShortlistEntry,
    name: Optional[str] = None,
    lastname: Optional[str] = None,
) -> ShortlistEntryResponse:
    resp = ShortlistEntryResponse.model_validate(entry)
    resp.candidate_name = name
    resp.candidate_lastname = lastname
    return resp


@router.post(
    "/jobs/{job_id}/shortlist",
    response_model=ShortlistAddResponse,
    summary="Add candidates to a job's shortlist",
)
async def add_to_shortlist(
    job_id: int,
    body: ShortlistAddRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistAddResponse:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    valid = set(
        (
            await db.execute(
                select(Candidate.id).where(Candidate.id.in_(body.candidate_ids))
            )
        )
        .scalars()
        .all()
    )
    already = set(
        (
            await db.execute(
                select(JobShortlistEntry.candidate_id).where(
                    JobShortlistEntry.job_id == job_id,
                    JobShortlistEntry.candidate_id.in_(body.candidate_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    added: list[int] = []
    skipped: list[int] = []
    seen: set[int] = set()
    for cid in body.candidate_ids:
        if cid in seen:
            continue
        seen.add(cid)
        if cid not in valid or cid in already:
            skipped.append(cid)
            continue
        db.add(
            JobShortlistEntry(
                job_id=job_id,
                candidate_id=cid,
                note=body.note,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )
        added.append(cid)

    await db.commit()
    return ShortlistAddResponse(
        added=added,
        skipped=skipped,
        total_added=len(added),
        total_skipped=len(skipped),
    )


@router.get(
    "/jobs/{job_id}/shortlist",
    response_model=list[ShortlistEntryResponse],
    summary="List a job's shortlist",
)
async def list_shortlist(
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> list[ShortlistEntryResponse]:
    rows = (
        await db.execute(
            select(JobShortlistEntry, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == JobShortlistEntry.candidate_id)
            .where(JobShortlistEntry.job_id == job_id)
            .order_by(JobShortlistEntry.created_at.desc())
        )
    ).all()
    return [_to_response(entry, name, lastname) for entry, name, lastname in rows]


@router.patch(
    "/shortlist/{entry_id}",
    response_model=ShortlistEntryResponse,
    summary="Update a shortlist entry (optimistic-locked)",
)
async def update_shortlist_entry(
    entry_id: int,
    body: ShortlistUpdateRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistEntryResponse:
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    if entry.version != body.version:
        raise HTTPException(
            status_code=409,
            detail="Wpis zmieniony przez kogoś innego — odśwież i spróbuj ponownie.",
        )

    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    for field, value in changes.items():
        setattr(entry, field, value)
    entry.version += 1
    entry.updated_by = current_user.id

    await db.commit()
    await db.refresh(entry)
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == entry.candidate_id)
    )
    return _to_response(
        entry,
        candidate.name if candidate else None,
        candidate.lastname if candidate else None,
    )


@router.delete(
    "/shortlist/{entry_id}",
    summary="Remove a shortlist entry",
)
async def delete_shortlist_entry(
    entry_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted", "id": entry_id}


@router.post(
    "/shortlist/{entry_id}/promote",
    response_model=ShortlistPromoteResponse,
    summary="Promote a shortlist entry into the job's pipeline",
)
async def promote_shortlist_entry(
    entry_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistPromoteResponse:
    """Move an approved shortlist entry into the pipeline (creates a
    ``CandidateStage`` at the first non-terminal stage). Idempotent: if the
    candidate is already in the job's pipeline it just records the promotion.
    Applies the same eligibility gate as bulk-add / single-assign — a global
    blacklist or an active client conflict → 409.
    """
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    job = await db.scalar(select(Job).where(Job.id == entry.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == entry.candidate_id)
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    now = datetime.now(timezone.utc)
    existing_stage = await db.scalar(
        select(CandidateStage).where(
            CandidateStage.job_id == job.id,
            CandidateStage.candidate_id == candidate.id,
        )
    )

    # Already in the pipeline — record the promotion (idempotent) and return.
    if existing_stage is not None:
        already_promoted = entry.promoted_to_pipeline_at is not None
        if not already_promoted:
            entry.promoted_to_pipeline_at = now
            entry.updated_by = current_user.id
            await db.commit()
        return ShortlistPromoteResponse(
            entry_id=entry.id,
            candidate_id=candidate.id,
            job_id=job.id,
            stage_id=existing_stage.id,
            already_promoted=already_promoted,
            already_in_pipeline=True,
        )

    # Eligibility gate before creating a new pipeline row.
    conflict_rows = (
        (
            await db.execute(
                select(CandidateConflict).where(
                    CandidateConflict.candidate_id == candidate.id,
                    CandidateConflict.client_id == job.client_id,
                    CandidateConflict.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    manager_verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=[candidate.id]
    )
    decision = evaluate_eligibility(
        EligibilityInput(
            candidate_status=candidate.status.value,
            job_client_id=job.client_id,
            conflicts=tuple(
                ConflictInput(
                    type=r.type.value,
                    client_id=r.client_id,
                    active=r.active,
                    expires_at=r.expires_at,
                )
                for r in conflict_rows
            ),
            excluded_client_ids=extract_excluded_client_ids(candidate.preferences),
            already_in_job=False,
            rejected_by_hiring_manager=candidate.id in manager_verdicts,
        ),
        now,
    )
    if not decision.assignment_allowed:
        detail = decision.reason
        verdict = manager_verdicts.get(candidate.id)
        if (
            decision.reason_code is EligibilityReason.rejected_by_hiring_manager
            and verdict is not None
        ):
            detail = verdict.as_polish_detail()
        raise HTTPException(status_code=409, detail=detail)

    stage_def = await _resolve_initial_stage(db, job, None)
    legacy_enum = PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = PipelineStage.new

    stage = CandidateStage(
        candidate_id=candidate.id,
        job_id=job.id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        moved_by=current_user.id,
    )
    db.add(stage)
    # M3-ACT-01: snapshot the CV current at promotion + emit the audit, the
    # same invariant the single-assign path holds — shortlist promotion was
    # skipping it. Idempotent + fail-soft.
    await db.flush()
    await create_original_cv_snapshot(db, stage)
    entry.promoted_to_pipeline_at = now
    entry.updated_by = current_user.id
    await db.commit()
    await db.refresh(stage)
    return ShortlistPromoteResponse(
        entry_id=entry.id,
        candidate_id=candidate.id,
        job_id=job.id,
        stage_id=stage.id,
    )
