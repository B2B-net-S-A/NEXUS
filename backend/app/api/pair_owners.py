"""„Prowadzi” — przypisanie osoby prowadzącej kandydata w rekrutacji.

Trasa za bramką sekcji Pipeline; przypisuje admin albo Head of Recruitment
(``HeadOfRecruitmentPlus``). Reguły i skutki: ``services/pair_owner.py``.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services import pair_owner

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class PairOwnerAssign(BaseModel):
    owner_user_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=pair_owner.REASON_MAX)


@router.put("/jobs/{job_id}/candidates/{candidate_id}/owner")
async def assign_pair_owner(
    job_id: int,
    candidate_id: int,
    body: PairOwnerAssign,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await ensure_job_read_access(db, current_user, job_id)
    previous = await pair_owner.owner_ids(db, [(candidate_id, job_id)])
    previous_id = previous.get((candidate_id, job_id)) or (
        await pair_owner.implicit_owner_id(db, candidate_id=candidate_id, job_id=job_id)
    )
    await pair_owner.assign_owner(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        owner_user_id=body.owner_user_id,
        reason=body.reason,
        actor=current_user,
        previous_owner_id=previous_id,
    )
    await db.commit()
    owners = await pair_owner.owners_for_job(db, job_id)
    owner = owners[candidate_id]
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "owner_user_id": owner.owner_user_id,
        "owner_name": owner.owner_name,
        "owner_assigned_by_name": owner.assigned_by_name,
        "owner_assigned_at": owner.assigned_at,
        "owner_previous_name": owner.previous_owner_name,
    }
