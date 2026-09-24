"""Automat przydziału ludzi do requestów — warstwa bazy (24.09.2026).

Zbiera stan świata, woła czysty planer (``request_allocation_plan``) i
zapisuje zmiany w ``job_work_assignments``. Wołany z pętli
``tasks/recruitment_allocation.allocation_loop`` pod tą samą blokadą doradczą
co reszta przydziałów (``allocation_lock``):

* po każdej zmianie, która może zmienić przydział (zdarzenia z outboxa
  ``recruitment_allocation_events``: rekrutacja, kategoria osoby, …);
* raz dziennie o ``review_time`` z Ustawień — wtedy też idzie poranny dzwonek
  „Od dziś: …” do ludzi i skrót dla Delivery Leadów.

Tryby (``recruitment_allocation_state.mode``): ``off`` — nic; ``shadow`` —
przypisania jako ``proposed`` (pulpit pokazuje je jako propozycję, nikt nic
nie dostaje); ``auto`` — ``active``, a pierwszy rekruter zostaje też
prowadzącym rekrutacji (``jobs.recruiter_id``), jeśli go nie było.

Urlopy: ``workforce_context`` z Compassa. Bez świeżych danych tryb ``auto``
nie przydziela nikomu nowych requestów (mógłby trafić ktoś na urlopie), a
tryb ``shadow`` proponuje dalej i pulpit mówi, że danych o urlopach brak.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate_search_run import CandidateSearchRun
from app.models.cc_feedback import JobSecondaryCc
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services.request_allocation_plan import (
    Change,
    LiveAssignment,
    PersonInfo,
    PlanInput,
    RequestInfo,
    plan_assignments,
)
from app.services.request_allocation_rules import AllocationRules, load_rules
from app.services.request_work_state import visible_state

logger = logging.getLogger(__name__)

STATS_KEY = "request_allocation"
RECRUIT_ROLES = (UserRole.recruiter, UserRole.tac)
SOURCE_ROLES = (UserRole.sourcer, UserRole.tac)
OPERATOR_ROLES = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)


def _pool_clause():
    return and_(
        Job.status == JobStatus.published,
        Job.work_state == "searching",
        Job.champion_found_at.is_(None),
    )


async def _requests(db: AsyncSession) -> list[RequestInfo]:
    from app.services import candidate_search_store as store  # noqa: PLC0415
    from app.services.job_proposals import open_counts_for_jobs  # noqa: PLC0415
    from app.services.job_similarity import sent_counts  # noqa: PLC0415

    jobs = (
        await db.execute(
            select(Job.id, Job.competence_category_id, Job.deadline).where(
                _pool_clause()
            )
        )
    ).all()
    ids = [job_id for job_id, _cc, _deadline in jobs]
    if not ids:
        return []
    secondary: dict[int, set[int]] = {}
    for job_id, cc in (
        await db.execute(
            select(JobSecondaryCc.job_id, JobSecondaryCc.competence_category_id).where(
                JobSecondaryCc.job_id.in_(ids)
            )
        )
    ).all():
        secondary.setdefault(job_id, set()).add(cc)
    sent = await sent_counts(db, ids)
    proposals = await open_counts_for_jobs(db, ids)
    reviewed = set(
        (
            await db.scalars(
                select(CandidateSearchRun.job_id).where(
                    CandidateSearchRun.job_id.in_(ids),
                    store.auto_origin_clause(),
                    CandidateSearchRun.completed_at.is_not(None),
                )
            )
        ).all()
    )
    return [
        RequestInfo(
            job_id=job_id,
            categories=frozenset(
                ({cc} if cc else set()) | secondary.get(job_id, set())
            ),
            primary_category=cc,
            sent=int(sent.get(job_id, 0)),
            deadline=deadline,
            # Bez nocnego przeglądu bazy nie wiadomo, ilu pasuje — rekruter.
            base_matches=int(proposals.get(job_id, 0)) if job_id in reviewed else None,
        )
        for job_id, cc, deadline in jobs
    ]


def _role_set(user: User) -> set[str]:
    values = {str(getattr(r, "value", r)) for r in (user.roles or [])}
    values.add(str(getattr(user.role, "value", user.role)))
    return values


async def _people(
    db: AsyncSession, *, available_ids: Optional[set[int]]
) -> list[PersonInfo]:
    """Kto może dostać request. ``available_ids=None`` = brak danych o urlopach."""
    from app.services.section_permissions import (  # noqa: PLC0415
        ProductSection,
        SectionAccess,
        resolve_effective_section_access_for_users,
        section_access_for_user,
    )

    users = list(
        (
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.allocation_excluded.is_(False),
                    or_(
                        User.role.in_(OPERATOR_ROLES),
                        *(User.roles.contains([r.value]) for r in OPERATOR_ROLES),
                    ),
                )
            )
        ).all()
    )
    await resolve_effective_section_access_for_users(db, users)
    users = [
        u
        for u in users
        if section_access_for_user(u, ProductSection.pipeline) >= SectionAccess.write
        and (available_ids is None or u.id in available_ids)
    ]
    if not users:
        return []
    first: dict[int, set[int]] = {}
    second: dict[int, set[int]] = {}
    for user_id, cc, priority in (
        await db.execute(
            select(
                UserCompetenceCategory.user_id,
                UserCompetenceCategory.competence_category_id,
                UserCompetenceCategory.priority,
            ).where(UserCompetenceCategory.user_id.in_([u.id for u in users]))
        )
    ).all():
        (first if priority == 1 else second).setdefault(user_id, set()).add(cc)
    last = dict(
        (
            await db.execute(
                select(
                    JobWorkAssignment.user_id, func.max(JobWorkAssignment.assigned_at)
                )
                .where(JobWorkAssignment.source == "auto")
                .group_by(JobWorkAssignment.user_id)
            )
        ).all()
    )
    people = []
    for user in users:
        roles = _role_set(user)
        # Bez żadnej kategorii osoba nie dostaje requestów — tak zdecydował
        # Artur („osoba bez kategorii nie dostaje requestów automatycznie”).
        if user.id not in first and user.id not in second:
            continue
        people.append(
            PersonInfo(
                user_id=user.id,
                can_recruit=bool(roles & {r.value for r in RECRUIT_ROLES}),
                can_source=bool(roles & {r.value for r in SOURCE_ROLES}),
                first=frozenset(first.get(user.id, set())),
                second=frozenset(second.get(user.id, set())),
                last_assigned=last.get(user.id),
            )
        )
    return people


async def _live(db: AsyncSession) -> tuple[list[LiveAssignment], dict[int, str]]:
    rows = (
        await db.execute(
            select(
                JobWorkAssignment.job_id,
                JobWorkAssignment.user_id,
                JobWorkAssignment.role,
                JobWorkAssignment.source,
                JobWorkAssignment.state,
            ).where(JobWorkAssignment.state != "released")
        )
    ).all()
    if not rows:
        return [], {}
    job_ids = sorted({row.job_id for row in rows})
    in_process = set(
        (
            await db.execute(
                select(
                    RecruitmentProcess.job_id, RecruitmentProcess.owner_user_id
                ).where(
                    RecruitmentProcess.job_id.in_(job_ids),
                    RecruitmentProcess.status == ProcessStatus.open,
                )
            )
        ).all()
    )
    states = {
        job_id: visible_state(work_state, champion)
        if status == JobStatus.published
        else "finished"
        for job_id, work_state, champion, status in (
            await db.execute(
                select(Job.id, Job.work_state, Job.champion_found_at, Job.status).where(
                    Job.id.in_(job_ids)
                )
            )
        ).all()
    }
    live = [
        LiveAssignment(
            job_id=row.job_id,
            user_id=row.user_id,
            role=row.role,
            source=row.source,
            state=row.state,
            in_process=(row.job_id, row.user_id) in in_process,
        )
        for row in rows
    ]
    out = {job_id: state for job_id, state in states.items() if state != "searching"}
    return live, out


async def _apply(
    db: AsyncSession, changes: list[Change], *, mode: str, now: datetime
) -> dict[str, int]:
    counts = {"assigned": 0, "released": 0, "activated": 0}
    for change in changes:
        live_row = and_(
            JobWorkAssignment.job_id == change.job_id,
            JobWorkAssignment.user_id == change.user_id,
            JobWorkAssignment.state != "released",
        )
        if change.kind == "release":
            await db.execute(
                update(JobWorkAssignment)
                .where(live_row)
                .values(state="released", released_at=now, release_reason=change.reason)
            )
            counts["released"] += 1
        elif change.kind == "activate":
            await db.execute(
                update(JobWorkAssignment)
                .where(live_row)
                .values(state="active", assigned_at=now)
            )
            counts["activated"] += 1
            if change.role == "recruiter":
                await _set_owner_if_empty(db, change.job_id, change.user_id)
        elif change.kind == "assign":
            state = "active" if mode == "auto" else "proposed"
            db.add(
                JobWorkAssignment(
                    job_id=change.job_id,
                    user_id=change.user_id,
                    role=change.role,
                    source="auto",
                    state=state,
                    assigned_at=now,
                )
            )
            counts["assigned"] += 1
            if state == "active" and change.role == "recruiter":
                await _set_owner_if_empty(db, change.job_id, change.user_id)
    await db.flush()
    return counts


async def _set_owner_if_empty(db: AsyncSession, job_id: int, user_id: int) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id, Job.recruiter_id.is_(None))
        .values(recruiter_id=user_id)
    )


def _review_due(stats: dict[str, Any], rules: AllocationRules, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if local.time() < rules.review_clock:
        return False
    return stats.get("last_review_date") != local.date().isoformat()


async def run_request_allocation(
    db: AsyncSession,
    *,
    mode: str,
    availability_fresh: bool,
    available_ids: set[int],
    stats: Optional[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Jeden przebieg automatu. Wołający trzyma ``allocation_lock`` i commituje.

    Zwraca nowe ``stats`` (klucz ``request_allocation`` w stanie przydziałów).
    """
    stats = dict(stats or {})
    rules = await load_rules(db)
    requests = await _requests(db)
    people = await _people(
        db,
        available_ids=(
            available_ids
            if availability_fresh and settings.COMPASS_AVAILABILITY_ENABLED
            else None
        ),
    )
    live, out = await _live(db)
    changes = plan_assignments(
        PlanInput(
            requests=requests,
            people=people,
            live=live,
            out_of_pool=out,
            sourcer_threshold=rules.sourcer_threshold,
            mode=mode,
            availability_known=availability_fresh
            and settings.COMPASS_AVAILABILITY_ENABLED,
        )
    )
    counts = await _apply(db, changes, mode=mode, now=now)
    stats.update(
        {
            "last_run_at": now.isoformat(),
            "mode": mode,
            "requests": len(requests),
            "people": len(people),
            "availability_known": bool(
                availability_fresh and settings.COMPASS_AVAILABILITY_ENABLED
            ),
            **counts,
        }
    )
    if _review_due(stats, rules, now):
        local_date = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date()
        try:
            from app.services.request_allocation_notices import (  # noqa: PLC0415
                send_morning_notices,
            )

            async with db.begin_nested():
                stats["morning_notices"] = await send_morning_notices(
                    db, now=now, mode=mode
                )
        except Exception:  # noqa: BLE001 — dzwonek nie może zatrzymać przydziału
            logger.exception("[request_allocation] morning notices failed")
        stats["last_review_date"] = local_date.isoformat()
    return stats


