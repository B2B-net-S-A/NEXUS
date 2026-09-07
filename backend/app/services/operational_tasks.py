"""Shared ownership metadata for open tasks; creators and credit are immutable."""

from sqlalchemy import select

from app.models.candidate_contact import CandidateContactCase
from app.models.job import Job
from app.models.recruitment_process import RecruitmentProcess, ProcessStatus
from app.services.workforce_availability import workforce_context


async def nominal_task_owner(
    db, *, actor_id: int, job_id=None, candidate_id=None
) -> int:
    context = await workforce_context(db)
    if not context.delegations:
        return actor_id
    owners = context.owners_for(actor_id) - {actor_id}
    if not owners:
        return actor_id
    # Prefer the specific candidate process, then its contact queue, then job.
    if candidate_id is not None and job_id is not None:
        owner = await db.scalar(
            select(RecruitmentProcess.owner_user_id)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
                RecruitmentProcess.status == ProcessStatus.open,
                RecruitmentProcess.owner_user_id.in_(owners),
            )
            .order_by(RecruitmentProcess.id.desc())
            .limit(1)
        )
        if owner is not None:
            return owner
    if candidate_id is not None:
        owner = await db.scalar(
            select(CandidateContactCase.owner_user_id)
            .where(
                CandidateContactCase.candidate_id == candidate_id,
                CandidateContactCase.owner_user_id.in_(owners),
                CandidateContactCase.state.not_in(["closed", "exhausted"]),
            )
            .limit(1)
        )
        if owner is not None:
            return owner
    if job_id is not None:
        owner = await db.scalar(
            select(Job.recruiter_id).where(
                Job.id == job_id, Job.recruiter_id.in_(owners)
            )
        )
        if owner is not None:
            return owner
    return actor_id


async def ownership_payload(
    db, owner_id: int | None, *, open_task: bool = True
) -> dict:
    context = await workforce_context(db)
    delegation = context.delegations.get(owner_id) if open_task else None
    return {
        "owner_user_id": owner_id,
        "effective_user_id": delegation.performer_id if delegation else owner_id,
        "substitution": delegation.as_payload() if delegation else None,
    }
