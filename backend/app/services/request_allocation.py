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

Prowadzący rekrutacji (``jobs.recruiter_id`` — z handoffu, z Traffita albo
wpisany ręcznie) jest przy requeście z urzędu: przebieg dopisuje mu wiersz
``source='owner'``, więc automat nie dokłada drugiej osoby tylko dlatego, że
nie widział prowadzącego. Takie wiersze nie są „zmianą” ani dzwonkiem.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cc_feedback import JobSecondaryCc
from app.models.competence_category import UserCompetenceCategory
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
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
    # Liczba pasujących w bazie = otwarte propozycje z nocnego przeglądu
    # (``full_base``). Wiersze samego przeglądu żyją 2 dni
    # (``AUTO_FULL_REVIEW_RETENTION_DAYS``), więc „czy był przegląd” czytamy
    # z propozycji, które zostają — inaczej request wchodzący do puli po
    # dwóch dniach zawsze dostawał rekrutera.
    proposals = await open_counts_for_jobs(db, ids, source="full_base")
    reviewed = set(
        (
            await db.scalars(
                select(JobProposal.job_id)
                .where(
                    JobProposal.job_id.in_(ids),
                    JobProposal.source == "full_base",
                )
                .distinct()
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
) -> tuple[list[PersonInfo], frozenset[int]]:
    """Kto może dostać request i kto mógłby, gdyby nie urlop.

    ``available_ids=None`` = brak danych o urlopach. Drugi element to osoby
    z rolą, dostępem, kategorią i bez „Poza przydziałem” — niezależnie od
    urlopu; planer zwalnia resztę bez czekania na Compass.
    """
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
    ]
    if not users:
        return [], frozenset()
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
    eligible: set[int] = set()
    for user in users:
        roles = _role_set(user)
        # Bez żadnej kategorii osoba nie dostaje requestów — tak zdecydował
        # Artur („osoba bez kategorii nie dostaje requestów automatycznie”).
        if user.id not in first and user.id not in second:
            continue
        eligible.add(user.id)
        if available_ids is not None and user.id not in available_ids:
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
    return people, frozenset(eligible)


async def _blocked(db: AsyncSession) -> frozenset[tuple[int, int]]:
    """Pary zdjęte ręcznie w BIEŻĄCYM stanie requestu (po ostatniej zmianie)."""
    rows = (
        await db.execute(
            select(JobWorkAssignment.job_id, JobWorkAssignment.user_id)
            .join(Job, Job.id == JobWorkAssignment.job_id)
            .where(
                _pool_clause(),
                JobWorkAssignment.state == "released",
                JobWorkAssignment.release_reason == "manual",
                or_(
                    Job.work_state_changed_at.is_(None),
                    JobWorkAssignment.released_at >= Job.work_state_changed_at,
                ),
            )
        )
    ).all()
    return frozenset((job_id, user_id) for job_id, user_id in rows)


AUTO_RELEASE_REASONS = ("unavailable", "excluded")


async def _auto_released(db: AsyncSession) -> frozenset[tuple[int, int]]:
    """Pary zwolnione przez automat (urlop, „Poza przydziałem”) w BIEŻĄCYM
    stanie requestu. Adopcja prowadzącego ich nie cofa — inaczej zwolnienie
    wracało następnym przebiegiem jako wiersz ``owner``, którego planer nie
    zwalnia nigdy, i request stał „pokryty” przez osobę na urlopie."""
    rows = (
        await db.execute(
            select(JobWorkAssignment.job_id, JobWorkAssignment.user_id)
            .join(Job, Job.id == JobWorkAssignment.job_id)
            .where(
                _pool_clause(),
                JobWorkAssignment.state == "released",
                JobWorkAssignment.release_reason.in_(AUTO_RELEASE_REASONS),
                or_(
                    Job.work_state_changed_at.is_(None),
                    JobWorkAssignment.released_at >= Job.work_state_changed_at,
                ),
            )
        )
    ).all()
    return frozenset((job_id, user_id) for job_id, user_id in rows)


async def _adopt_owners(
    db: AsyncSession,
    *,
    blocked: frozenset[tuple[int, int]],
    now: datetime,
    auto_released: frozenset[tuple[int, int]] = frozenset(),
) -> dict[str, int]:
    """Prowadzący rekrutacji jest przy requeście — wiersz ``owner``.

    Zmiana prowadzącego zwalnia poprzedni wiersz ``owner``, a nieaktywne konto
    prowadzącego — jego wiersz (inaczej zostawał na zawsze i nikt nie dostawał
    requestu). Prowadzący zdjęty ręcznie z pulpitu albo zwolniony przez
    automat (urlop, „Poza przydziałem”) nie wraca, dopóki request nie zmieni
    stanu.
    """
    inactive = select(User.id).where(User.is_active.is_(False))
    stale = await db.execute(
        update(JobWorkAssignment)
        .where(
            JobWorkAssignment.source == "owner",
            JobWorkAssignment.state != "released",
            JobWorkAssignment.job_id == Job.id,
            or_(
                Job.recruiter_id.is_(None),
                Job.recruiter_id != JobWorkAssignment.user_id,
                JobWorkAssignment.user_id.in_(inactive),
            ),
        )
        .values(state="released", released_at=now, release_reason="owner_changed")
        .execution_options(synchronize_session=False)
    )
    owners = (
        await db.execute(
            select(Job.id, Job.recruiter_id)
            .join(User, User.id == Job.recruiter_id)
            .where(_pool_clause(), User.is_active.is_(True))
        )
    ).all()
    if not owners:
        return {"owner_released": stale.rowcount or 0, "owner_adopted": 0}
    live = set(
        (
            await db.execute(
                select(JobWorkAssignment.job_id, JobWorkAssignment.user_id).where(
                    JobWorkAssignment.state != "released",
                    JobWorkAssignment.job_id.in_([job_id for job_id, _ in owners]),
                )
            )
        ).all()
    )
    adopted = 0
    for job_id, user_id in owners:
        pair = (job_id, user_id)
        if pair in live or pair in blocked or pair in auto_released:
            continue
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=user_id,
                role="recruiter",
                source="owner",
                state="active",
                assigned_at=now,
            )
        )
        adopted += 1
    await db.flush()
    return {"owner_released": stale.rowcount or 0, "owner_adopted": adopted}


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
            previous = (
                await db.execute(
                    select(JobWorkAssignment.source, JobWorkAssignment.state).where(
                        live_row
                    )
                )
            ).first()
            await db.execute(
                update(JobWorkAssignment)
                .where(live_row)
                .values(state="released", released_at=now, release_reason=change.reason)
            )
            counts["released"] += 1
            if (
                change.reason in AUTO_RELEASE_REASONS
                and change.role == "recruiter"
                and previous is not None
                and previous.source == "auto"
                and previous.state == "active"
            ):
                # Aktywny rekruter automatu był wpisany jako prowadzący przez
                # ``_set_owner_if_empty``. Jeśli nikt tego potem nie zmienił,
                # zwolnienie zdejmuje też prowadzącego — inaczej osoba na
                # urlopie zostawała prowadzącą, a adopcja przywracała ją
                # przy requeście.
                await _clear_auto_owner(db, change.job_id, change.user_id)
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


