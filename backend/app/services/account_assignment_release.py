"""Zwolnienie przypisań wyłączonego konta (audyt 08.11.2026, B8).

Rekrutacja przypisana do nieaktywnego konta wyglądała na obsadzoną, a nikt nad
nią nie pracował (08.11.2026: 7 otwartych rekrutacji na 4 kontach). Przy
wyłączeniu konta jego żywe przypisania schodzą z powodem ``deactivated``,
prowadzący znika z otwartych rekrutacji, a DL rekrutacji dostaje dzwonek.

Zamknięte rekrutacje zachowują ``jobs.recruiter_id``: wisi na nim historia
i metryki. Konto w toku odejścia z nieprzekazanymi rekrutacjami też nic nie
traci, bo przekazanie (``hr/handover.py``) szuka ich właśnie po tych wierszach
i bez nich przejmujący wskazany przez Kadry nie wszedłby do zespołu.
Bez commitu; wołający commituje.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import NotificationType
from app.models.user import User
from app.services.job_previous_recruiters import _notify, clear_parked
from app.services.recruitment_allocation import allocation_lock, release_operator
from app.services.request_allocation_plan import PROPOSAL_RELEASE_PREFIX

logger = logging.getLogger(__name__)

DEACTIVATED_RELEASE_REASON = "deactivated"


async def _handover_pending(db: AsyncSession, user_id: int) -> bool:
    """Sprawa odejścia w toku, a rekrutacje jeszcze nie przekazane."""
    case_id = await db.scalar(
        select(LifecycleCase.id)
        .outerjoin(
            WorkHandover,
            and_(
                WorkHandover.case_id == LifecycleCase.id,
                WorkHandover.work_kind == "recruitments",
                WorkHandover.status == "done",
            ),
        )
        .where(
            LifecycleCase.user_id == user_id,
            LifecycleCase.kind == "offboarding",
            LifecycleCase.status == "active",
            WorkHandover.id.is_(None),
        )
        .limit(1)
    )
    return case_id is not None


async def planned_release(db: AsyncSession, user_id: int) -> dict[int, list[str]]:
    """Co zejdzie z konta: ``{job_id: [„owner” i/lub stan przypisania]}``."""
    planned: dict[int, list[str]] = {}
    if await _handover_pending(db, user_id):
        return planned
    owned = await db.scalars(
        select(Job.id).where(
            Job.recruiter_id == user_id, Job.status == JobStatus.published
        )
    )
    for job_id in owned.all():
        planned.setdefault(job_id, []).append("owner")
    live = await db.execute(
        select(JobWorkAssignment.job_id, JobWorkAssignment.state).where(
            JobWorkAssignment.user_id == user_id,
            JobWorkAssignment.state != "released",
        )
    )
    for job_id, state in live.all():
        planned.setdefault(job_id, []).append(state)
    return planned


async def release_user_assignments(
    db: AsyncSession, user: User, *, actor_id: Optional[int]
) -> list[int]:
    """Zwalnia przypisania konta. Zwraca rekrutacje, z których ktoś zszedł."""
    planned = await planned_release(db, user.id)
    if not planned:
        return []
    await allocation_lock(db)
    jobs = (
        (
            await db.execute(
                select(Job)
                .where(Job.id.in_(planned))
                .order_by(Job.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    await db.execute(
        update(JobWorkAssignment)
        .where(
            JobWorkAssignment.user_id == user.id,
            JobWorkAssignment.state == "proposed",
        )
        .values(
            state="released",
            released_at=now,
            release_reason=f"{PROPOSAL_RELEASE_PREFIX}{DEACTIVATED_RELEASE_REASON}",
        )
    )
    await db.execute(
        update(JobWorkAssignment)
        .where(
            JobWorkAssignment.user_id == user.id,
            JobWorkAssignment.state != "released",
        )
        .values(
            state="released",
            released_at=now,
            release_reason=DEACTIVATED_RELEASE_REASON,
        )
    )
    released: list[int] = []
    from app.services.notification_triggers import (  # noqa: PLC0415
        _delivery_lead_targets,
    )

    for job in jobs:
        was_owner = job.recruiter_id == user.id and job.status == JobStatus.published
        if was_owner:
            await clear_parked(
                db, job_id=job.id, user_id=user.id, reason="removed", actor_id=actor_id
            )
            await release_operator(db, job=job)
            db.add(
                Activity(
                    entity_type="job",
                    entity_id=job.id,
                    action="owner_released",
                    user_id=actor_id,
                    details={
                        "previous_owner_id": user.id,
                        "reason": DEACTIVATED_RELEASE_REASON,
                    },
                )
            )
        worked = was_owner or "active" in planned.get(job.id, [])
        if job.status != JobStatus.published or not worked:
            continue
        released.append(job.id)
        await _notify(
            db,
            job_id=job.id,
            user_ids=await _delivery_lead_targets(db, job),
            ntype=NotificationType.recruiter_parked,
            title="Rekrutacja straciła rekrutera",
            suffix="Konto osoby, która ją prowadziła, jest wyłączone. Przypisz rekrutera.",
        )
    await db.flush()
    return released


async def release_assignments_safely(
    db: AsyncSession, user: User, *, actor_id: Optional[int]
) -> list[int]:
    """Jak wyżej, ale awaria nie zatrzymuje wyłączenia konta."""
    try:
        async with db.begin_nested():
            return await release_user_assignments(db, user, actor_id=actor_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "account_assignment_release: zwolnienie user_id=%s nie wyszło", user.id
        )
        return []
