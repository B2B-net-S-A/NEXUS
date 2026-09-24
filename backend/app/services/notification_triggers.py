"""
Phase 13 — 5 automatycznych triggerów powiadomień.

Każdy trigger to async funkcja `check_*` uruchamiana z `tasks/triggers_loop.py`
co 5 min. Idempotentność zapewnia unique partial index `ix_notif_dedup_daily`
(user, type, entity, lokalny dzień Warsaw) + `emit()` łapiący IntegrityError.

Triggery:
  1. check_dl_stage_stale_6h     — kandydat w `cv_sent` > 6h bez ruchu → alert do DL.
  2. check_client_feedback_eobd  — o 16:30 dla `client_interview` zakończonego dziś
                                   bez feedbacku (brak ScreeningNote po end_time).
  3. (usunięty 23.09.2026) raport PowerCalling 11:45 — bez telefonii mierzył
     rozmowy, których system nie rejestruje. Typ `powercalling_kpi` zostaje
     dla historycznych powiadomień.
  4. check_candidate_feedback_1h — 60–75 min po Call completed bez ScreeningNote →
                                   alert do rekrutera (Call.user_id).
  5. check_stage_stuck_7d        — kandydat na nieterminalnym etapie 7–30 dni
                                   w otwartej rekrutacji → alert do
                                   Job.recruiter_id, raz na tydzień per etap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

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
from app.models.candidate import Candidate
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.screening_note import ScreeningNote
from app.models.user import User, UserRole
from app.schemas.pipeline import STAGE_LABELS
from app.services.calendar_auto_complete import mark_ended_interviews_completed
from app.services.notification_access import notification_recipient_has_access

logger = logging.getLogger(__name__)

_WARSAW = ZoneInfo("Europe/Warsaw")

# Non-terminal stages — kandydat jest "w grze" i może utknąć. `posting`
# (kandydat z ogłoszenia, nieprzejrzany) świadomie POZA: to poczekalnia, nie
# proces — alert „utknął" na setkach kandydatów z auto-matchu byłby szumem.
_NON_TERMINAL_STAGES: frozenset[PipelineStage] = frozenset(
    s
    for s in PipelineStage
    if s
    not in {
        PipelineStage.posting,
        PipelineStage.hired,
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    }
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

    Odbiorca jest sprawdzany TUTAJ, a nie w każdym triggerze z osobna.

    `emit` jest jedynym wąskim gardłem wszystkich producentów powiadomień, więc
    to jedyne miejsce, którego nie da się obejść przez dopisanie nowego
    triggera. Do 09.2026 nie sprawdzało nic: ani `is_active`, ani polityki
    sekcji. `_delivery_lead_targets` filtrowało aktywność WYŁĄCZNIE na gałęzi
    eskalacji do HoR, a ścieżka podstawowa zwracała `job.delivery_lead_id`
    wprost. Zmierzone na produkcji:

        90 dni:  6 647 z 63 336 powiadomień (10,5%) trafiło na konta NIEAKTYWNE
        stage_stuck_7d, 30 dni:  1 701 do 4 kont nieaktywnych
                                   903 do 3 kont aktywnych   → 65% donikąd

    Konta dezaktywowane odtwarza nocny sync Traffita i nadal bywają
    właścicielami rekrutacji, więc to się nie naprawia samo. Alert był
    zapisywany, liczony jako wysłany i niewidoczny dla kogokolwiek — a dedup
    tygodniowy powodował, że wracał co tydzień w nieskończoność.

    Polityka sekcji jest sprawdzana przy tej samej okazji, bo i tak obowiązuje
    po stronie ODCZYTU (`api/notifications.py` filtruje listę, oba liczniki
    i oznaczanie jako przeczytane). Wiersz, którego adresat nie może zobaczyć,
    był więc dotąd wyłącznie śmieciem w tabeli.

    Zwraca utworzoną Notification lub None (duplikat albo brak adresata).
    """
    if not await notification_recipient_has_access(
        db,
        user_id,
        ntype,
        related_entity_type=related_entity_type,
        link=link,
    ):
        logger.debug(
            "notification skipped: user=%s type=%s — inactive or no access",
            user_id,
            ntype.value,
        )
        return None

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