async def manual_add(
    db: AsyncSession, *, job_id: int, user_id: int, role: str, actor_id: int
) -> JobWorkAssignment:
    """Ręczne dodanie osoby z pulpitu. Automat nigdy jej nie zdejmie za urlop."""
    existing = await db.scalar(
        select(JobWorkAssignment)
        .where(
            JobWorkAssignment.job_id == job_id,
            JobWorkAssignment.user_id == user_id,
            JobWorkAssignment.state != "released",
        )
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.state = "active"
        existing.source = "manual"
        existing.role = role
        existing.assigned_by = actor_id
        await db.flush()
        return existing
    row = JobWorkAssignment(
        job_id=job_id,
        user_id=user_id,
        role=role,
        source="manual",
        state="active",
        assigned_at=now,
        assigned_by=actor_id,
    )
    db.add(row)
    if role == "recruiter":
        await _set_owner_if_empty(db, job_id, user_id)
    await db.flush()
    return row


async def manual_remove(db: AsyncSession, *, job_id: int, user_id: int) -> bool:
    result = await db.execute(
        update(JobWorkAssignment)
        .where(
            JobWorkAssignment.job_id == job_id,
            JobWorkAssignment.user_id == user_id,
            JobWorkAssignment.state != "released",
        )
        .values(
            state="released",
            released_at=datetime.now(timezone.utc),
            release_reason="manual",
        )
    )
    return bool(result.rowcount)


def changed_since(now: datetime) -> datetime:
    """Początek okna „Zmiany od wczoraj” — 24 h wstecz."""
    return now - timedelta(hours=24)
