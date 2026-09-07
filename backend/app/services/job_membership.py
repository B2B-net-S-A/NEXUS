"""Sprawdzanie i listowanie członków rekrutacji (Job).

Członkowie projektu = osoby które mogą widzieć Job Chat danego projektu:
    - admin (każdy admin systemu)
    - job.recruiter_id (właściciel/owner)
    - job.delivery_lead_id (DL projektu)
    - job.tac_id (TAC projektu)
    - aktywni job_collaborators (removed_from_auto_cc=False)

Klient i kandydat NIE są członkami — Job Chat jest wewnętrzny.
"""

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole
from app.core.config import settings
from app.services.workforce_availability import (
    workforce_context,
    effective_owner_ids,
    open_operational_job_clause,
)
from app.models.recruitment_priority import (
    RecruitmentPriorityAssignment,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityPlan,
    PriorityPlanStatus,
    PriorityMemberStatus,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access_for_users,
    section_access_for_user,
)


async def is_member_of_job(
    db: AsyncSession,
    user: User,
    job_id: int,
    *,
    admin_bypass: bool = True,
) -> bool:
    """Czy user może widzieć/uczestniczyć w Job Chacie danego projektu.

    ``admin_bypass=False`` supports an admin explicitly acting in a self-scoped
    persona without changing the chat-oriented default contract.
    """
    # A historical owner/collaborator id is not an authorization grant.
    # Recruitment chat is candidate-domain data, so Finance/viewer and
    # deactivated accounts fail closed before membership is evaluated.
    if not user_can_access_candidate_domain(user):
        return False
    if admin_bypass and user.has_role(UserRole.admin):
        return True

    job = await db.get(Job, job_id)
    if job is None:
        return False

    owners = await effective_owner_ids(db, user.id)
    inherited = owners - {user.id}
    if inherited:
        from app.services.workforce_availability import (
            inherited_collaborator_work_clause,
        )

        if (
            await db.scalar(
                select(Job.id).where(
                    Job.id == job_id,
                    inherited_collaborator_work_clause(Job.id, inherited),
                )
            )
            is not None
        ):
            return True
    if not job.is_open or job.status == JobStatus.closed:
        has_open_work = inherited and await db.scalar(
            select(Job.id).where(
                Job.id == job_id, open_operational_job_clause(Job.id, inherited)
            )
        )
        if not has_open_work:
            owners = {user.id}
    if (
        job.recruiter_id in owners
        or job.delivery_lead_id in owners
        or job.tac_id in owners
    ):
        return True

    if settings.RECRUITMENT_ALLOCATION_ENABLED:
        commitment = await db.scalar(
            select(RecruitmentPriorityAssignment.id)
            .join(
                RecruitmentPriorityPlanMember,
                RecruitmentPriorityPlanMember.id
                == RecruitmentPriorityAssignment.plan_member_id,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityAssignment.job_id == job_id,
                RecruitmentPriorityPlanMember.user_id.in_(owners),
                RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            )
            .limit(1)
        )
        if commitment is not None:
            return True

    q = (
        select(JobCollaborator.id)
        .where(JobCollaborator.job_id == job_id)
        .where(JobCollaborator.user_id == user.id)
        .where(JobCollaborator.removed_from_auto_cc.is_(False))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none() is not None


async def list_job_member_ids(db: AsyncSession, job_id: int) -> list[int]:
    """Zwraca unikalną listę user_id członków projektu (z adminami)."""
    job = await db.get(Job, job_id)
    if job is None:
        return []

    member_ids: set[int] = set()
    if job.recruiter_id:
        member_ids.add(job.recruiter_id)
    if job.delivery_lead_id:
        member_ids.add(job.delivery_lead_id)
    if job.tac_id:
        member_ids.add(job.tac_id)

    # Aktywni collaboratorzy
    rows = await db.execute(
        select(JobCollaborator.user_id)
        .where(JobCollaborator.job_id == job_id)
        .where(JobCollaborator.removed_from_auto_cc.is_(False))
    )
    for (uid,) in rows.all():
        member_ids.add(uid)

    if settings.RECRUITMENT_ALLOCATION_ENABLED:
        members = await db.scalars(
            select(RecruitmentPriorityPlanMember.user_id)
            .join(
                RecruitmentPriorityAssignment,
                RecruitmentPriorityAssignment.plan_member_id
                == RecruitmentPriorityPlanMember.id,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityAssignment.job_id == job_id,
                RecruitmentPriorityPlanMember.status == PriorityMemberStatus.active,
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
            )
        )
        member_ids.update(members.all())

    # Wszyscy admini systemu (małych liczb użytkowników — OK)
    admins = await db.execute(
        select(User.id)
        .where(User.role == UserRole.admin)
        .where(User.is_active.is_(True))
    )
    for (uid,) in admins.all():
        member_ids.add(uid)

    if settings.COMPASS_AVAILABILITY_ENABLED:
        context = await workforce_context(db)
        # Notifications use the same resource boundary as interactive access.
        # An observer's absence alone must not subscribe the substitute.
        for owner_id in member_ids & context.delegations.keys():
            substitute = await db.get(User, context.performer(owner_id))
            if substitute and await is_member_of_job(db, substitute, job_id):
                member_ids.discard(owner_id)
                member_ids.add(substitute.id)

    if not member_ids:
        return []

    eligible_rows = await db.execute(
        select(User).where(User.id.in_(member_ids)).where(User.is_active.is_(True))
    )
    eligible_users = list(eligible_rows.scalars().all())
    await resolve_effective_section_access_for_users(db, eligible_users)
    eligible_ids = {
        user.id
        for user in eligible_users
        if user_can_access_candidate_domain(user)
        and section_access_for_user(user, ProductSection.pipeline) >= SectionAccess.read
    }
    return sorted(eligible_ids)


async def list_job_members(db: AsyncSession, job_id: int) -> list[User]:
    """Zwraca pełne obiekty User członków projektu (z adminami)."""
    ids = await list_job_member_ids(db, job_id)
    if not ids:
        return []
    rows = await db.execute(select(User).where(User.id.in_(ids)))
    users = list(rows.scalars().all())
    users.sort(key=lambda u: (u.role.value, u.name.lower()))
    return users


async def filter_to_members(
    db: AsyncSession, job_id: int, user_ids: Iterable[int]
) -> list[int]:
    """Z listy user_ids zwróć tylko tych którzy są członkami projektu."""
    members = set(await list_job_member_ids(db, job_id))
    return [uid for uid in user_ids if uid in members]