@dataclass(frozen=True, slots=True)
class LatestStage:
    """Lekki snapshot najnowszego `CandidateStage` dla pary (kandydat, oferta).

    Triggery używają wyłącznie tych pięciu pól. Pełny obiekt ORM ciągnie też
    `notes` (Text) + `scorecard_answers`/`screening_answers` (JSONB) — przy
    ~158k wierszy to setki MB w kontenerze z limitem ~1 GB.
    """

    id: int
    candidate_id: int
    job_id: int
    stage: PipelineStage
    moved_at: datetime


LatestStageMap = dict[tuple[int, int], LatestStage]


async def _latest_stage_per_pair(
    db: AsyncSession,
    latest: Optional[LatestStageMap] = None,
) -> LatestStageMap:
    """Najnowszy stage per (candidate_id, job_id) — dedupe w Postgresie.

    Optymalizacja 2026-07-27: dawniej `select(CandidateStage)` bez `WHERE`
    i bez `LIMIT` (pełna hydratacja ~158k obiektów ORM z JSONB/Text) + dedupe
    pętlą w Pythonie. Ten sam skan mierzono na >15 s (patrz `api/phase3.py`),
    a leciał 2-6× na każdy tick loopa co 5 min — czyli ≥24 pełne skany/h bez
    ani jednego zalogowanego użytkownika.

    Teraz `DISTINCT ON (candidate_id, job_id)` na pięciu kolumnach, obsłużone
    indeksem `ix_analytics_cs_cand_job_moved (candidate_id, job_id, moved_at
    DESC, id DESC)` — ta sama definicja "najnowszego", co widok
    `analytics_current_pipeline` (migracja 0174).

    `latest` — gotowa mapa policzona raz na tick przez `run_all_triggers`.
    Podana => zwracana bez dotykania bazy.
    """
    if latest is not None:
        return latest
    rows = await db.execute(
        select(
            CandidateStage.id,
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.moved_at,
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    return {
        (row.candidate_id, row.job_id): LatestStage(
            id=row.id,
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            stage=row.stage,
            moved_at=row.moved_at,
        )
        for row in rows
    }


async def _open_jobs_by_id(db: AsyncSession, job_ids: Iterable[int]) -> dict[int, Job]:
    """Rekrutacje OPUBLIKOWANE — jedyny zbiór, w którym alert ma adresata.

    JEDEN helper, świadomie: do 09.2026 obok tego stała nieprzefiltrowana
    `_jobs_by_id`, a poprawka z 17.09 (#1593) objęła tylko jedną z dwóch
    ścieżek — mimo że docstring `check_stage_stuck_7d` nazywa siebie „lustrem"
    `check_dl_stage_stale_6h`. Zmierzone tego skutki na produkcji:

        dl_stage_stale_6h   52 263 powiadomień, 30 993 (59,3%) o rekrutacjach
                            ZAMKNIĘTYCH, przeczytane: 1

    Kandydat wiszący w wersji roboczej ani w rekrutacji zamkniętej nie jest
    powodem do przypomnienia — nie ma czego „przepuścić dalej".
    Rozwidlenie było przyczyną, nie jego jedna gałąź: dopóki istnieją dwa
    helpery, następna poprawka znów obejmie tylko jeden.
    """
    from app.models.job import JobStatus

    ids = list({jid for jid in job_ids if jid is not None})
    if not ids:
        return {}
    rows = await db.execute(
        select(Job).where(Job.id.in_(ids), Job.status == JobStatus.published)
    )
    return {j.id: j for j in rows.scalars().all()}


async def _delivery_lead_targets(db: AsyncSession, job: Job) -> list[int]:
    """Do kogo trafia alert DL-owy.

    Primary: `job.delivery_lead_id`. Jeśli NULL → eskalacja do
    `head_of_recruitment` (przełożeni DL-i, którzy mogą przypisać DL), NIE
    fan-out do wszystkich DL-i. Pusta lista = brak alertu.

    Stary fallback rozsyłał do KAŻDEGO aktywnego delivery_lead — przy 3874/3882
    jobach z NULL delivery_lead_id dawało to ~10983×15 ≈ 165k alertów/dzień
    (incydent notifications 2026-05-22).
    """
    if job.delivery_lead_id:
        # Nieaktywny DL = jak brak DL-a (eskalacja do HoR). Inaczej `emit`
        # odrzucał odbiorcę i alert DL-owy przepadał bez śladu.
        active = await db.scalar(
            select(User.is_active).where(User.id == job.delivery_lead_id)
        )
        if active:
            return [job.delivery_lead_id]
    rows = await db.execute(
        select(User.id).where(
            User.roles.contains([UserRole.head_of_recruitment.value]),
            User.is_active.is_(True),
        )
    )
    return list(rows.scalars().all())


def _moved_at_utc(stage: LatestStage) -> datetime:
    """`CandidateStage.moved_at` jako aware UTC."""
    moved = stage.moved_at
    if moved.tzinfo is None:
        return moved.replace(tzinfo=timezone.utc)
    return moved.astimezone(timezone.utc)


# ── Trigger 1: DL_STAGE_STALE_6H ──────────────────────────────────────────────


async def check_dl_stage_stale_6h(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
    """Kandydat w `cv_sent` od ≥6h (ale nie starszy niż MAX_DAYS) → alert do DL."""
    latest = await _latest_stage_per_pair(db, latest)
    now_utc = now.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(hours=settings.DL_STAGE_STALE_HOURS)
    floor = now_utc - timedelta(days=settings.DL_STAGE_STALE_MAX_DAYS)
    # Okno: zaległy ≥6h, ale ≤MAX_DAYS. Bez dolnej granicy historyczny backlog
    # (kandydaci z importów wiszący w cv_sent miesiącami) odpalał alert codziennie
    # — patrz incydent notifications 2026-05-22.
    candidates = [
        s
        for s in latest.values()
        if s.stage == PipelineStage.cv_sent and floor <= _moved_at_utc(s) <= cutoff
    ]
    if not candidates:
        return 0

    jobs = await _open_jobs_by_id(db, (s.job_id for s in candidates))
    emitted = 0
    for stage in candidates:
        job = jobs.get(stage.job_id)
        if not job:
            continue
        targets = await _delivery_lead_targets(db, job)
        if not targets:
            continue
        hours = int(
            (now.astimezone(timezone.utc) - _moved_at_utc(stage)).total_seconds()
            // 3600
        )
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
                link=f"/jobs/{job.id}?candidate={stage.candidate_id}",
                ntype=NotificationType.dl_stage_stale_6h,
                related_entity_type="candidate_stage",
                related_entity_id=stage.id,
            )
            if result is not None:
                emitted += 1
    return emitted


# ── Trigger 2: CLIENT_FEEDBACK_EOBD ───────────────────────────────────────────


async def check_client_feedback_eobd(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
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

    latest = await _latest_stage_per_pair(db, latest)
    emitted = 0
    jobs = await _open_jobs_by_id(db, (e.job_id for e in events))
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
                link=f"/jobs/{job.id}?candidate={event.candidate_id}",
                ntype=NotificationType.client_feedback_eobd,
                related_entity_type="calendar_event",
                related_entity_id=event.id,
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


# ── Trigger: poranny skrót kolejki „Czeka na Ciebie" (0348) ──────────────────

# Pierwszy dzień (lokalny), dla którego skrót już policzono w tym procesie.
# Migawka kolejki to jeden przebieg po etapach opublikowanych rekrutacji —
# liczymy ją RAZ dziennie, a nie co 5 minut; restart procesu powtórzy bieg,
# a duplikat zatrzyma indeks `ix_notif_dedup_daily`.
_BOARD_TASKS_DIGEST_DONE_FOR: Optional[date] = None
BOARD_TASKS_DIGEST_FROM_HOUR = 8
BOARD_TASKS_DIGEST_UNTIL_HOUR = 17


async def check_board_tasks_digest(db: AsyncSession, now: datetime) -> int:
    """Rano JEDEN wpis na osobę: przegląd DL, kolejka Cpro i follow-upy z kandydatami."""

    global _BOARD_TASKS_DIGEST_DONE_FOR
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if not (BOARD_TASKS_DIGEST_FROM_HOUR <= local.hour < BOARD_TASKS_DIGEST_UNTIL_HOUR):
        return 0
    if _BOARD_TASKS_DIGEST_DONE_FOR == local.date():
        return 0

    from app.services import board_tasks, candidate_followups  # noqa: PLC0415

    # Skrót dzieli transakcję z pozostałymi triggerami ticku — jego awaria
    # (savepoint + log) nie może zatrzymać przypomnień o rozmowach i KPI.
    try:
        async with db.begin_nested():
            snapshot = await board_tasks.load_snapshot(db, now=now)
            followups = await candidate_followups.load_followups(db, now=now)
            counts = await board_tasks.digest_counts(
                db,
                snapshot,
                followups=candidate_followups.digest_counts(
                    followups, today=local.date()
                ),
            )
    except Exception:  # noqa: BLE001
        logger.exception("board_tasks_digest: nie udało się policzyć kolejki")
        return 0
    emitted = 0
    for user_id, line in counts.items():
        if line.total == 0:
            continue
        created = await emit(
            db,
            user_id=user_id,
            title="Czeka na Ciebie na Tablicach",
            message=board_tasks.digest_message(line),
            ntype=NotificationType.board_tasks_digest,
            related_entity_type="user",
            related_entity_id=user_id,
            link="/dashboard#czeka-na-ciebie",
        )
        emitted += int(created is not None)
    _BOARD_TASKS_DIGEST_DONE_FOR = local.date()
    return emitted


# ── Trigger: prep wymaga uwagi (0370) ────────────────────────────────────────

# Migawka par z rozmową u klienta w najbliższym tygodniu — liczona najwyżej
# raz na kwadrans, nie co tick.
_PREP_ATTENTION_LAST_RUN: Optional[datetime] = None
PREP_ATTENTION_EVERY = timedelta(minutes=15)


async def _hor_user_ids(db: AsyncSession) -> list[int]:
    rows = await db.execute(
        select(User.id).where(
            User.roles.contains([UserRole.head_of_recruitment.value]),
            User.is_active.is_(True),
        )
    )
    return list(rows.scalars().all())


async def _already_notified(
    db: AsyncSession, *, user_id: int, entity_type: str, entity_id: int
) -> bool:
    """„Raz na sprawę”: ten sam prep/rozmowa nie dzwoni drugi raz w kolejnych dniach."""
    return (
        await db.scalar(
            select(Notification.id)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.prep_attention,
                Notification.related_entity_type == entity_type,
                Notification.related_entity_id == entity_id,
            )
            .limit(1)
        )
    ) is not None


async def check_prep_attention(db: AsyncSession, now: datetime) -> int:
    """Prep słaby / bez nagrania od razu, brak prepu na dobę przed rozmową.

    Do organizatora prepu i każdego Head of Recruitment (decyzja 23.09.2026).
    """
    global _PREP_ATTENTION_LAST_RUN
    if (
        _PREP_ATTENTION_LAST_RUN is not None
        and now - _PREP_ATTENTION_LAST_RUN < PREP_ATTENTION_EVERY
    ):
        return 0
    from app.services import prep_attention  # noqa: PLC0415

    try:
        async with db.begin_nested():
            items = await prep_attention.load_prep_attention(db, now)
            names, titles = await prep_attention.labels(db, items)
            hor = await _hor_user_ids(db)
    except Exception:  # noqa: BLE001 — dzwonek nie może zatrzymać reszty ticku
        logger.exception("prep_attention: nie udało się policzyć prepów")
        return 0
    emitted = 0
    for item in items:
        if item.reason == "missing" and not item.urgent:
            continue
        who = names.get(item.candidate_id, "kandydat")
        what = titles.get(item.job_id, "rekrutacja")
        if item.reason == "missing":
            title = f"Brak Prepu {item.prep_no} przed rozmową u klienta"
            message = f"{who} — {what}: rozmowa u klienta w ciągu doby, a Prepu {item.prep_no} nie ma w kalendarzu."
        elif item.reason == "weak":
            title = f"Prep {item.prep_no} słaby"
            message = f"{who} — {what}: ocena prepu jest słaba. Sprawdź, co zostało do przygotowania przed rozmową u klienta."
        else:
            title = f"Prep {item.prep_no} bez nagrania"
            message = f"{who} — {what}: z prepu nie ma transkryptu, więc nie da się go ocenić."
        recipients = {*hor, *([item.owner_id] if item.owner_id else [])}
        # Brak Prepu 1 i brak Prepu 2 wiszą na tej samej rozmowie — osobny typ
        # encji, żeby jeden dzwonek nie zjadał drugiego.
        entity_type = (
            f"interview_prep{item.prep_no}"
            if item.reason == "missing"
            else "calendar_event"
        )
        for uid in sorted(recipients):
            if await _already_notified(
                db, user_id=uid, entity_type=entity_type, entity_id=item.entity_event_id
            ):
                continue
            created = await emit(
                db,
                user_id=uid,
                title=title,
                message=message,
                ntype=NotificationType.prep_attention,
                related_entity_type=entity_type,
                related_entity_id=item.entity_event_id,
                link=f"/calendar?cycle={item.candidate_id}-{item.job_id}",
            )
            emitted += int(created is not None)
    _PREP_ATTENTION_LAST_RUN = now
    return emitted


# ── Trigger 5: STAGE_STUCK_7D ─────────────────────────────────────────────────


async def check_stage_stuck_7d(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
    """Kandydat na nieterminalnym etapie od 7–30 dni w OTWARTEJ rekrutacji → alert.

    Do 09.2026 trigger nie miał ani dolnej granicy wieku, ani filtra otwartych
    rekrutacji, a dedup był dobowy: każdy kandydat zaległy od miesięcy
    (historyczny import, zamknięte rekrutacje) dostawał nowy wiersz każdego
    dnia — stąd „ponad tysiąc nieprzeczytanych" u rekruterów. Teraz:
    okno ``[now - STAGE_STUCK_MAX_DAYS, now - STAGE_STUCK_DAYS]`` (lustro
    ``check_dl_stage_stale_6h``), tylko rekrutacje niezamknięte i najwyżej
    jedno przypomnienie na etap w tygodniu ISO (Europe/Warsaw).
    """
    latest = await _latest_stage_per_pair(db, latest)
    now_utc = now.astimezone(timezone.utc)
    cutoff = now_utc - timedelta(days=settings.STAGE_STUCK_DAYS)
    floor = now_utc - timedelta(days=settings.STAGE_STUCK_MAX_DAYS)
    stale = [
        s
        for s in latest.values()
        if s.stage in _NON_TERMINAL_STAGES and floor <= _moved_at_utc(s) <= cutoff
    ]
    if not stale:
        return 0

    jobs = await _open_jobs_by_id(db, (s.job_id for s in stale))
    stale = [
        s for s in stale if (job := jobs.get(s.job_id)) is not None and job.recruiter_id
    ]
    if not stale:
        return 0

    # Dedup tygodniowy: indeks `ix_notif_dedup_daily` blokuje tylko ten sam
    # dzień, więc bez tego sprawdzenia etap wisiałby w dzwonku codziennie.
    week_start = _warsaw_week_start_utc(now)
    already = await db.execute(
        select(Notification.user_id, Notification.related_entity_id).where(
            Notification.notification_type == NotificationType.stage_stuck_7d,
            Notification.related_entity_id.in_([s.id for s in stale]),
            Notification.created_at >= week_start,
        )
    )
    reminded_this_week = {(row[0], row[1]) for row in already}

    names = await _candidate_names(db, (s.candidate_id for s in stale))
    emitted = 0
    for stage in stale:
        job = jobs[stage.job_id]
        if (job.recruiter_id, stage.id) in reminded_this_week:
            continue
        days = int((now_utc - _moved_at_utc(stage)).total_seconds() // 86400)
        who = names.get(stage.candidate_id) or "Kandydat"
        label = STAGE_LABELS.get(stage.stage, stage.stage.value)
        result = await emit(
            db,
            user_id=job.recruiter_id,
            title="Kandydat utknął na etapie",
            message=(
                f"{who} od {days} dni na etapie „{label}” w rekrutacji "
                f"„{job.title}” — zadzwoń i sprawdź, czy dalej jest zainteresowany."
            ),
            link=f"/jobs/{job.id}?candidate={stage.candidate_id}",
            ntype=NotificationType.stage_stuck_7d,
            related_entity_type="candidate_stage",
            related_entity_id=stage.id,
        )
        if result is not None:
            emitted += 1
    return emitted


async def _candidate_names(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, str]:
    ids = list(set(candidate_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(Candidate.id, Candidate.name, Candidate.lastname).where(
            Candidate.id.in_(ids)
        )
    )
    return {
        row.id: " ".join(part for part in (row.name, row.lastname) if part).strip()
        for row in rows
    }


def _warsaw_week_start_utc(now: datetime) -> datetime:
    """Początek bieżącego tygodnia ISO (poniedziałek 00:00 Europe/Warsaw) w UTC."""
    local = now.astimezone(_WARSAW)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(timezone.utc)


# ── Trigger 6-8: POST_INTERVIEW reminders (T+15, T+45, T+2h) ─────────────────
#
# Wzorzec: sprawdzamy interview eventy, których `end_time` wypada w okienku
# [T - half_window, T + half_window] minut temu (half_window=7.5 min przy
# loopie 5 min). Rozróżnienie candidate_side / client_side idzie przez
# najnowszy CandidateStage (jak w `check_client_feedback_eobd`).
#
# Pomijamy eventy z już zapisanym feedbackiem tej samej strony (candidate/
# client). Dedupe 1-alert-na-typ-na-dzień daje `ix_notif_dedup_daily`.
#
# Dla client-side (stage=client_interview): alert leci do rekrutera + DL.
# Dla candidate-side (pozostałe nieterminalne etapy): alert leci tylko do
# rekrutera. T+2h zawsze eskaluje do DL i flaguje event `needs_attention`.

_POST_INTERVIEW_WINDOW_MINUTES = 7.5  # half-window przy 5-min loopie
# 0338: rozmowa kandydata U KLIENTA (cykl „Rozmowy u klienta”). Po niej rekruter
# dzwoni do KANDYDATA ≤30 min — to debrief strony kandydata, nie feedback klienta.
_POST_INTERVIEW_EVENT_TYPES = (EventType.interview, EventType.client_interview)


def _post_interview_side(event: CalendarEvent, stage: "LatestStage | None") -> bool:
    """Czy po tym wydarzeniu zbieramy feedback KLIENTA (True) czy kandydata."""
    if event.event_type == EventType.client_interview:
        return False
    return _is_client_side(stage)


def _post_interview_recipients(
    event: CalendarEvent, job: "Job | None", *, client_side: bool
) -> list[int]:
    """Kto dzwoni: przy rozmowie u klienta — rekruter kandydata (właściciel
    wydarzenia z cyklu), w pozostałych — rekruter rekrutacji jak dotąd."""
    recipients: list[int] = []
    if event.event_type == EventType.client_interview:
        owner = event.operational_owner_id or event.created_by
        if owner:
            recipients.append(owner)
        elif job and job.recruiter_id:
            recipients.append(job.recruiter_id)
        return recipients
    if job and job.recruiter_id:
        recipients.append(job.recruiter_id)
    if client_side and job and job.delivery_lead_id:
        recipients.append(job.delivery_lead_id)
    if not recipients and event.created_by:
        # Fallback: twórca eventu, jeśli nie ma job.recruiter_id
        recipients.append(event.created_by)
    return recipients


async def _events_in_post_interview_window(
    db: AsyncSession, now: datetime, offset_minutes: int
) -> list[CalendarEvent]:
    now_utc = now.astimezone(timezone.utc)
    upper = now_utc - timedelta(minutes=offset_minutes - _POST_INTERVIEW_WINDOW_MINUTES)
    lower = now_utc - timedelta(minutes=offset_minutes + _POST_INTERVIEW_WINDOW_MINUTES)
    rows = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.event_type.in_(_POST_INTERVIEW_EVENT_TYPES),
            CalendarEvent.status == EventStatus.completed,
            CalendarEvent.end_time.isnot(None),
            CalendarEvent.end_time >= lower,
            CalendarEvent.end_time <= upper,
            CalendarEvent.candidate_id.isnot(None),
        )
    )
    return list(rows.scalars().all())


async def _feedback_exists(
    db: AsyncSession, event_id: int, source: FeedbackSource
) -> bool:
    res = await db.execute(
        select(func.count())
        .select_from(InterviewFeedback)
        .where(
            InterviewFeedback.calendar_event_id == event_id,
            InterviewFeedback.feedback_source == source,
        )
    )
    return (res.scalar() or 0) > 0


def _is_client_side(stage: LatestStage | None) -> bool:
    return stage is not None and stage.stage == PipelineStage.client_interview


def _post_interview_link(event: CalendarEvent) -> str:
    """Rozmowa u klienta → debrief na ekranie „Rozmowy u klienta” (0338);
    pozostałe rozmowy → dotychczasowe okno feedbacku w siatce tygodnia."""
    if (
        event.event_type == EventType.client_interview
        and event.candidate_id is not None
        and event.job_id is not None
    ):
        return f"/calendar?cycle={event.candidate_id}-{event.job_id}&debrief={event.id}"
    return f"/calendar?event={event.id}&action=feedback"


async def _post_interview_emit(
    db: AsyncSession,
    *,
    event: CalendarEvent,
    recipients: list[int],
    ntype: NotificationType,
    title: str,
    message: str,
) -> int:
    emitted = 0
    for uid in recipients:
        if uid is None:
            continue
        result = await emit(
            db,
            user_id=uid,
            title=title,
            message=message,
            link=_post_interview_link(event),
            ntype=ntype,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
        )
        if result is not None:
            emitted += 1
    return emitted


async def check_post_interview_t15(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
    """15 min po interview bez feedbacku → ping rekruterowi (+ DL dla client-side)."""
    events = await _events_in_post_interview_window(
        db, now, settings.POST_INTERVIEW_T15_MINUTES
    )
    if not events:
        return 0

    latest = await _latest_stage_per_pair(db, latest)
    jobs = await _open_jobs_by_id(db, (e.job_id for e in events))
    emitted = 0
    for event in events:
        stage = latest.get((event.candidate_id, event.job_id))
        client_side = _post_interview_side(event, stage)
        source = (
            FeedbackSource.client_side if client_side else FeedbackSource.candidate_side
        )
        if await _feedback_exists(db, event.id, source):
            continue

        job = jobs.get(event.job_id) if event.job_id else None
        recipients = _post_interview_recipients(event, job, client_side=client_side)

        if event.event_type == EventType.client_interview:
            title = "Zadzwoń do kandydata po rozmowie u klienta"
            message = (
                f"Rozmowa „{event.title}” skończyła się 15 min temu. Zadzwoń do "
                "kandydata i zapisz debrief: jak poszło, jakie były pytania, czy "
                "przyjmie ofertę."
            )
        else:
            side_label = "klienta" if client_side else "kandydata"
            title = "Zadzwoń i zbierz feedback"
            message = (
                f"15 min temu skończył się interview z kandydatem #{event.candidate_id}. "
                f"Zadzwoń do {side_label} i zbierz feedback + pytania."
            )
        emitted += await _post_interview_emit(
            db,
            event=event,
            recipients=recipients,
            ntype=NotificationType.post_interview_t15,
            title=title,
            message=message,
        )
    return emitted


async def check_post_interview_t45(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
    """45 min po interview bez feedbacku → drugi ping do tych samych adresatów."""
    events = await _events_in_post_interview_window(
        db, now, settings.POST_INTERVIEW_T45_MINUTES
    )
    if not events:
        return 0

    latest = await _latest_stage_per_pair(db, latest)
    jobs = await _open_jobs_by_id(db, (e.job_id for e in events))
    emitted = 0
    for event in events:
        stage = latest.get((event.candidate_id, event.job_id))
        client_side = _post_interview_side(event, stage)
        source = (
            FeedbackSource.client_side if client_side else FeedbackSource.candidate_side
        )
        if await _feedback_exists(db, event.id, source):
            continue

        job = jobs.get(event.job_id) if event.job_id else None
        recipients = _post_interview_recipients(event, job, client_side=client_side)

        side_label = "klienta" if client_side else "kandydata"
        emitted += await _post_interview_emit(
            db,
            event=event,
            recipients=recipients,
            ntype=NotificationType.post_interview_t45,
            title="Przypomnienie: feedback po interview",
            message=(
                f"Mija 45 min od rozmowy z kandydatem #{event.candidate_id}. "
                f"Daj znać jak poszło — zadzwoń do {side_label} i zanotuj feedback."
            ),
        )
    return emitted


async def check_post_interview_t2h_escalation(
    db: AsyncSession, now: datetime, latest: Optional[LatestStageMap] = None
) -> int:
    """2h po interview bez feedbacku → eskalacja do DL + czerwona flaga na evencie."""
    events = await _events_in_post_interview_window(
        db, now, settings.POST_INTERVIEW_T2H_MINUTES
    )
    if not events:
        return 0

    latest = await _latest_stage_per_pair(db, latest)
    jobs = await _open_jobs_by_id(db, (e.job_id for e in events))
    emitted = 0
    for event in events:
        stage = latest.get((event.candidate_id, event.job_id))
        client_side = _post_interview_side(event, stage)
        source = (
            FeedbackSource.client_side if client_side else FeedbackSource.candidate_side
        )
        if await _feedback_exists(db, event.id, source):
            continue

        job = jobs.get(event.job_id) if event.job_id else None
        # Flag event (nawet jeśli nie ma DL do notyfikacji — UI zobaczy).
        if not event.needs_attention:
            event.needs_attention = True
            await db.flush()

        targets: list[int] = []
        if job is not None:
            targets = await _delivery_lead_targets(db, job)
        if not targets and event.created_by:
            targets = [event.created_by]

        side_label = "klienta" if client_side else "kandydata"
        emitted += await _post_interview_emit(
            db,
            event=event,
            recipients=targets,
            ntype=NotificationType.post_interview_t2h_escalation,
            title="Eskalacja: brak feedbacku po 2h",
            message=(
                f"Minęły 2 godziny od interview z kandydatem #{event.candidate_id} "
                f"— nadal brakuje feedbacku od {side_label}. "
                "Zajrzyj do karty kandydata i przyciśnij rekrutera."
            ),
        )
    return emitted


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def run_all_triggers(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Jeden przebieg wszystkich triggerów. Zwraca słownik `{trigger_name: emitted}`."""
    # Auto-promote ended interviews scheduled→completed before post-interview
    # triggers read them. Liczymy ile zmieniliśmy do loggingu ale nie raportujemy
    # w output (bo to nie emission).
    await mark_ended_interviews_completed(db, now)

    # Snapshot pipeline'u liczony RAZ na tick i przekazywany w dół. Dawniej
    # każdy z 6 triggerów robił własny pełny skan `candidate_stages` — 6 skanów
    # ~158k wierszy co 5 min, czyli ≥24 pełne skany na godzinę. Teraz jeden.
    latest = await _latest_stage_per_pair(db)

    return {
        "dl_stage_stale_6h": await check_dl_stage_stale_6h(db, now, latest),
        "stage_stuck_7d": await check_stage_stuck_7d(db, now, latest),
        "candidate_feedback_1h": await check_candidate_feedback_1h(db, now),
        "client_feedback_eobd": await check_client_feedback_eobd(db, now, latest),
        "post_interview_t15": await check_post_interview_t15(db, now, latest),
        "post_interview_t45": await check_post_interview_t45(db, now, latest),
        "post_interview_t2h_escalation": await check_post_interview_t2h_escalation(
            db, now, latest
        ),
        "board_tasks_digest": await check_board_tasks_digest(db, now),
        "prep_attention": await check_prep_attention(db, now),
    }


__all__ = [
    "LatestStage",
    "check_board_tasks_digest",
    "LatestStageMap",
    "check_candidate_feedback_1h",
    "check_client_feedback_eobd",
    "check_dl_stage_stale_6h",
    "check_post_interview_t15",
    "check_post_interview_t45",
    "check_post_interview_t2h_escalation",
    "check_prep_attention",
    "check_stage_stuck_7d",
    "emit",
    "run_all_triggers",
]
