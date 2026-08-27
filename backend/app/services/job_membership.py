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
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole


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

    if (
        job.recruiter_id == user.id
        or job.delivery_lead_id == user.id
        or job.tac_id == user.id
    ):
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

    # Wszyscy admini systemu (małych liczb użytkowników — OK)
    admins = await db.execute(
        select(User.id)
        .where(User.role == UserRole.admin)
        .where(User.is_active.is_(True))
    )
    for (uid,) in admins.all():
        member_ids.add(uid)

    if not member_ids:
        return []

    eligible_rows = await db.execute(
        select(User).where(User.id.in_(member_ids)).where(User.is_active.is_(True))
    )
    eligible_ids = {
        user.id
        for user in eligible_rows.scalars().all()
        if user_can_access_candidate_domain(user)
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