async def _clear_auto_owner(db: AsyncSession, job_id: int, user_id: int) -> None:
    await db.execute(
        update(Job)
        .where(Job.id == job_id, Job.recruiter_id == user_id)
        .values(recruiter_id=None)
    )


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
    people, eligible_ids = await _people(
        db,
        available_ids=(
            available_ids
            if availability_fresh and settings.COMPASS_AVAILABILITY_ENABLED
            else None
        ),
    )
    blocked = await _blocked(db)
    auto_released = await _auto_released(db) if mode != "off" else frozenset()
    owner_counts = (
        await _adopt_owners(db, blocked=blocked, now=now, auto_released=auto_released)
        if mode != "off"
        else {"owner_released": 0, "owner_adopted": 0}
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
            eligible_ids=eligible_ids,
            blocked=blocked,
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
            **owner_counts,
        }
    )
    if _review_due(stats, rules, now):
        local_date = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date()
        try:
            from app.services.request_allocation_notices import (  # noqa: PLC0415
                send_morning_notices,
            )

            async with db.begin_nested():
                notices = await send_morning_notices(
                    db,
                    now=now,
                    mode=mode,
                    silent_reminded=stats.get("silent_reminded"),
                )
            # Kiedy który request „Klient milczy” był ostatnio przypomniany —
            # rytm 14 dni liczy się od tej daty (`silent_reminder_due`).
            stats["silent_reminded"] = notices.pop("silent_reminded", {})
            stats["morning_notices"] = notices
        except Exception:  # noqa: BLE001 — dzwonek nie może zatrzymać przydziału
            logger.exception("[request_allocation] morning notices failed")
        stats["last_review_date"] = local_date.isoformat()
    return stats


async def manual_add(
    db: AsyncSession, *, job_id: int, user_id: int, role: str, actor_id: int
) -> JobWorkAssignment:
    """Ręczne dodanie osoby z pulpitu. Automat nigdy jej nie zdejmie za urlop.

    Wołający trzyma ``allocation_lock`` (przed blokadą rekrutacji). Wstawienie
    jest idempotentne (``ON CONFLICT DO NOTHING`` na żywej parze), więc
    podwójne kliknięcie ani przebieg automatu dodający tę samą parę nie kończą
    się naruszeniem ``ux_job_work_assignments_live`` (goły 500).
    """
    live_pair = and_(
        JobWorkAssignment.job_id == job_id,
        JobWorkAssignment.user_id == user_id,
        JobWorkAssignment.state != "released",
    )
    now = datetime.now(timezone.utc)
    inserted_id = await db.scalar(
        pg_insert(JobWorkAssignment)
        .values(
            job_id=job_id,
            user_id=user_id,
            role=role,
            source="manual",
            state="active",
            assigned_at=now,
            assigned_by=actor_id,
        )
        .on_conflict_do_nothing(
            index_elements=["job_id", "user_id"],
            index_where=text("state <> 'released'"),
        )
        .returning(JobWorkAssignment.id)
    )
    if inserted_id is None:
        # Para już żyje (automat albo drugie kliknięcie) — przejmij ją ręcznie.
        await db.execute(
            update(JobWorkAssignment)
            .where(live_pair)
            .values(state="active", source="manual", role=role, assigned_by=actor_id)
            .execution_options(synchronize_session=False)
        )
    if role == "recruiter":
        await _set_owner_if_empty(db, job_id, user_id)
    await db.flush()
    row = await db.scalar(
        select(JobWorkAssignment)
        .where(live_pair)
        .execution_options(populate_existing=True)
    )
    assert row is not None
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
