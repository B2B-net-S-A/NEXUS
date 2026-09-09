"""Explicit human requirement decisions, scoped to candidate and recruitment."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import require_candidate_read, require_candidate_write
from app.api.candidate_search import _authorized_job
from app.api.deps import get_db
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.requirement_verification import RequirementVerification
from app.models.user import User
from app.schemas.requirement_verification import VerifyRequirementRequest
from app.services.requirement_contract import requirements_for_job
from app.services.requirement_verification import (
    criteria_fingerprint,
    group_key,
    latest_verifications,
    source_fingerprint,
    verification_is_current,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)
_PATH = "/candidate-search/jobs/{job_id}/candidates/{candidate_id}/verifications"


@router.get(_PATH)
async def read_verifications(
    job_id: int,
    candidate_id: int,
    user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    job = await _authorized_job(db, user, job_id)
    await ensure_job_read_access(db, user, job_id)
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Kandydat nie istnieje")
    contract = requirements_for_job(job)
    rows = await latest_verifications(db, job_id, [candidate_id])
    return {
        "requirements": contract.model_dump(),
        "requirements_fingerprint": criteria_fingerprint(contract),
        "candidate_version": str(candidate.updated_at),
        "verifications": [
            {
                "id": row.id,
                "group_key": row.group_key,
                "requirement": row.requirement,
                "status": row.status,
                "evidence": row.evidence,
                "usage_context": row.usage_context,
                "verified_at": row.verified_at,
                "reviewer_id": row.reviewer_id,
                "current": verification_is_current(row, contract, candidate),
            }
            for row in rows
        ],
    }


@router.post(_PATH, status_code=201)
async def verify_requirement(
    job_id: int,
    candidate_id: int,
    body: VerifyRequirementRequest,
    user: User = Depends(require_candidate_write),
    db: AsyncSession = Depends(get_db),
):
    await _authorized_job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    # Serialize with concurrent requirement/profile edits and refresh ORM state.
    job = await db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or candidate is None:
        raise HTTPException(404, "Rekrutacja lub kandydat nie istnieje")
    contract = requirements_for_job(job)
    if body.requirements_fingerprint != criteria_fingerprint(
        contract
    ) or body.candidate_version != str(candidate.updated_at):
        raise HTTPException(
            409, "Wymagania lub profil zmieniły się — odśwież dane przed weryfikacją"
        )
    if body.requirement_index >= len(contract.all_of):
        raise HTTPException(422, "Wymaganie nie istnieje")
    group = contract.all_of[body.requirement_index]
    if group.level not in {"must", "nice"}:
        raise HTTPException(
            422, "Weryfikacja dotyczy wymagań obowiązkowych lub dodatkowych"
        )
    row = RequirementVerification(
        job_id=job_id,
        candidate_id=candidate_id,
        reviewer_id=user.id,
        group_key=group_key(group),
        requirement=group.model_dump(),
        requirements_fingerprint=criteria_fingerprint(contract),
        source_fingerprint=source_fingerprint(candidate),
        status=body.status,
        evidence=body.evidence,
        usage_context=body.usage_context,
        verified_at=body.verified_at,
    )
    db.add(row)
    # Existing full-search/proposal versions must not retain pre-review facts.
    candidate.updated_at = datetime.now(timezone.utc)
    await db.flush()
    result = {
        "id": row.id,
        "status": row.status,
        "candidate_version": str(candidate.updated_at),
    }
    await db.commit()
    return result
