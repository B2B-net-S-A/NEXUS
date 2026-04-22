"""
Phase 13 — 5 automatycznych triggerów powiadomień.

Każdy trigger to async funkcja `check_*` uruchamiana z `tasks/triggers_loop.py`
co 5 min. Idempotentność zapewnia unique partial index `ix_notif_dedup_daily`
(user, type, entity, lokalny dzień Warsaw) + `emit()` łapiący IntegrityError.

Triggery:
  1. check_dl_stage_stale_6h     — kandydat w `cv_sent` > 6h bez ruchu → alert do DL.
  2. check_client_feedback_eobd  — o 16:30 dla `client_interview` zakończonego dziś
                                   bez feedbacku (brak ScreeningNote po end_time).
  3. check_powercalling_kpi      — o 11:45: rekruterzy z <15 completed Call dziś +
                                   agregat do każdego head_of_recruitment.
  4. check_candidate_feedback_1h — 60–75 min po Call completed bez ScreeningNote →
                                   alert do rekrutera (Call.user_id).
  5. check_stage_stuck_7d        — kandydat na nieterminalnym etapie > 7 dni →
                                   alert do Job.recruiter_id.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ws as ws_manager
from app.core.config import settings
from app.core.scheduling import (
    is_within_window,
    local_day_bounds,
)
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.call import Call, CallStatus
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.screening_note import ScreeningNote
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

# Non-terminal stages — kandydat jest "w grze" i może utknąć.
_NON_TERMINAL_STAGES: frozenset[PipelineStage] = frozenset(
    s
    for s in PipelineStage
    if s not in {PipelineStage.hired, PipelineStage.rejected, PipelineStage.withdrawn}
)


# ── Emission ──────────────────────────────────────────────────────────────────


async def emit(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    message: str,
    ntype: NotificationType,
    related_entity_type: Optional[str],
    related_entity_id: Optional[int],
    link: Optional[str] = None,
) -> Optional[Notification]:
    """Wstawia `Notification` z gwarancją idempotentności.

    Duplikat (ten sam user+type+entity w tym samym lokalnym dniu) jest blokowany
    przez unique partial index `ix_notif_dedup_daily`. W takim przypadku INSERT
    rzuca IntegrityError → nested savepoint jest rollbackowany, a główna
    transakcja może kontynuować.

    Zwraca utworzoną Notification lub None (duplikat).
    """
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        notification_type=ntype,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    try:
        async with db.begin_nested():
            db.add(notif)
            await db.flush()
    except IntegrityError:
        logger.debug(
            "notification dedup hit: user=%s type=%s entity=%s — skipped",
            user_id,
            ntype.value,
            related_entity_id,
        )
        return None

    # Best-effort WS push — brak odbiorcy online = brak problemu (poll to złapie).
    try:
        await ws_manager.notify_user(
            user_id,
            {
                "type": "notification",
                "data": {
                    "id": notif.id,
                    "title": notif.title,
                    "message": notif.message,
                    "link": notif.link,
                    "notification_type": ntype.value,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS push failed for user=%s: %s", user_id, exc)
    return notif


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _latest_stage_per_pair(
    db: AsyncSession,
) -> dict[tuple[int, int], CandidateStage]:
    """Najnowszy CandidateStage per (candidate_id, job_id). Single scan."""
    rows = await db.execute(
        select(CandidateStage).order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
        )
    )
    latest: dict[tuple[int, int], CandidateStage] = {}
    for stage in rows.scalars().all():
        key = (stage.candidate_id, stage.job_id)
        if key not in latest:
            latest[key] = stage
    return latest


async def _jobs_by_id(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, Job]:
    ids = list({jid for jid in job_ids if jid is not None})
    if not ids:
        return {}
    rows = await db.execute(select(Job).where(Job.id.in_(ids)))
    return {j.id: j for j in rows.scalars().all()}


async def _delivery_lead_targets(db: AsyncSession, job: Job) -> list[int]:
    """Do kogo trafia alert DL-owy.

    Primary: `job.delivery_lead_id`. Jeśli NULL → fallback do wszystkich
    userów z rolą `delivery_lead`.
    """
    if job.delivery_lead_id:
        return [job.delivery_lead_id]
    rows = await db.execute(
        select(User.id).where(
            User.role == UserRole.delivery_lead, User.is_active.is_(True)
        )
    )
    return list(rows.scalars().all())


def _moved_at_utc(stage: CandidateStage) -> datetime:
    """`CandidateStage.moved_at` jako aware UTC."""
    moved = stage.moved_at
    if moved.tzinfo is None:
        return moved.replace(tzinfo=timezone.utc)
    return moved.astimezone(timezone.utc)


def _date_as_int(moment: datetime) -> int:
    """YYYYMMDD jako int — kanoniczne entity_id dla raportów dziennych."""
    return moment.year * 10000 + moment.month * 100 + moment.day


# ── Trigger 1: DL_STAGE_STALE_6H ──────────────────────────────────────────────


async def check_dl_stage_stale_6h(db: AsyncSession, now: datetime) -> int:
    """Kandydat w `cv_sent` od ≥6h → alert do DL."""
    latest = await _latest_stage_per_pair(db)
    cutoff = now.astimezone(timezone.utc) - timedelta(
        hours=settings.DL_STAGE_STALE_HOURS
    )
    candidates = [
        s
        for s in latest.values()
        if s.stage == PipelineStage.cv_sent and _moved_at_utc(s) <= cutoff
    ]
    if not candidates:
        return 0

    jobs = await _jobs_by_id(db, (s.job_id for s in candidates))
    emitted = 0
    for stage in candidates:
        job = jobs.get(stage.job_id)
        if not job:
            continue
        targets = await _delivery_lead_targets(db, job)
        if not targets:
            continue
        hours = int((now.astimezone(timezone.utc) - _moved_at_utc(stage)).total_seconds() // 3600)
        for dl_id in targets:
            result = await emit(
                db,
                user_id=dl_id,
                title="Kandydat czeka na decyzję DL",
                message=(
                    f"Kandydat #{stage.candidate_id} siedzi w etapie 'CV wysłane' "
                    f"od {hours}h w ofercie '{job.title}' (#{job.id}). "
                    "Przepuść go dalej albo odrzuć."
                ),
                link=f"/jobs/{job.id}",
                ntype=NotificationType.dl_stage_stale_6h,
                related_entity_type="candidate_stage",
                related_entity_id=stage.id,
            )
            if result is not None:
                emitted += 1
    return emitted


# ── Trigger 2: CLIENT_FEEDBACK_EOBD ───────────────────────────────────────────


async def check_client_feedback_eobd(db: AsyncSession, now: datetime) -> int:
    """O 16:30 — brak feedbacku klienta po interview z klientem dziś → alert DL."""
    if not is_within_window(
        now,
        hour=settings.CLIENT_FEEDBACK_ALERT_HOUR,
        minute=settings.CLIENT_FEEDBACK_ALERT_MINUTE,
    ):
        return 0

    day = local_day_bounds(now)
    # Wszystkie dzisiejsze zakończone interview (event_type=interview, status=completed).
    ev_rows = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.event_type == EventType.interview,
            CalendarEvent.status == EventStatus.completed,
            CalendarEvent.end_time.isnot(None),
            CalendarEvent.end_time >= day.start_utc,
            CalendarEvent.end_time <= day.end_utc,
            CalendarEvent.candidate_id.isnot(None),
            CalendarEvent.job_id.isnot(None),
        )
    )
    events = list(ev_rows.scalars().all())
    if not events:
        return 0

    latest = await _latest_stage_per_pair(db)
    emitted = 0
    jobs = await _jobs_by_id(db, (e.job_id for e in events))
    for event in events:
        stage = latest.get((event.candidate_id, event.job_id))
        if stage is None or stage.stage != PipelineStage.client_interview:
            continue
        job = jobs.get(event.job_id)
        if job is None:
            continue
        # Feedback = jakakolwiek ScreeningNote dla tego candidate+job po end_time.
        fb = await db.execute(
            select(func.count())
            .select_from(ScreeningNote)
            .where(
                ScreeningNote.candidate_id == event.candidate_id,
                ScreeningNote.job_id == event.job_id,
                ScreeningNote.created_at > event.end_time,
            )
        )
        if (fb.scalar() or 0) > 0:
            continue
        targets = await _delivery_lead_targets(db, job)
        for dl_id in targets:
            result = await emit(
                db,
                user_id=dl_id,
                title="Zapytaj klienta o feedback",
                message=(
                    f"Kandydat #{event.candidate_id} miał dziś rozmowę u klienta "
                    f"w ofercie '{job.title}' (#{job.id}). Brak zanotowanego "
                    "feedbacku — złap go do końca dnia pracy."
                ),
                link=f"/jobs/{job.id}",
                ntype=NotificationType.client_feedback_eobd,
                related_entity_type="calendar_event",
                related_entity_id=event.id,
            )
            if result is not None:
                emitted += 1
    return emitted


# ── Trigger 3: POWERCALLING_KPI ───────────────────────────────────────────────


async def check_powercalling_kpi(db: AsyncSession, now: datetime) -> int:
    """O 11:45 — per-recruiter alert o <15 calli + agregat do HR-ów."""
    if not is_within_window(
        now,
        hour=settings.POWERCALLING_CHECK_HOUR,
        minute=settings.POWERCALLING_CHECK_MINUTE,
    ):
        return 0

    day = local_day_bounds(now)
    target = settings.POWERCALLING_DAILY_TARGET

    # Wszyscy aktywni rekruterzy.
    recruiters_rows = await db.execute(
        select(User.id, User.name).where(
            User.role == UserRole.recruiter, User.is_active.is_(True)
        )
    )
    recruiters = [(r.id, r.name) for r in recruiters_rows]
    if not recruiters:
        return 0

    # Liczba completed Call per user od startu dnia lokalnego.
    counts_rows = await db.execute(
        select(Call.user_id, func.count(Call.id))
        .where(
            Call.status == CallStatus.completed,
            Call.user_id.isnot(None),
            Call.created_at >= day.start_utc,
            Call.created_at <= day.end_utc,
        )
        .group_by(Call.user_id)
    )
    calls_per_user: dict[int, int] = {row[0]: row[1] for row in counts_rows}

    emitted = 0
    day_id = _date_as_int(now)
    below_target: list[tuple[int, str, int]] = []
    for user_id, name in recruiters:
        count = calls_per_user.get(user_id, 0)
        if count < target:
            below_target.append((user_id, name, count))

    # Indywidualne alerty dla rekruterów < target.
    for user_id, name, count in below_target:
        result = await emit(
            db,
            user_id=user_id,
            title="Baza PowerCalling niekompletna",
            message=(
                f"Masz {count}/{target} wykonanych rozmów dziś. "
                "Dobij bazę — raport trafia właśnie do Head of Recruitment."
            ),
            link="/candidates",
            ntype=NotificationType.powercalling_kpi,
            related_entity_type="user",
            related_entity_id=user_id,
        )
        if result is not None:
            emitted += 1

    # Agregat dla HR-ów — jedna tabelka per dzień.
    hr_rows = await db.execute(
        select(User.id).where(
            User.role == UserRole.head_of_recruitment, User.is_active.is_(True)
        )
    )
    hr_ids = list(hr_rows.scalars().all())
    if hr_ids:
        lines = ["Stan bazy PowerCalling na 11:45:", ""]
        for user_id, name, _ in sorted(
            [(u, n, calls_per_user.get(u, 0)) for u, n in recruiters],
            key=lambda r: r[2],
        ):
            count = calls_per_user.get(user_id, 0)
            marker = "✅" if count >= target else "❌"
            lines.append(f"- {name}: {count}/{target} {marker}")
        message = "\n".join(lines)
        for hr_id in hr_ids:
            result = await emit(
                db,
                user_id=hr_id,
                title="Raport PowerCalling 11:45",
                message=message,
                link="/reports",
                ntype=NotificationType.powercalling_kpi,
                related_entity_type="daily_kpi_report",
                related_entity_id=day_id,
            )
            if result is not None:
                emitted += 1
    return emitted


# ── Trigger 4: CANDIDATE_FEEDBACK_1H ──────────────────────────────────────────


async def check_candidate_feedback_1h(db: AsyncSession, now: datetime) -> int:
    """Call completed 60–75 min temu bez ScreeningNote → alert do rekrutera."""
    now_utc = now.astimezone(timezone.utc)
    lower = now_utc - timedelta(minutes=settings.CANDIDATE_FEEDBACK_AFTER_MINUTES + 15)
    upper = now_utc - timedelta(minutes=settings.CANDIDATE_FEEDBACK_AFTER_MINUTES)

    rows = await db.execute(
        select(Call).where(
            Call.status == CallStatus.completed,
            Call.user_id.isnot(None),
            Call.created_at >= lower,
            Call.created_at <= upper,
        )
    )
    calls = list(rows.scalars().all())
    if not calls:
        return 0

    emitted = 0
    for call in calls:
        note_count = await db.execute(
            select(func.count())
            .select_from(ScreeningNote)
            .where(
                ScreeningNote.candidate_id == call.candidate_id,
                ScreeningNote.author_id == call.user_id,
                ScreeningNote.created_at > call.created_at,
            )
        )
        if (note_count.scalar() or 0) > 0:
            continue
        result = await emit(
            db,
            user_id=call.user_id,
            title="Zapytaj kandydata o feedback",
            message=(
                f"Godzina minęła od rozmowy z kandydatem #{call.candidate_id}. "
                "Dorzuć notatkę ze screeningu — motywacja, red flags, oczekiwania."
            ),
            link=f"/candidates/{call.candidate_id}",
            ntype=NotificationType.candidate_feedback_1h,
            related_entity_type="call",
            related_entity_id=call.id,
        )
        if result is not None:
            emitted += 1
    return emitted


# ── Trigger 5: STAGE_STUCK_7D ─────────────────────────────────────────────────


async def check_stage_stuck_7d(db: AsyncSession, now: datetime) -> int:
    """Kandydat na nieterminalnym etapie od ≥7 dni → alert do rekrutera."""
    latest = await _latest_stage_per_pair(db)
    cutoff = now.astimezone(timezone.utc) - timedelta(
        days=settings.STAGE_STUCK_DAYS
    )
    stale = [
        s
        for s in latest.values()
        if s.stage in _NON_TERMINAL_STAGES and _moved_at_utc(s) <= cutoff
    ]
    if not stale:
        return 0

    jobs = await _jobs_by_id(db, (s.job_id for s in stale))
    emitted = 0
    for stage in stale:
        job = jobs.get(stage.job_id)
        if not job or not job.recruiter_id:
            continue
        days = int((now.astimezone(timezone.utc) - _moved_at_utc(stage)).total_seconds() // 86400)
        result = await emit(
            db,
            user_id=job.recruiter_id,
            title="Kandydat utknął w etapie",
            message=(
                f"Kandydat #{stage.candidate_id} siedzi w etapie "
                f"'{stage.stage.value}' od {days} dni w ofercie "
                f"'{job.title}' (#{job.id}). Zadzwoń i sprawdź czy dalej jest zainteresowany."
            ),
            link=f"/candidates/{stage.candidate_id}",
            ntype=NotificationType.stage_stuck_7d,
            related_entity_type="candidate_stage",
            related_entity_id=stage.id,
        )
        if result is not None:
            emitted += 1
    return emitted


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def run_all_triggers(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Jeden przebieg wszystkich triggerów. Zwraca słownik `{trigger_name: emitted}`."""
    return {
        "dl_stage_stale_6h": await check_dl_stage_stale_6h(db, now),
        "stage_stuck_7d": await check_stage_stuck_7d(db, now),
        "candidate_feedback_1h": await check_candidate_feedback_1h(db, now),
        "powercalling_kpi": await check_powercalling_kpi(db, now),
        "client_feedback_eobd": await check_client_feedback_eobd(db, now),
    }


__all__ = [
    "check_candidate_feedback_1h",
    "check_client_feedback_eobd",
    "check_dl_stage_stale_6h",
    "check_powercalling_kpi",
    "check_stage_stuck_7d",
    "emit",
    "run_all_triggers",
]
