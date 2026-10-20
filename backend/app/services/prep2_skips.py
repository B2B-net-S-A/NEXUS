"""Rozmowa u klienta bez Prepu 2 — wyjątek z powodem (0482, 20.10.2026).

Zgłoszenie rekrutera: kandydat czasem nie znajdzie czasu na drugi prep przed
rozmową u klienta. Decyzja Artura: to ma być wyjątek, a nie wymówka, więc
pominięcie:

* da się zapisać tylko tuż przed rozmową (dziś albo w najbliższy dzień
  roboczy), po odbytym Prepie 1, który nie jest słaby ani bez nagrania
  (``interview_cycle.prep2_skip_status``),
* wymaga powodu z listy i telefonu do kandydata przed rozmową (zadanie
  „Telefon przed rozmową” do odhaczenia),
* zostawia ślad: szary krok z powodem i nazwiskiem, plakietka na Tablicy,
  dzwonek do Delivery Leada rekrutacji (licznik),
* liczy się w raporcie „Jakość prepów”; kto w 30 dniach ma ponad 20% rozmów
  bez Prepu 2 (i co najmniej dwie), tego zobaczy Head of Recruitment — raz
  na 30 dni na osobę.

Hamulcem jest pomiar, nie blokada: przy rozmowie jutro rano zgoda kogoś
z góry i tak przyszłaby za późno.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.prep_meeting import Prep2Skip
from app.models.user import User
from app.services import interview_cycle, interview_slots
from app.services.job_working_title import job_display_title_expr

STATS_WINDOW_DAYS = 30
# Próg „za często”: ponad 20% rozmów osoby w 30 dniach i co najmniej dwie —
# jedna z trzech rozmów to jeszcze przypadek, nie nawyk.
THRESHOLD_SHARE = 0.2
THRESHOLD_MIN_SKIPS = 2
# Telefon „przed rozmową” może być też przed chwilą — rekruter zapisuje
# pominięcie zaraz po rozmowie z kandydatem.
CALL_PAST_TOLERANCE = timedelta(hours=2)

# Odmowy z ``prep2_skip_status`` — tekst dla człowieka (422).
BLOCKED_MESSAGES = {
    "not_needed": "Ta rozmowa nie potrzebuje decyzji — Prep 2 jest już "
    "w kalendarzu albo rozmowy nie ma przed nami.",
    "skipped": "Pominięcie Prepu 2 przed tą rozmową jest już zapisane.",
    "prep1_missing": "Najpierw Prep 1 — bez Prepu 2 da się tylko po odbytym Prepie 1.",
    "prep1_weak": "Prep 1 był słaby albo bez nagrania — przed tą rozmową "
    "Prep 2 jest obowiązkowy.",
    "too_early": "Do rozmowy jest więcej niż dzień roboczy — jest czas na Prep 2.",
}


async def _snapshot(
    db: AsyncSession, *, candidate_id: int, job_id: int, now: datetime
) -> interview_cycle.PairSnapshot:
    snaps = await interview_cycle.load_snapshots(
        db,
        [(candidate_id, job_id)],
        window_start=now - timedelta(days=interview_cycle.DEFAULT_DAYS_BACK),
        window_end=now + timedelta(days=interview_cycle.BADGE_DAYS_AHEAD),
        now=now,
    )
    return snaps[(candidate_id, job_id)]


NOT_PAIR_PERSON = (
    "Rozmowę bez Prepu 2 zapisuje rekruter kandydata, prowadzący rozmowę "
    "albo Delivery Lead rekrutacji."
)


async def ensure_skip_editor(
    db: AsyncSession,
    user: User,
    *,
    candidate_id: int,
    job_id: int,
    interview_owner_id: Optional[int],
) -> None:
    """Pominięcie zapisują i odhaczają ludzie pary, nie cały zespół.

    Bramki planowania prepu (``POST /preps``) wpuszczają każdego z dostępem
    do rekrutacji — także Finanse i rekrutera spoza tej rekrutacji (CI
    20.10.2026). Tu decyzja zwalnia z prepu konkretną rozmowę, więc stoją za
    nią: rekruter kandydata, prowadzący rozmowę (właściciel wydarzenia),
    Delivery Lead rekrutacji, ich zastępcy oraz admin i Head of Recruitment —
    ta sama reguła co zmiana prepu (``prep_meetings.user_can_edit_prep``).
    """
    from app.services.prep_meetings import user_can_edit_prep  # noqa: PLC0415

    job = await db.get(Job, job_id)
    pair = (candidate_id, job_id)
    recruiter = (await interview_slots.default_recruiter_ids(db, [pair])).get(pair)
    ids = {
        i
        for i in (
            interview_owner_id,
            job.delivery_lead_id if job is not None else None,
            recruiter,
        )
        if i
    }
    if not user_can_edit_prep(user, ids):
        raise HTTPException(status_code=403, detail=NOT_PAIR_PERSON)


async def create_skip(
    db: AsyncSession,
    *,
    actor: User,
    candidate_id: int,
    job_id: int,
    reason: str,
    reason_note: Optional[str],
    call_at: datetime,
    now: Optional[datetime] = None,
) -> Prep2Skip:
    """Zapisuje pominięcie Prepu 2 przed najbliższą rozmową pary.

    Reguły liczy ta sama migawka co ekran (``prep2_skip_status``), więc
    przycisk i serwer nie mogą się rozjechać.
    """
    now = now or datetime.now(timezone.utc)
    snap = await _snapshot(db, candidate_id=candidate_id, job_id=job_id, now=now)
    upcoming = snap.for_preps().interview
    await ensure_skip_editor(
        db,
        actor,
        candidate_id=candidate_id,
        job_id=job_id,
        interview_owner_id=upcoming.owner_id if upcoming is not None else None,
    )
    status = interview_cycle.prep2_skip_status(snap, now)
    if status != "allowed":
        raise HTTPException(
            status_code=409 if status == "skipped" else 422,
            detail={
                "code": f"PREP2_SKIP_{status.upper()}",
                "message": BLOCKED_MESSAGES[status],
            },
        )
    interview = snap.for_preps().interview
    assert interview is not None  # ``allowed`` = jest rozmowa przed nami
    call_at = call_at if call_at.tzinfo else call_at.replace(tzinfo=timezone.utc)
    if call_at >= interview.start:
        raise HTTPException(
            status_code=422,
            detail="Telefon do kandydata musi być przed rozmową u klienta.",
        )
    if call_at < now - CALL_PAST_TOLERANCE:
        raise HTTPException(
            status_code=422,
            detail="Podaj, kiedy zadzwonisz do kandydata — termin jest w przeszłości.",
        )
    row = Prep2Skip(
        interview_event_id=interview.id,
        candidate_id=candidate_id,
        job_id=job_id,
        reason=reason,
        reason_note=reason_note,
        call_at=call_at,
        created_by=actor.id,
    )
    db.add(row)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail=BLOCKED_MESSAGES["skipped"]
        ) from exc
    return row


async def mark_call_done(
    db: AsyncSession,
    *,
    actor: User,
    skip: Prep2Skip,
    note: Optional[str],
    now: Optional[datetime] = None,
) -> Prep2Skip:
    interview = await db.get(CalendarEvent, skip.interview_event_id)
    await ensure_skip_editor(
        db,
        actor,
        candidate_id=skip.candidate_id,
        job_id=skip.job_id,
        interview_owner_id=(
            (interview.operational_owner_id or interview.created_by)
            if interview is not None
            else None
        ),
    )
    if skip.call_done_at is not None:
        raise HTTPException(
            status_code=409, detail="Telefon przed rozmową jest już odhaczony."
        )
    skip.call_done_at = now or datetime.now(timezone.utc)
    skip.call_done_by = actor.id
    skip.call_note = note
    await db.flush()
    return skip


async def clear_upcoming(
    db: AsyncSession, *, candidate_id: int, job_id: int, now: Optional[datetime] = None
) -> None:
    """Prep 2 jednak w kalendarzu — pominięcie przed przyszłą rozmową znika.

    Inaczej raport liczyłby rozmowę jako „bez Prepu 2”, choć prep się odbył.
    """
    now = now or datetime.now(timezone.utc)
    upcoming = select(CalendarEvent.id).where(
        CalendarEvent.candidate_id == candidate_id,
        CalendarEvent.job_id == job_id,
        CalendarEvent.event_type == EventType.client_interview,
        CalendarEvent.start_time > now,
    )
    await db.execute(
        delete(Prep2Skip).where(Prep2Skip.interview_event_id.in_(upcoming))
    )


# ── Statystyka per osoba (raport i próg) ─────────────────────────────────────


@dataclass
class SkipStat:
    """Rozmowy u klienta osoby (właściciel rozmowy = rekruter) w oknie."""

    owner_id: int
    interviews: int = 0
    with_reason: int = 0
    # Rozmowa się odbyła, prepów było mniej niż dwa i nikt nie zapisał powodu.
    silent: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def share(self) -> float:
        return self.with_reason / self.interviews if self.interviews else 0.0

    @property
    def over_threshold(self) -> bool:
        return self.with_reason >= THRESHOLD_MIN_SKIPS and self.share > THRESHOLD_SHARE


async def skip_stats(
    db: AsyncSession, *, since: datetime, until: datetime, now: datetime
) -> dict[int, SkipStat]:
    owner = func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by)
    interviews = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.candidate_id,
                CalendarEvent.job_id,
                CalendarEvent.start_time,
                owner,
            ).where(
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time >= since,
                CalendarEvent.start_time <= until,
                CalendarEvent.candidate_id.isnot(None),
                CalendarEvent.job_id.isnot(None),
                owner.isnot(None),
            )
        )
    ).all()
    if not interviews:
        return {}
    skips = {
        row.interview_event_id: row.reason
        for row in (
            await db.execute(
                select(Prep2Skip.interview_event_id, Prep2Skip.reason).where(
                    Prep2Skip.interview_event_id.in_([iv[0] for iv in interviews])
                )
            )
        ).all()
    }
    preps: dict[tuple[int, int], list[datetime]] = {}
    for cid, jid, start in (
        await db.execute(
            select(
                CalendarEvent.candidate_id,
                CalendarEvent.job_id,
                CalendarEvent.start_time,
            ).where(
                CalendarEvent.event_type == EventType.prep_call,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time >= since - timedelta(days=30),
                CalendarEvent.start_time <= until,
                CalendarEvent.candidate_id.in_({iv[1] for iv in interviews}),
            )
        )
    ).all():
        preps.setdefault((cid, jid), []).append(_utc(start))

    stats: dict[int, SkipStat] = {}
    for iv_id, cid, jid, start, owner_id in interviews:
        start = _utc(start)
        stat = stats.setdefault(owner_id, SkipStat(owner_id=owner_id))
        stat.interviews += 1
        reason = skips.get(iv_id)
        if reason is not None:
            stat.with_reason += 1
            stat.reasons[reason] = stat.reasons.get(reason, 0) + 1
        elif start <= now:
            before = [
                s
                for s in preps.get((cid, jid), [])
                if start - timedelta(days=30) < s <= start
            ]
            if len(before) < 2:
                stat.silent += 1
    return stats


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Powiadomienia ────────────────────────────────────────────────────────────


async def _pair_labels(db: AsyncSession, skip: Prep2Skip) -> tuple[str, str]:
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == skip.candidate_id
            )
        )
    ).first()
    who = (
        " ".join(p for p in (row[0], row[1]) if p) if row else ""
    ) or f"Kandydat #{skip.candidate_id}"
    title = await db.scalar(
        select(job_display_title_expr()).where(Job.id == skip.job_id)
    )
    return who, title or f"Rekrutacja #{skip.job_id}"


def _link(skip: Prep2Skip) -> str:
    return f"/calendar?cycle={skip.candidate_id}-{skip.job_id}"


async def notify_skip(
    db: AsyncSession, *, actor: User, skip: Prep2Skip, interview_start: datetime
) -> None:
    """Dzwonek do Delivery Leada rekrutacji (licznik, bez dymka)."""
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl
    from app.services.prep_notifications import _short  # noqa: PLC0415

    job = await db.get(Job, skip.job_id)
    if job is None or not job.delivery_lead_id or job.delivery_lead_id == actor.id:
        return
    who, what = await _pair_labels(db, skip)
    reason = interview_cycle.PREP2_SKIP_REASON_LABELS.get(skip.reason, skip.reason)
    if skip.reason == "other" and skip.reason_note:
        reason = skip.reason_note
    await emit(
        db,
        user_id=job.delivery_lead_id,
        title=f"Rozmowa bez Prepu 2 · {_short(interview_start)}",
        message=(
            f"{who} — {what}. {actor.name or 'Rekruter'}: {reason}. "
            f"Zamiast prepu telefon do kandydata {_short(skip.call_at)}."
        ),
        ntype=NotificationType.prep2_skipped,
        related_entity_type="prep2_skip",
        related_entity_id=skip.id,
        link=_link(skip),
    )


async def notify_threshold(
    db: AsyncSession, *, owner_id: int, until: datetime, now: datetime
) -> bool:
    """Head of Recruitment widzi osobę, która za często pomija Prep 2.

    Raz na ``STATS_WINDOW_DAYS`` na osobę — sprawdzane przy każdym zapisie
    pominięcia, więc bez osobnej pętli w tle.
    """
    from app.services.notification_triggers import (  # noqa: PLC0415 — cykl
        _hor_user_ids,
        emit,
    )

    since = now - timedelta(days=STATS_WINDOW_DAYS)
    stat = (await skip_stats(db, since=since, until=until, now=now)).get(owner_id)
    if stat is None or not stat.over_threshold:
        return False
    already = await db.scalar(
        select(Notification.id)
        .where(
            Notification.notification_type == NotificationType.prep2_skip_threshold,
            Notification.related_entity_type == "prep2_skip_owner",
            Notification.related_entity_id == owner_id,
            Notification.created_at >= since,
        )
        .limit(1)
    )
    if already is not None:
        return False
    name = await db.scalar(select(User.name).where(User.id == owner_id)) or (
        f"#{owner_id}"
    )
    reasons = ", ".join(
        f"{interview_cycle.PREP2_SKIP_REASON_LABELS.get(k, k)} ×{v}"
        for k, v in sorted(stat.reasons.items(), key=lambda kv: -kv[1])
    )
    sent = False
    for uid in await _hor_user_ids(db):
        created = await emit(
            db,
            user_id=uid,
            title=f"{name}: {stat.with_reason} z {stat.interviews} rozmów bez Prepu 2",
            message=(
                f"Ostatnie {STATS_WINDOW_DAYS} dni, {round(stat.share * 100)}%. "
                f"Powody: {reasons}. Szczegóły: Insights → Raporty → Jakość prepów."
            ),
            ntype=NotificationType.prep2_skip_threshold,
            related_entity_type="prep2_skip_owner",
            related_entity_id=owner_id,
            link="/insights?tab=raporty&report=prepy",
        )
        sent = sent or created is not None
    return sent
