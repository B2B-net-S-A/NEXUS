"""Cykl rozmowy u klienta — agregacja dla ekranu „Rozmowy u klienta” (0338).

Jedna para (kandydat, rekrutacja) przechodzi siedem kroków::

    Sloty (DL) → Wybór terminu (rekruter) → Prep → Prep 2
    → Rozmowa u klienta → Telefon ≤30 min po → Debrief

Moduł ma dwie warstwy:

* ``compute_steps`` / ``compute_todos`` — CZYSTE funkcje na migawce pary
  (``PairSnapshot``). Na nich stoją testy kroków i ta sama logika działa
  niezależnie od tego, skąd przyszły dane.
* ``load_overview`` — hurtowe zapytania (stała liczba, bez N+1) zbierające
  pary w zakresie wołającego.

Zakres „mine” = pary, w których wołający jest rekruterem wniosku o sloty,
właścicielem wydarzenia cyklu albo osobą, która przesunęła kandydata na
„Rozmowa z klientem”. Zakres „jobs” = wszystkie pary w rekrutacjach, do których
należy (DL/TAC/właściciel/współpracownik). „all” = nadzór (admin/HoR).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal, Optional

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    SLOT_STATUS_AWAITING_DL,
    SLOT_STATUS_AWAITING_RECRUITER,
    SLOT_STATUS_CANCELLED,
    SLOT_STATUS_CONFIRMED,
    ClientInterviewSlotRequest,
)
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.debrief_gate import debrief_saved_after_start

Scope = Literal["mine", "jobs", "all"]
StepState = Literal[
    "done", "current", "scheduled", "waiting", "todo", "overdue", "skipped"
]

STEP_KEYS = ("slots", "choice", "prep", "prep2", "interview", "call", "debrief")
STEP_LABELS = {
    "slots": "Terminy od klienta",
    "choice": "Wybór terminu",
    "prep": "Prep",
    "prep2": "Prep 2",
    "interview": "Rozmowa u klienta",
    "call": "Telefon po rozmowie",
    "debrief": "Debrief",
}

# Okno, w którym para „żyje” na ekranie: rozmowy i prepy z ostatnich dwóch
# tygodni (zaległy debrief) i najbliższego miesiąca.
DEFAULT_DAYS_BACK = 14
DEFAULT_DAYS_AHEAD = 30
# Para bez żadnego wydarzenia pokazuje się, gdy przesunięto ją na „Rozmowa
# z klientem” w tym oknie — dłużej wisząca to już nie agenda, tylko pipeline.
STAGE_LOOKBACK_DAYS = 30
MAX_PAIRS = 300


@dataclass(frozen=True)
class EventRef:
    id: int
    start: datetime
    end: Optional[datetime]
    title: str
    status: str
    online_meeting_url: Optional[str] = None
    external_source: Optional[str] = None
    # 0369 — prep założony z NEXUSA (Teams): numer, transkrypt, ocena.
    # Dla prepów spoza NEXUSA wszystko puste, a `ordinal` liczy kolejność.
    prep_no: Optional[int] = None
    ordinal: Optional[int] = None
    transcription_setup: Optional[str] = None
    transcript_status: Optional[str] = None
    review_status: Optional[str] = None
    review_level: Optional[str] = None
    # Organizator (właściciel operacyjny) — adresat zadania „prep słaby”.
    owner_id: Optional[int] = None


def assign_prep_ordinals(preps: list[EventRef]) -> list[EventRef]:
    """Który prep jest Prepem 1, a który Prepem 2.

    Prep z numerem (założony z NEXUSA) trzyma swój numer; pozostałe zajmują
    najniższy wolny numer w kolejności startu. Zwraca listę posortowaną po
    numerze — samotny Prep 2 nie „awansuje” na Prep 1.
    """
    taken = {p.prep_no for p in preps if p.prep_no}
    out: list[EventRef] = []
    next_free = 1
    for p in sorted(preps, key=lambda e: e.start):
        if p.prep_no:
            out.append(replace(p, ordinal=p.prep_no))
            continue
        while next_free in taken:
            next_free += 1
        taken.add(next_free)
        out.append(replace(p, ordinal=next_free))
    return sorted(out, key=lambda e: (e.ordinal or 99, e.start))


@dataclass(frozen=True)
class SlotRef:
    id: int
    status: str
    slots: tuple[dict, ...]
    chosen_index: Optional[int]
    respond_by: Optional[datetime]
    recruiter_id: Optional[int]
    created_by: Optional[int]
    duration_minutes: int
    note: Optional[str]
    event_id: Optional[int]


@dataclass(frozen=True)
class DebriefRef:
    id: int
    overall_impression: Optional[int]
    offer_acceptance: Optional[str]
    acceptance_condition: Optional[str]
    candidate_questions: Optional[str]
    client_questions: Optional[str]


@dataclass
class PairSnapshot:
    candidate_id: int
    job_id: int
    slot_request: Optional[SlotRef] = None
    preps: list[EventRef] = field(default_factory=list)
    interview: Optional[EventRef] = None
    debrief: Optional[DebriefRef] = None
    latest_stage: Optional[str] = None

    def prep_slot(self, n: int) -> Optional[EventRef]:
        """Prep numer ``n``. Powtórzony prep (poprzedni bez nagrania) wygrywa
        z tym, którego nie nagrano — liczy się ostatnia próba."""
        preps = (
            self.preps
            if all(p.ordinal for p in self.preps)
            else assign_prep_ordinals(self.preps)
        )
        matching = [p for p in preps if (p.ordinal or 0) == n]
        if not matching:
            return None
        return max(matching, key=lambda p: (p.transcript_status != "missing", p.start))


LEVEL_LABELS_PL = {"weak": "słaby", "ok": "OK", "good": "dobry"}


def prep_quality(ev: EventRef) -> tuple[Optional[str], Optional[str]]:
    """``(meta, quality)`` odbytego prepu. Prep spoza NEXUSA → brak informacji."""
    status = ev.transcript_status
    if status is None or status == "cancelled":
        return None, None
    if status == "missing":
        return "bez nagrania", "unrecorded"
    if status in ("waiting", "error", "forbidden"):
        return "czeka na transkrypt", "pending"
    if ev.review_status == "ok" and ev.review_level in LEVEL_LABELS_PL:
        return f"ocena: {LEVEL_LABELS_PL[ev.review_level]}", ev.review_level
    return "transkrypt jest, ocena niedostępna", None


def _interview_end(ev: EventRef) -> datetime:
    return ev.end or (ev.start + timedelta(hours=1))


def _step(
    key: str, state: StepState, *, at=None, event_id=None, meta=None, quality=None
) -> dict:
    return {
        "key": key,
        "label": STEP_LABELS[key],
        "state": state,
        "at": at,
        "event_id": event_id,
        "meta": meta,
        "quality": quality,
    }


def compute_steps(
    pair: PairSnapshot, now: datetime, *, call_window_minutes: int
) -> list[dict]:
    """Siedem kroków pary. Stan „current” ma najwyżej jeden krok — pierwszy
    niezamknięty — żeby ekran wiedział, co podświetlić."""
    req = pair.slot_request
    iv = pair.interview
    iv_done = iv is not None and _interview_end(iv) <= now
    steps: list[dict] = []

    # 1. Terminy od klienta
    if req is not None or iv is not None:
        steps.append(_step("slots", "done"))
    else:
        steps.append(_step("slots", "todo"))

    # 2. Wybór terminu
    if iv is not None or (req is not None and req.status == SLOT_STATUS_CONFIRMED):
        steps.append(_step("choice", "done", at=iv.start if iv else None))
    elif req is not None and req.status == SLOT_STATUS_AWAITING_DL:
        chosen = _chosen_slot(req)
        steps.append(
            _step(
                "choice",
                "waiting",
                at=chosen["start"] if chosen else None,
                meta="czeka na potwierdzenie DL u klienta",
            )
        )
    elif req is not None and req.status == SLOT_STATUS_AWAITING_RECRUITER:
        overdue = req.respond_by is not None and req.respond_by < now
        steps.append(
            _step(
                "choice",
                "overdue" if overdue else "todo",
                at=req.respond_by,
                meta=f"{len(req.slots)} terminy do wyboru",
            )
        )
    else:
        steps.append(_step("choice", "todo"))

    # 3–4. Prep i Prep 2 — oba wymagane (0369); po rozmowie już się nie wydarzą.
    for n, key in ((1, "prep"), (2, "prep2")):
        ev = pair.prep_slot(n)
        if ev is not None and ev.start > now:
            meta = (
                "transkrypcja nie włączyła się — włącz ją ręcznie w Teams"
                if ev.transcription_setup == "failed"
                else None
            )
            steps.append(
                _step(key, "scheduled", at=ev.start, event_id=ev.id, meta=meta)
            )
        elif ev is not None:
            meta, quality = prep_quality(ev)
            steps.append(
                _step(
                    key, "done", at=ev.start, event_id=ev.id, meta=meta, quality=quality
                )
            )
        elif iv is not None and iv.start <= now:
            steps.append(_step(key, "skipped"))
        else:
            steps.append(_step(key, "todo"))

    # 5. Rozmowa u klienta
    if iv is None:
        steps.append(_step("interview", "todo"))
    elif iv_done:
        steps.append(_step("interview", "done", at=iv.start, event_id=iv.id))
    else:
        steps.append(_step("interview", "scheduled", at=iv.start, event_id=iv.id))

    # 6–7. Telefon po i debrief
    if iv is None:
        steps.append(_step("call", "todo"))
        steps.append(_step("debrief", "todo"))
    else:
        end = _interview_end(iv)
        deadline = end + timedelta(minutes=call_window_minutes)
        # Debrief przed rozpoczęciem rozmowy nie zamyka kroków — rozmowy
        # jeszcze nie było (zapis blokuje ``PUT …/debrief``).
        if pair.debrief is not None and iv.start <= now:
            steps.append(_step("call", "done", at=end, event_id=iv.id))
            steps.append(_step("debrief", "done", event_id=iv.id))
        elif not iv_done:
            # `at` telefonu to zawsze KONIEC okna („zadzwoń do 13:30”).
            steps.append(_step("call", "todo", at=deadline, event_id=iv.id))
            steps.append(_step("debrief", "todo", event_id=iv.id))
        elif now <= deadline:
            steps.append(_step("call", "current", at=deadline, event_id=iv.id))
            steps.append(_step("debrief", "todo", event_id=iv.id))
        else:
            steps.append(_step("call", "overdue", at=deadline, event_id=iv.id))
            steps.append(_step("debrief", "overdue", event_id=iv.id))

    # Pierwszy niezamknięty krok, który wymaga ruchu, zostaje „current”.
    # Telefon i debrief nie są „bieżące”, zanim rozmowa się zacznie — inaczej
    # karta proponowała „Zapisz debrief” dzień przed rozmową.
    interview_ahead = iv is not None and iv.start > now
    if not any(s["state"] == "current" for s in steps):
        for s in steps:
            if interview_ahead and s["key"] in ("call", "debrief"):
                break
            if s["state"] in ("todo", "overdue", "waiting"):
                if s["state"] == "todo":
                    s["state"] = "current"
                break
    return steps


def current_step_key(steps: list[dict]) -> Optional[str]:
    for s in steps:
        if s["state"] in ("current", "overdue", "waiting"):
            return s["key"]
    for s in steps:
        if s["state"] in ("todo", "scheduled"):
            return s["key"]
    return None


def _chosen_slot(req: SlotRef) -> Optional[dict]:
    if req.chosen_index is None:
        return None
    if 0 <= req.chosen_index < len(req.slots):
        return req.slots[req.chosen_index]
    return None


TodoKind = Literal[
    "call_now",
    "debrief_overdue",
    "slots_pick",
    "slots_confirm",
    "prep_missing",
    "prep2_missing",
    "prep_weak",
    "prep_unrecorded",
    "slots_missing",
]
_TODO_PRIORITY = {
    "call_now": 0,
    "debrief_overdue": 1,
    "slots_pick": 2,
    "slots_confirm": 3,
    "prep_missing": 4,
    "slots_missing": 5,
    "prep2_missing": 6,
    "prep_weak": 6,
    "prep_unrecorded": 7,
}
# Brak prepu tuż przed rozmową u klienta jest pilny (0369).
PREP_URGENT_HOURS = 24


def compute_todos(
    pair: PairSnapshot,
    now: datetime,
    *,
    call_window_minutes: int,
    user_id: int,
    is_dl_view: bool,
) -> list[dict]:
    """Zadania „Do zrobienia” dla pary. Rekruter i DL widzą inne przekazania:
    wybór terminu należy do rekrutera, potwierdzenie u klienta do DL."""
    todos: list[dict] = []
    iv = pair.interview
    req = pair.slot_request

    def add(kind: str, *, due=None, event_id=None, slot_request_id=None, urgent=False):
        todos.append(
            {
                "kind": kind,
                # Pilny brak prepu wskakuje zaraz za telefon po rozmowie.
                "priority": 1 if urgent else _TODO_PRIORITY[kind],
                "candidate_id": pair.candidate_id,
                "job_id": pair.job_id,
                "due": due,
                "event_id": event_id,
                "slot_request_id": slot_request_id,
                "urgent": urgent,
            }
        )

    if iv is not None and pair.debrief is None:
        end = _interview_end(iv)
        deadline = end + timedelta(minutes=call_window_minutes)
        if end <= now <= deadline:
            add("call_now", due=deadline, event_id=iv.id)
        elif deadline < now:
            add("debrief_overdue", due=deadline, event_id=iv.id)

    if req is not None and req.status == SLOT_STATUS_AWAITING_RECRUITER:
        if is_dl_view or req.recruiter_id in (None, user_id):
            add("slots_pick", due=req.respond_by, slot_request_id=req.id)
    if req is not None and req.status == SLOT_STATUS_AWAITING_DL:
        if is_dl_view or req.created_by == user_id:
            chosen = _chosen_slot(req)
            add(
                "slots_confirm",
                due=chosen["start"] if chosen else None,
                slot_request_id=req.id,
            )

    if iv is not None and iv.start > now:
        urgent = iv.start - now <= timedelta(hours=PREP_URGENT_HOURS)
        first, second = pair.prep_slot(1), pair.prep_slot(2)
        # Najpierw Prep 1 — dwa zadania naraz to szum; Prep 2 zawsze (0369).
        if first is None:
            add("prep_missing", due=iv.start, event_id=iv.id, urgent=urgent)
        elif second is None:
            add("prep2_missing", due=iv.start, event_id=iv.id, urgent=urgent)
        for ev in (first, second):
            if ev is None or ev.start > now:
                continue
            _meta, quality = prep_quality(ev)
            if quality == "weak":
                add("prep_weak", due=iv.start, event_id=ev.id)
            elif quality == "unrecorded":
                add("prep_unrecorded", due=iv.start, event_id=ev.id)

    if (
        is_dl_view
        and iv is None
        and req is None
        and pair.latest_stage == PipelineStage.client_interview.value
    ):
        add("slots_missing")
    return todos


# ── Ładowanie ────────────────────────────────────────────────────────────────


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _event_ref(ev: CalendarEvent) -> EventRef:
    return EventRef(
        id=ev.id,
        start=_as_utc(ev.start_time),
        end=_as_utc(ev.end_time) if ev.end_time else None,
        title=ev.title,
        status=ev.status.value if ev.status else "scheduled",
        online_meeting_url=ev.online_meeting_url or ev.teams_link,
        external_source=ev.external_source,
        owner_id=ev.operational_owner_id or ev.created_by,
    )


def slot_ref(req: ClientInterviewSlotRequest) -> SlotRef:
    return SlotRef(
        id=req.id,
        status=req.status,
        slots=tuple(req.slots or ()),
        chosen_index=req.chosen_index,
        respond_by=_as_utc(req.respond_by) if req.respond_by else None,
        recruiter_id=req.recruiter_id,
        created_by=req.created_by,
        duration_minutes=req.duration_minutes,
        note=req.note,
        event_id=req.event_id,
    )


async def _scope_pairs(
    db: AsyncSession,
    user: User,
    scope: Scope,
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> set[tuple[int, int]]:
    """Klucze par w zakresie — trzy źródła, każde jednym zapytaniem."""
    from app.api.recruitment_access import job_scope_clause
    from app.services.workforce_availability import operational_owner_ids

    owners = sorted(operational_owner_ids(user))
    job_filter_events = true()
    job_filter_slots = true()
    job_filter_stages = true()
    if scope == "jobs":
        job_filter_events = job_scope_clause(
            user, CalendarEvent.job_id, oversight_bypass=False
        )
        job_filter_slots = job_scope_clause(
            user, ClientInterviewSlotRequest.job_id, oversight_bypass=False
        )
        job_filter_stages = job_scope_clause(
            user, CandidateStage.job_id, oversight_bypass=False
        )

    pairs: set[tuple[int, int]] = set()

    ev_q = select(CalendarEvent.candidate_id, CalendarEvent.job_id).where(
        CalendarEvent.event_type.in_((EventType.prep_call, EventType.client_interview)),
        CalendarEvent.status != EventStatus.cancelled,
        CalendarEvent.candidate_id.isnot(None),
        CalendarEvent.job_id.isnot(None),
        CalendarEvent.start_time >= window_start,
        CalendarEvent.start_time <= window_end,
        job_filter_events,
    )
    if scope == "mine":
        ev_q = ev_q.where(
            func.coalesce(
                CalendarEvent.operational_owner_id, CalendarEvent.created_by
            ).in_(owners)
        )
    for cid, jid in (await db.execute(ev_q.limit(MAX_PAIRS))).all():
        pairs.add((cid, jid))

    slot_q = select(
        ClientInterviewSlotRequest.candidate_id, ClientInterviewSlotRequest.job_id
    ).where(
        or_(
            ClientInterviewSlotRequest.status.in_(OPEN_SLOT_STATUSES),
            and_(
                ClientInterviewSlotRequest.status == SLOT_STATUS_CONFIRMED,
                ClientInterviewSlotRequest.confirmed_at >= window_start,
            ),
        ),
        job_filter_slots,
    )
    if scope == "mine":
        slot_q = slot_q.where(
            or_(
                ClientInterviewSlotRequest.recruiter_id.in_(owners),
                ClientInterviewSlotRequest.created_by == user.id,
            )
        )
    for cid, jid in (await db.execute(slot_q.limit(MAX_PAIRS))).all():
        pairs.add((cid, jid))

    # Najnowszy etap pary = „Rozmowa z klientem”, przesunięty niedawno.
    latest = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.moved_by,
            CandidateStage.moved_at,
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .where(
            CandidateStage.moved_at >= now - timedelta(days=STAGE_LOOKBACK_DAYS),
            job_filter_stages,
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    stage_q = select(latest.c.candidate_id, latest.c.job_id).where(
        latest.c.stage == PipelineStage.client_interview
    )
    if scope == "mine":
        from app.models.recruitment_process import RecruitmentProcess

        owned_process = (
            select(RecruitmentProcess.id)
            .where(
                RecruitmentProcess.candidate_id == latest.c.candidate_id,
                RecruitmentProcess.job_id == latest.c.job_id,
                RecruitmentProcess.owner_user_id.in_(owners),
            )
            .exists()
        )
        stage_q = stage_q.where(or_(latest.c.moved_by.in_(owners), owned_process))
    for cid, jid in (await db.execute(stage_q.limit(MAX_PAIRS))).all():
        pairs.add((cid, jid))
    return pairs


async def load_snapshots(
    db: AsyncSession,
    pairs: Iterable[tuple[int, int]],
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[tuple[int, int], PairSnapshot]:
    """Migawki par — stała liczba zapytań niezależnie od liczby par."""
    keys = sorted(set(pairs))[:MAX_PAIRS]
    snaps = {k: PairSnapshot(candidate_id=k[0], job_id=k[1]) for k in keys}
    if not keys:
        return snaps
    cand_ids = sorted({k[0] for k in keys})
    job_ids = sorted({k[1] for k in keys})

    # Wydarzenia cyklu: prepy i rozmowa u klienta w oknie.
    ev_rows = (
        await db.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.candidate_id.in_(cand_ids),
                CalendarEvent.job_id.in_(job_ids),
                CalendarEvent.event_type.in_(
                    (EventType.prep_call, EventType.client_interview)
                ),
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time >= window_start - timedelta(days=30),
                CalendarEvent.start_time <= window_end,
            )
            .order_by(CalendarEvent.start_time)
        )
    ).scalars()
    interviews: dict[tuple[int, int], CalendarEvent] = {}
    # Poprzednia rozmowa pary — prepy sprzed niej należą do poprzedniej rundy.
    previous: dict[tuple[int, int], CalendarEvent] = {}
    for ev in ev_rows:
        key = (ev.candidate_id, ev.job_id)
        snap = snaps.get(key)
        if snap is None:
            continue
        if ev.event_type == EventType.prep_call:
            snap.preps.append(_event_ref(ev))
        else:
            # Najnowsza rozmowa u klienta — kolejne rundy nadpisują poprzednią.
            if key in interviews:
                previous[key] = interviews[key]
            interviews[key] = ev
    for key, ev in interviews.items():
        snaps[key].interview = _event_ref(ev)
        # Prepy liczą się do TEJ rozmowy: te po niej należą do następnej rundy.
        iv_start = _as_utc(ev.start_time)
        prev = previous.get(key)
        prev_start = _as_utc(prev.start_time) if prev is not None else None
        snaps[key].preps = [
            p
            for p in snaps[key].preps
            if p.start <= iv_start and (prev_start is None or p.start > prev_start)
        ]

    # 0369: stan prepów z NEXUSA (numer, transkrypt, ocena) — jedno zapytanie.
    prep_ids = [p.id for snap in snaps.values() for p in snap.preps]
    if prep_ids:
        from app.models.prep_meeting import PrepMeeting, PrepReview

        info = {
            row.calendar_event_id: row
            for row in (
                await db.execute(
                    select(
                        PrepMeeting.calendar_event_id,
                        PrepMeeting.prep_no,
                        PrepMeeting.transcription_setup,
                        PrepMeeting.transcript_status,
                        PrepReview.status.label("review_status"),
                        PrepReview.level.label("review_level"),
                    )
                    .outerjoin(PrepReview, PrepReview.prep_meeting_id == PrepMeeting.id)
                    .where(PrepMeeting.calendar_event_id.in_(prep_ids))
                )
            ).all()
        }
        for snap in snaps.values():
            snap.preps = [
                replace(
                    p,
                    prep_no=info[p.id].prep_no,
                    transcription_setup=info[p.id].transcription_setup,
                    transcript_status=info[p.id].transcript_status,
                    review_status=info[p.id].review_status,
                    review_level=info[p.id].review_level,
                )
                if p.id in info
                else p
                for p in snap.preps
            ]
    for snap in snaps.values():
        snap.preps = assign_prep_ordinals(snap.preps)

    # Wnioski o sloty: otwarty wygrywa, inaczej najnowszy niezanulowany.
    slot_rows = (
        await db.execute(
            select(ClientInterviewSlotRequest)
            .where(
                ClientInterviewSlotRequest.candidate_id.in_(cand_ids),
                ClientInterviewSlotRequest.job_id.in_(job_ids),
                ClientInterviewSlotRequest.status != SLOT_STATUS_CANCELLED,
            )
            .order_by(ClientInterviewSlotRequest.created_at)
        )
    ).scalars()
    for req in slot_rows:
        snap = snaps.get((req.candidate_id, req.job_id))
        if snap is None:
            continue
        current = snap.slot_request
        if current is None or current.status not in OPEN_SLOT_STATUSES:
            snap.slot_request = slot_ref(req)

    # Debrief: feedback strony kandydata pod rozmową u klienta.
    iv_ids = [s.interview.id for s in snaps.values() if s.interview is not None]
    if iv_ids:
        fb_rows = (
            await db.execute(
                select(InterviewFeedback).where(
                    InterviewFeedback.calendar_event_id.in_(iv_ids),
                    InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
                )
            )
        ).scalars()
        by_event = {fb.calendar_event_id: fb for fb in fb_rows}
        for snap in snaps.values():
            if snap.interview is None:
                continue
            fb = by_event.get(snap.interview.id)
            # Debrief zapisany przed rozpoczęciem rozmowy nie zamyka kroków
            # „Telefon” i „Debrief” — rozmowy jeszcze nie było (lustro bramki
            # w ``debrief_gate``; zapis przed startem blokuje ``PUT …/debrief``).
            if fb is not None and debrief_saved_after_start(
                _as_utc(fb.updated_at) if fb.updated_at else None,
                snap.interview.start,
            ):
                snap.debrief = DebriefRef(
                    id=fb.id,
                    overall_impression=fb.overall_impression,
                    offer_acceptance=fb.offer_acceptance,
                    acceptance_condition=fb.acceptance_condition,
                    candidate_questions=fb.candidate_questions,
                    client_questions=fb.client_questions,
                )

    # Najnowszy etap pary.
    latest = (
        select(CandidateStage.candidate_id, CandidateStage.job_id, CandidateStage.stage)
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .where(
            CandidateStage.candidate_id.in_(cand_ids),
            CandidateStage.job_id.in_(job_ids),
        )
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    for cid, jid, stage in (await db.execute(latest)).all():
        snap = snaps.get((cid, jid))
        if snap is not None:
            snap.latest_stage = stage.value if hasattr(stage, "value") else str(stage)
    return snaps


async def _labels(
    db: AsyncSession, cand_ids: list[int], job_ids: list[int]
) -> tuple[
    dict[int, tuple[Optional[str], Optional[str]]],
    dict[int, tuple[str, Optional[int], Optional[str]]],
]:
    names: dict[int, tuple[Optional[str], Optional[str]]] = {}
    if cand_ids:
        for cid, first, last, email in (
            await db.execute(
                select(
                    Candidate.id, Candidate.name, Candidate.lastname, Candidate.email
                ).where(Candidate.id.in_(cand_ids))
            )
        ).all():
            full = " ".join(part for part in (first, last) if part) or None
            names[cid] = (full, email)
    jobs: dict[int, tuple[str, Optional[int], Optional[str]]] = {}
    if job_ids:
        for jid, title, client_id, client_name in (
            await db.execute(
                select(Job.id, Job.title, Job.client_id, Client.name)
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(job_ids))
            )
        ).all():
            jobs[jid] = (title, client_id, client_name)
    return names, jobs


async def load_overview(
    db: AsyncSession,
    user: User,
    *,
    scope: Scope,
    now: Optional[datetime] = None,
    days_back: int = DEFAULT_DAYS_BACK,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
    can_read_candidates: bool = True,
) -> dict:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=days_back)
    window_end = now + timedelta(days=days_ahead)
    call_window = settings.POST_INTERVIEW_CALL_WINDOW_MINUTES
    pair_keys = await _scope_pairs(
        db, user, scope, window_start=window_start, window_end=window_end, now=now
    )
    snaps = await load_snapshots(
        db, pair_keys, window_start=window_start, window_end=window_end
    )
    names, jobs = await _labels(
        db,
        sorted({k[0] for k in snaps}),
        sorted({k[1] for k in snaps}),
    )
    is_dl_view = scope != "mine"

    items: list[dict] = []
    agenda: list[dict] = []
    todos: list[dict] = []
    for key, snap in snaps.items():
        cid, jid = key
        title, client_id, client_name = jobs.get(jid, (None, None, None))
        # Nazwisko i e-mail tylko dla ról czytających kandydatów. E-mail jest
        # potrzebny do zaproszenia na prep (Teams wysyła je kandydatowi).
        name, email = (
            names.get(cid, (None, None)) if can_read_candidates else (None, None)
        )
        pair_info = {
            "candidate_id": cid,
            "candidate_name": name,
            "candidate_email": email,
            "job_id": jid,
            "job_title": title,
            "client_id": client_id,
            "client_name": client_name,
        }
        steps = compute_steps(snap, now, call_window_minutes=call_window)
        req = snap.slot_request
        items.append(
            {
                **pair_info,
                "steps": steps,
                "current_step": current_step_key(steps),
                "latest_stage": snap.latest_stage,
                "slot_request": _slot_payload(req) if req else None,
                "interview_event_id": snap.interview.id if snap.interview else None,
                "debrief": _debrief_payload(snap.debrief) if snap.debrief else None,
            }
        )
        for t in compute_todos(
            snap,
            now,
            call_window_minutes=call_window,
            user_id=user.id,
            is_dl_view=is_dl_view,
        ):
            todos.append({**t, **pair_info})

        for prep in snap.preps:
            if window_start <= prep.start <= window_end:
                meta, quality = prep_quality(prep)
                agenda.append(
                    {
                        **pair_info,
                        "kind": "prep" if (prep.ordinal or 1) == 1 else "prep2",
                        "start": prep.start,
                        "end": prep.end,
                        "event_id": prep.id,
                        "online_meeting_url": prep.online_meeting_url,
                        "from_nexus": prep.prep_no is not None,
                        "prep_quality": quality,
                        "prep_meta": meta if prep.start <= now else None,
                    }
                )
        iv = snap.interview
        if iv is not None and window_start <= iv.start <= window_end:
            agenda.append(
                {
                    **pair_info,
                    "kind": "interview",
                    "start": iv.start,
                    "end": iv.end,
                    "event_id": iv.id,
                    "online_meeting_url": None,
                }
            )
            end = _interview_end(iv)
            agenda.append(
                {
                    **pair_info,
                    "kind": "call",
                    "start": end,
                    "end": end + timedelta(minutes=call_window),
                    "event_id": iv.id,
                    "online_meeting_url": None,
                    "done": snap.debrief is not None,
                }
            )
        if (
            req is not None
            and req.status == SLOT_STATUS_AWAITING_DL
            and _chosen_slot(req) is not None
        ):
            chosen = _chosen_slot(req)
            agenda.append(
                {
                    **pair_info,
                    "kind": "tentative",
                    "start": chosen["start"],
                    "end": chosen.get("end"),
                    "event_id": None,
                    "slot_request_id": req.id,
                    "online_meeting_url": None,
                }
            )

    def _sort_key(entry: dict):
        start = entry["start"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        return _as_utc(start)

    agenda.sort(key=_sort_key)
    todos.sort(
        key=lambda t: (
            t["priority"],
            _as_utc(t["due"]) if isinstance(t["due"], datetime) else window_end,
        )
    )
    items.sort(
        key=lambda i: (
            STEP_KEYS.index(i["current_step"]) if i["current_step"] else 99,
            i["candidate_name"] or "",
        )
    )
    return {
        "generated_at": now,
        "scope": scope,
        "call_window_minutes": call_window,
        "items": items,
        "agenda": agenda,
        "todos": todos,
        "truncated": len(pair_keys) > MAX_PAIRS,
    }


def _slot_payload(req: SlotRef) -> dict:
    return {
        "id": req.id,
        "status": req.status,
        "slots": list(req.slots),
        "chosen_index": req.chosen_index,
        "respond_by": req.respond_by,
        "recruiter_id": req.recruiter_id,
        "created_by": req.created_by,
        "duration_minutes": req.duration_minutes,
        "note": req.note,
        "event_id": req.event_id,
    }


def _debrief_payload(fb: DebriefRef) -> dict:
    return {
        "id": fb.id,
        "overall_impression": fb.overall_impression,
        "offer_acceptance": fb.offer_acceptance,
        "acceptance_condition": fb.acceptance_condition,
    }


# ── Odznaka na karcie Tablicy (Pipeline v4, 23.09.2026) ─────────────────────
#
# Karta w kolumnie „Rozmowa u klienta” pokazuje JEDNĄ odznakę terminarza —
# najważniejszą rzecz do zrobienia albo wiedzenia. Kolejność:
# telefon po rozmowie > wybór terminu > czeka na DL > zbliżająca się rozmowa
# (z prepem) > debrief zrobiony. Logika stoi na tej samej migawce pary co
# kroki ekranu „Rozmowy u klienta”, więc obie powierzchnie mówią to samo.

BadgeKind = Literal[
    "choose_slot",
    "awaiting_dl",
    "slot",
    "prep_done",
    "prep2",
    "prep_missing",
    "prep_weak",
    "call_due",
    "debrief_done",
]
BadgeTone = Literal["wait", "info", "ok", "urgent"]

# Rozmowy do przodu widoczne na karcie — dalej niż kwartał to już nie terminarz.
BADGE_DAYS_AHEAD = 90
_WEEKDAYS_PL = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")


def _local(dt: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    return _as_utc(dt).astimezone(ZoneInfo(settings.BUSINESS_TZ))


def _when_label(dt: datetime) -> str:
    """„czw 25.09 · 14:00” w strefie biznesowej."""
    local = _local(dt)
    return f"{_WEEKDAYS_PL[local.weekday()]} {local:%d.%m} · {local:%H:%M}"


def _day_label(dt: datetime, now: datetime) -> str:
    """„dziś 14:00” / „jutro” / „czw 25.09” — względem dnia w strefie biznesowej."""
    local = _local(dt)
    days = (local.date() - _local(now).date()).days
    if days == 0:
        return f"dziś {local:%H:%M}"
    if days == 1:
        return "jutro"
    return f"{_WEEKDAYS_PL[local.weekday()]} {local:%d.%m}"


def _proposals_label(count: int) -> str:
    if count == 1:
        return "1 propozycja"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} propozycje"
    return f"{count} propozycji"


def _badge(kind: str, label: str, tone: str, at: Optional[datetime]) -> dict:
    return {
        "kind": kind,
        "label": label,
        "tone": tone,
        "at": _as_utc(at).isoformat() if at is not None else None,
    }


def compute_badge(
    pair: PairSnapshot, now: datetime, *, call_window_minutes: int
) -> Optional[dict]:
    """Najważniejsza odznaka terminarza pary albo ``None`` (nic do pokazania)."""
    iv = pair.interview
    req = pair.slot_request

    if iv is not None and pair.debrief is None:
        end = _interview_end(iv)
        if end <= now:
            deadline = end + timedelta(minutes=call_window_minutes)
            if now <= deadline:
                minutes = int((now - end).total_seconds() // 60)
                label = (
                    "Zadzwoń · zaraz po rozmowie"
                    if minutes < 1
                    else f"Zadzwoń · {minutes} min po rozmowie"
                )
            else:
                label = "Zadzwoń · debrief zaległy"
            return _badge("call_due", label, "urgent", deadline)

    if req is not None and req.status == SLOT_STATUS_AWAITING_RECRUITER:
        overdue = req.respond_by is not None and req.respond_by < now
        return _badge(
            "choose_slot",
            f"Wybierz termin · {_proposals_label(len(req.slots))}",
            "urgent" if overdue else "wait",
            req.respond_by,
        )

    if req is not None and req.status == SLOT_STATUS_AWAITING_DL:
        chosen = _chosen_slot(req)
        start = datetime.fromisoformat(chosen["start"]) if chosen else None
        label = f"Czeka na DL · {_when_label(start)}" if start else "Czeka na DL"
        return _badge("awaiting_dl", label, "wait", start)

    if iv is not None and _interview_end(iv) > now:
        soon = iv.start - now <= timedelta(hours=PREP_URGENT_HOURS)
        past = [p for p in pair.preps if p.start <= now]
        if any(prep_quality(p)[1] == "weak" for p in past) and iv.start > now:
            return _badge(
                "prep_weak",
                f"Prep słaby · rozmowa {_day_label(iv.start, now)}",
                "urgent" if soon else "wait",
                iv.start,
            )
        if (
            soon
            and iv.start > now
            and (pair.prep_slot(1) is None or pair.prep_slot(2) is None)
        ):
            return _badge(
                "prep_missing",
                f"Brak prepu · rozmowa {_day_label(iv.start, now)}",
                "urgent",
                iv.start,
            )
        second = pair.prep_slot(2)
        if second is not None and second.start > now:
            return _badge(
                "prep2", f"Prep 2 {_day_label(second.start, now)}", "info", second.start
            )
        if any(p.start <= now for p in pair.preps):
            return _badge(
                "prep_done", f"{_when_label(iv.start)} · Prep ✓", "ok", iv.start
            )
        return _badge("slot", _when_label(iv.start), "info", iv.start)

    if iv is not None and pair.debrief is not None:
        return _badge("debrief_done", "Debrief ✓", "ok", iv.start)
    return None


async def interview_badges_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_ids: Iterable[int],
    now: Optional[datetime] = None,
) -> dict[int, dict]:
    """Odznaki terminarza dla kart jednej rekrutacji: ``{candidate_id: badge}``.

    Kandydaci bez niczego w cyklu (brak wniosku o terminy, prepu i rozmowy)
    nie mają wpisu. Stała liczba zapytań: jedno wyszukanie kandydatów
    z czymkolwiek w cyklu + migawki (``load_snapshots``) po najwyżej
    ``MAX_PAIRS`` par na paczkę.
    """
    from sqlalchemy import union

    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    window_start = now - timedelta(days=DEFAULT_DAYS_BACK)
    window_end = now + timedelta(days=BADGE_DAYS_AHEAD)

    with_events = select(CalendarEvent.candidate_id).where(
        CalendarEvent.job_id == job_id,
        CalendarEvent.candidate_id.in_(ids),
        CalendarEvent.event_type.in_((EventType.prep_call, EventType.client_interview)),
        CalendarEvent.status != EventStatus.cancelled,
        # To samo okno co `load_snapshots` (cofa start o 30 dni).
        CalendarEvent.start_time >= window_start - timedelta(days=30),
        CalendarEvent.start_time <= window_end,
    )
    with_slots = select(ClientInterviewSlotRequest.candidate_id).where(
        ClientInterviewSlotRequest.job_id == job_id,
        ClientInterviewSlotRequest.candidate_id.in_(ids),
        ClientInterviewSlotRequest.status != SLOT_STATUS_CANCELLED,
    )
    active = sorted(
        {cid for cid in (await db.execute(union(with_events, with_slots))).scalars()}
    )
    if not active:
        return {}

    call_window = settings.POST_INTERVIEW_CALL_WINDOW_MINUTES
    badges: dict[int, dict] = {}
    for offset in range(0, len(active), MAX_PAIRS):
        chunk = active[offset : offset + MAX_PAIRS]
        snaps = await load_snapshots(
            db,
            [(cid, job_id) for cid in chunk],
            window_start=window_start,
            window_end=window_end,
        )
        for (cid, _jid), snap in snaps.items():
            badge = compute_badge(snap, now, call_window_minutes=call_window)
            if badge is not None:
                badges[cid] = badge
    return badges
