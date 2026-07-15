"""Job shortlist API (SEARCH-P1-05).

A pre-pipeline evaluation list per job. Recruiters add candidates from search,
track evaluation + outreach status, then promote approved entries into the
pipeline (promotion lands in a follow-up). Updates use optimistic locking:
the client echoes the ``version`` it read and a stale PATCH 409s.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.job_shortlist import JobShortlistEntry
from app.schemas.job_shortlist import (
    ShortlistAddRequest,
    ShortlistAddResponse,
    ShortlistEntryResponse,
    ShortlistUpdateRequest,
)

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
