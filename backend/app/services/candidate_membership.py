"""Candidate Chat membership.

Members of a candidate chat:
    - admin (every active admin)
    - candidate.created_by (recruiter who added the candidate)
    - any user who is recruiter/DL/TAC of a Job that has this candidate
      in its pipeline (via candidate_stages)
    - active job_collaborator on such Job
    - any user who has authored a candidate_chat_message for this candidate
      (so reply chains stay accessible even after pipeline changes)
"""

from typing import Iterable

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole


async def is_member_of_candidate_chat(
    db: AsyncSession, user: User, candidate_id: int
) -> bool:
    """True if user can read/post in chat for this candidate."""
    if user.role == UserRole.admin:
        return True

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return False

    if candidate.created_by == user.id:
        return True

    # Sub-query: jobs that have this candidate in pipeline
    stage_jobs_q = (
        select(distinct(CandidateStage.job_id))
        .where(CandidateStage.candidate_id == candidate_id)
    )
    job_ids = [jid for (jid,) in (await db.execute(stage_jobs_q)).all()]
    if not job_ids:
        return False

    # owner of any such job
    own_q = (
        select(Job.id)
        .where(Job.id.in_(job_ids))
        .where(
            (Job.recruiter_id == user.id)
            | (Job.delivery_lead_id == user.id)
            | (Job.tac_id == user.id)
        )
        .limit(1)
    )
    if (await db.execute(own_q)).scalar_one_or_none() is not None:
        return True

    # active collaborator on any such job
    collab_q = (
        select(JobCollaborator.id)
        .where(JobCollaborator.job_id.in_(job_ids))
        .where(JobCollaborator.user_id == user.id)
        .where(JobCollaborator.removed_from_auto_cc.is_(False))
        .limit(1)
    )
    return (await db.execute(collab_q)).scalar_one_or_none() is not None


async def list_candidate_chat_member_ids(
    db: AsyncSession, candidate_id: int
) -> list[int]:
    """Unique sorted list of user_ids that can see this candidate's chat."""
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return []

    member_ids: set[int] = set()
    if candidate.created_by:
        member_ids.add(candidate.created_by)

    # All admins
    admin_rows = await db.execute(
        select(User.id)
        .where(User.role == UserRole.admin)
        .where(User.is_active.is_(True))
    )
    for (uid,) in admin_rows.all():
        member_ids.add(uid)

    # Find all jobs touching this candidate
    job_rows = await db.execute(
        select(distinct(CandidateStage.job_id)).where(
            CandidateStage.candidate_id == candidate_id
        )
    )
    job_ids = [jid for (jid,) in job_rows.all()]

    if job_ids:
        # Owners (recruiter / DL / TAC) of those jobs
        owner_rows = await db.execute(
            select(Job.recruiter_id, Job.delivery_lead_id, Job.tac_id).where(
                Job.id.in_(job_ids)
            )
        )
        for r, d, t in owner_rows.all():
            for uid in (r, d, t):
                if uid is not None:
                    member_ids.add(uid)

        # Active collaborators of those jobs
        collab_rows = await db.execute(
            select(JobCollaborator.user_id)
            .where(JobCollaborator.job_id.in_(job_ids))
            .where(JobCollaborator.removed_from_auto_cc.is_(False))
        )
        for (uid,) in collab_rows.all():
            member_ids.add(uid)

    return sorted(member_ids)


async def list_candidate_chat_members(
    db: AsyncSession, candidate_id: int
) -> list[User]:
    ids = await list_candidate_chat_member_ids(db, candidate_id)
    if not ids:
        return []
    rows = await db.execute(select(User).where(User.id.in_(ids)))
    users = list(rows.scalars().all())
    users.sort(key=lambda u: (u.role.value, u.name.lower()))
    return users


async def filter_to_candidate_members(
    db: AsyncSession, candidate_id: int, user_ids: Iterable[int]
) -> list[int]:
    members = set(await list_candidate_chat_member_ids(db, candidate_id))
    return [uid for uid in user_ids if uid in members]
