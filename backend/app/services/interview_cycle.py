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
należy (DL/TAC/właściciel/współpracownik) ORAZ pary z „mine” — własne zadanie
nie może zniknąć z domyślnego widoku. „all” = nadzór (admin/HoR).
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
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.debrief_gate import (
    debrief_closes_round,
    pick_current_round,
    pick_prep_round,
)
from app.services.job_working_title import job_display_title_expr

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
    # 0370 — prep założony z NEXUSA (Teams): numer, transkrypt, ocena.
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
    # Komentarz kandydata (``concerns``) i jawne „klient nie pytał” — podsumowanie
    # debriefu w doku osoby i w kalendarzu (04.10.2026: zapisany debrief nie
    # był nigdzie widoczny).
    concerns: Optional[str] = None
    no_client_questions: bool = False


@dataclass
class PairSnapshot:
    candidate_id: int
    job_id: int
    slot_request: Optional[SlotRef] = None
    preps: list[EventRef] = field(default_factory=list)
    interview: Optional[EventRef] = None
    debrief: Optional[DebriefRef] = None
    latest_stage: Optional[str] = None
    # Runda do prepów, gdy jest INNA niż ``interview`` (runda do debriefu):
    # runda odbyta bez debriefu + zaplanowana kolejna. Runda 8 (CAL2, decyzja
    # Artura 27.09.2026): zaległy debrief i braki prepów do następnej rundy
    # przypominają się równolegle. ``None`` = obie rundy to ``interview``.
    prep_interview: Optional[EventRef] = None
    prep_round_preps: list[EventRef] = field(default_factory=list)
    # Zaplanowane prepy, które wypadają PO rozmowie, do której miały
    # przygotować (termin rozmowy potwierdzono albo przełożono na wcześniej
    # niż prep). Należą do rundy prepów — do 02.10.2026 nie należały do żadnej,
    # więc ekran prosił o drugi Prep 1, a serwer pozwalał go założyć.
    late_preps: list[EventRef] = field(default_factory=list)

    def for_preps(self) -> "PairSnapshot":
        """Migawka rundy, do której robi się prepy (najbliższa przyszła
        rozmowa, bez przyszłej — bieżąca). Czytają ją zadania „Brak prepu”,
        plakietka prepu na Tablicy i kolejka ``prep_attention``."""
        if self.prep_interview is None:
            return self
        return replace(
            self,
            interview=self.prep_interview,
            preps=self.prep_round_preps,
            debrief=None,
            prep_interview=None,
            prep_round_preps=[],
        )

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

    def late_prep(self, n: int) -> Optional[EventRef]:
        """Zaplanowany prep numer ``n``, który wypada po rozmowie u klienta."""
        matching = [p for p in self.late_preps if (p.ordinal or 0) == n]
        return min(matching, key=lambda p: p.start) if matching else None


LEVEL_LABELS_PL = {"weak": "słaby", "ok": "OK", "good": "dobry"}
LATE_PREP_META = "zaplanowany po rozmowie u klienta — przełóż"


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
    niezamknięty — żeby ekran wiedział, co podświetlić.

    Otwarty wniosek o terminy (rekruter wybiera albo DL potwierdza) po rozmowie,
    która już się odbyła, to NOWA runda (runda 10, F26): kroki opisują ją, nie
    poprzednią rozmowę — inaczej „Wybór terminu” i „Rozmowa” świeciły jako
    zrobione z datą starej rozmowy, a bieżącym krokiem był telefon po niej.
    Zaległy debrief poprzedniej rozmowy zostaje zadaniem (``compute_todos``).
    Gdy kolejna rozmowa jest już zaplanowana (``prep_interview``), kroki
    opisują tę rundę.
    """
    req = pair.slot_request
    iv = pair.interview
    open_request = req is not None and req.status in (
        SLOT_STATUS_AWAITING_RECRUITER,
        SLOT_STATUS_AWAITING_DL,
    )
    if open_request and iv is not None and _interview_end(iv) <= now:
        if pair.prep_interview is not None:
            pair = pair.for_preps()
        else:
            pair = replace(
                pair,
                interview=None,
                preps=[],
                debrief=None,
                prep_interview=None,
                prep_round_preps=[],
                late_preps=[],
            )
        iv = pair.interview
    iv_done = iv is not None and _interview_end(iv) <= now
    steps: list[dict] = []

    # 1. Terminy od klienta
    if req is not None or iv is not None:
        steps.append(_step("slots", "done"))
    else:
        steps.append(_step("slots", "todo"))

    # 2. Wybór terminu — otwarty wniosek wygrywa z zaplanowaną rozmową
    # (nowe terminy = przełożenie albo kolejna runda, runda 10 F26).
    if not open_request and (
        iv is not None or (req is not None and req.status == SLOT_STATUS_CONFIRMED)
    ):
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

    # 3–4. Prep i Prep 2 — oba wymagane (0370); po rozmowie już się nie wydarzą.
    for n, key in ((1, "prep"), (2, "prep2")):
        ev = pair.prep_slot(n)
        # Spóźniony prep dotyczy tylko rundy, której rozmowa jest przed nami.
        late = (
            pair.late_prep(n)
            if ev is None and iv is not None and iv.start > now
            else None
        )
        if late is not None:
            # Prep JEST w kalendarzu, tylko po rozmowie: „po terminie”
            # z akcją „Przełóż”, nie „Zaplanuj” (drugi byłby duplikatem).
            steps.append(
                _step(
                    key,
                    "overdue",
                    at=late.start,
                    event_id=late.id,
                    meta=LATE_PREP_META,
                )
            )
        elif ev is not None and ev.start > now:
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
    "prep_late",
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
    "prep_late": 4,
    "slots_missing": 5,
    "prep2_missing": 6,
    "prep_weak": 6,
    "prep_unrecorded": 7,
}
# Brak prepu tuż przed rozmową u klienta jest pilny (0370).
PREP_URGENT_HOURS = 24


def compute_todos(
    pair: PairSnapshot,
    now: datetime,
    *,
    call_window_minutes: int,
    user_id: int,
    is_dl_view: bool,
    acting_for: Optional[Iterable[int]] = None,
) -> list[dict]:
    """Zadania „Do zrobienia” dla pary. Rekruter i DL widzą inne przekazania:
    wybór terminu należy do rekrutera, potwierdzenie u klienta do DL.

    ``acting_for`` = osoby, za które wołający pracuje (``operational_owner_ids``
    — on sam i zastępowani z COMPASS-a). Runda 8 (R8-N9-6): zastępca widział
    parę w zakresie „mine”, ale nie dostawał „Wybierz termin” ani „Potwierdź”.
    """
    me = set(acting_for) if acting_for is not None else {user_id}
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
        if is_dl_view or req.recruiter_id is None or req.recruiter_id in me:
            add("slots_pick", due=req.respond_by, slot_request_id=req.id)
    if req is not None and req.status == SLOT_STATUS_AWAITING_DL:
        if is_dl_view or req.created_by in me:
            chosen = _chosen_slot(req)
            add(
                "slots_confirm",
                due=chosen["start"] if chosen else None,
                slot_request_id=req.id,
            )

    # Prepy liczą się do rundy prepów (``for_preps``), nie do rundy czekającej
    # na debrief — oba przypomnienia idą równolegle (runda 8, CAL2).
    prep_round = pair.for_preps()
    prep_iv = prep_round.interview
    if prep_iv is not None and prep_iv.start > now:
        urgent = prep_iv.start - now <= timedelta(hours=PREP_URGENT_HOURS)
        first, second = prep_round.prep_slot(1), prep_round.prep_slot(2)
        # Najpierw Prep 1 — dwa zadania naraz to szum; Prep 2 zawsze (0370).
        # Prep zaplanowany PO rozmowie nie jest brakiem terminu: zadaniem jest
        # go przełożyć, a „Zaplanuj” założyłoby drugi w kalendarzu organizatora
        # i kandydata.
        if first is None:
            if prep_round.late_prep(1) is None:
                add(
                    "prep_missing",
                    due=prep_iv.start,
                    event_id=prep_iv.id,
                    urgent=urgent,
                )
        elif second is None and prep_round.late_prep(2) is None:
            add("prep2_missing", due=prep_iv.start, event_id=prep_iv.id, urgent=urgent)
        for ev in prep_round.late_preps:
            add("prep_late", due=prep_iv.start, event_id=ev.id, urgent=urgent)
        for ev in (first, second):
            if ev is None or ev.start > now:
                continue
            _meta, quality = prep_quality(ev)
            if quality == "weak":
                add("prep_weak", due=prep_iv.start, event_id=ev.id)
            elif quality == "unrecorded":
                add("prep_unrecorded", due=prep_iv.start, event_id=ev.id)

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

    from app.models.recruitment_process import RecruitmentProcess

    owners = sorted(operational_owner_ids(user))

    def in_scope(job_col, mine):
        """„mine” = własne pary; „jobs” = pary moich rekrutacji ORAZ własne.

        Zgłoszenie 02.10.2026: osoba z rolą TAC (ekran startuje w „Moje
        rekrutacje”) dostała dzwonek „Terminy rozmowy od klienta” jako rekruter
        kandydata w cudzej rekrutacji. Zakres rekrutacji tej pary nie zawierał,
        więc tablica była pusta, a link z dzwonka mówił „nie ma w Twoim
        zakresie” — choć zadanie było jej. Domyślny widok nie może chować
        zadania przypisanego osobie imiennie.
        """
        if scope == "mine":
            return mine
        if scope == "jobs":
            return or_(job_scope_clause(user, job_col, oversight_bypass=False), mine)
        return true()

    pairs: set[tuple[int, int]] = set()

    ev_q = select(CalendarEvent.candidate_id, CalendarEvent.job_id).where(
        CalendarEvent.event_type.in_((EventType.prep_call, EventType.client_interview)),
        CalendarEvent.status != EventStatus.cancelled,
        CalendarEvent.candidate_id.isnot(None),
        CalendarEvent.job_id.isnot(None),
        CalendarEvent.start_time >= window_start,
        CalendarEvent.start_time <= window_end,
        in_scope(
            CalendarEvent.job_id,
            func.coalesce(
                CalendarEvent.operational_owner_id, CalendarEvent.created_by
            ).in_(owners),
        ),
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
        in_scope(
            ClientInterviewSlotRequest.job_id,
            or_(
                ClientInterviewSlotRequest.recruiter_id.in_(owners),
                ClientInterviewSlotRequest.created_by == user.id,
            ),
        ),
    )
    for cid, jid in (await db.execute(slot_q.limit(MAX_PAIRS))).all():
        pairs.add((cid, jid))

    # Najnowszy etap pary = „Rozmowa z klientem”, przesunięty niedawno.
    # Zakres nakładamy na najnowszy wiersz pary (wszystkie jej wiersze mają
    # tę samą rekrutację, więc wynik jest ten sam, co przy filtrze w środku).
    latest = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
            CandidateStage.moved_by,
            CandidateStage.moved_at,
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .where(CandidateStage.moved_at >= now - timedelta(days=STAGE_LOOKBACK_DAYS))
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    owned_process = (
        select(RecruitmentProcess.id)
        .where(
            RecruitmentProcess.candidate_id == latest.c.candidate_id,
            RecruitmentProcess.job_id == latest.c.job_id,
            RecruitmentProcess.owner_user_id.in_(owners),
        )
        .exists()
    )
    stage_q = select(latest.c.candidate_id, latest.c.job_id).where(
        latest.c.stage == PipelineStage.client_interview,
        # Runda 8 (R8-N9-5): import Traffita dopisuje etap „Rozmowa z klientem”
        # rekrutacjom-archiwum i zamkniętym — to nie jest praca DL-a, więc
        # bez „Brak terminów od klienta” dla nich. Pary z wydarzeniami
        # i wnioskami o terminy (źródła wyżej) zostają bez zmian.
        latest.c.job_id.in_(select(Job.id).where(Job.status == JobStatus.published)),
        in_scope(
            latest.c.job_id,
            or_(latest.c.moved_by.in_(owners), owned_process),
        ),
    )
    for cid, jid in (await db.execute(stage_q.limit(MAX_PAIRS))).all():
        pairs.add((cid, jid))
    return pairs


async def load_snapshots(
    db: AsyncSession,
    pairs: Iterable[tuple[int, int]],
    *,
    window_start: datetime,
    window_end: datetime,
    now: Optional[datetime] = None,
) -> dict[tuple[int, int], PairSnapshot]:
    """Migawki par — stała liczba zapytań niezależnie od liczby par.

    ``now`` rozstrzyga, która runda rozmów jest bieżąca (``pick_current_round``)
    — wołający podaje ten sam zegar, którym liczy kroki i zadania.
    """
    keys = sorted(set(pairs))[:MAX_PAIRS]
    snaps = {k: PairSnapshot(candidate_id=k[0], job_id=k[1]) for k in keys}
    if not keys:
        return snaps
    cand_ids = sorted({k[0] for k in keys})
    job_ids = sorted({k[1] for k in keys})

    # Wydarzenia cyklu: prepy w oknie i WSZYSTKIE rozmowy u klienta pary.
    # Runda 8 (CAL2): rozmowy bez okna, jak bramka debriefu (``missing_debrief``)
    # — inaczej rozmowa sprzed 44 dni bez debriefu blokowała ruch karty, a ekran
    # jej nie widział i wskazywał inną rundę.
    ev_rows = (
        await db.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.candidate_id.in_(cand_ids),
                CalendarEvent.job_id.in_(job_ids),
                CalendarEvent.status != EventStatus.cancelled,
                or_(
                    CalendarEvent.event_type == EventType.client_interview,
                    and_(
                        CalendarEvent.event_type == EventType.prep_call,
                        CalendarEvent.start_time >= window_start - timedelta(days=30),
                        CalendarEvent.start_time <= window_end,
                    ),
                ),
            )
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
        )
    ).scalars()
    interviews: dict[tuple[int, int], list[CalendarEvent]] = {}
    for ev in ev_rows:
        key = (ev.candidate_id, ev.job_id)
        snap = snaps.get(key)
        if snap is None:
            continue
        if ev.event_type == EventType.prep_call:
            snap.preps.append(_event_ref(ev))
        else:
            interviews.setdefault(key, []).append(ev)

    # Debrief: feedback strony kandydata pod rozmowami u klienta — potrzebny
    # już do wyboru bieżącej rundy (runda z debriefem jest zamknięta).
    feedback: dict[int, InterviewFeedback] = {}
    iv_ids = [ev.id for evs in interviews.values() for ev in evs]
    if iv_ids:
        fb_rows = (
            await db.execute(
                select(InterviewFeedback).where(
                    InterviewFeedback.calendar_event_id.in_(iv_ids),
                    InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
                )
            )
        ).scalars()
        feedback = {fb.calendar_event_id: fb for fb in fb_rows}

    def _debrief_of(ev: CalendarEvent) -> Optional[InterviewFeedback]:
        fb = feedback.get(ev.id)
        # Ta sama reguła „runda zamknięta” co bramka (``debrief_closes_round``):
        # debrief kompletny i zapisany po rozpoczęciu rozmowy. Feedback bez
        # pytań klienta (ogólny ``POST /api/interview-feedback``) nie zamyka
        # kroków „Telefon” i „Debrief” — bramka i tak odrzuciłaby ruch karty.
        if fb is not None and debrief_closes_round(
            fb.client_questions,
            fb.no_client_questions,
            _as_utc(fb.updated_at) if fb.updated_at else None,
            _as_utc(ev.start_time),
        ):
            return fb
        return None

    def _round_preps(
        preps: list[EventRef], evs: list[CalendarEvent], index: int
    ) -> list[EventRef]:
        # Prepy liczą się do TEJ rozmowy: te po niej należą do następnej rundy,
        # te sprzed poprzedniej — do poprzedniej.
        iv_start = _as_utc(evs[index].start_time)
        prev_start = _as_utc(evs[index - 1].start_time) if index > 0 else None
        return [
            p
            for p in preps
            if p.start <= iv_start and (prev_start is None or p.start > prev_start)
        ]

    now = _as_utc(now) if now is not None else datetime.now(timezone.utc)

    def _late_preps(
        preps: list[EventRef], evs: list[CalendarEvent], index: int
    ) -> list[EventRef]:
        # Prep po OSTATNIEJ zaplanowanej rozmowie pary nie ma innej rundy, do
        # której mógłby należeć — to spóźniony prep tej rozmowy. Między dwiema
        # rozmowami prep należy do następnej (``_round_preps``), a po rozmowie,
        # która już się odbyła, do kolejnej rundy (jeszcze bez terminu).
        iv_start = _as_utc(evs[index].start_time)
        if index != len(evs) - 1 or iv_start <= now:
            return []
        return [p for p in preps if p.start > iv_start]

    for key, evs in interviews.items():
        # Runda 8 (R8-N9-3): runda do debriefu wg jednej reguły z
        # ``debrief_gate`` (ostatnia rozpoczęta bez debriefu, inaczej
        # najbliższa przyszła) — nie „najpóźniejsza”, bo przy kilku rundach
        # naraz telefon po rundzie, która właśnie minęła, znikał z ekranu.
        index = pick_current_round(
            [(_as_utc(ev.start_time), _debrief_of(ev) is not None) for ev in evs],
            now,
        )
        # Runda 8 (CAL2): prepy zawsze do najbliższej przyszłej rozmowy — obok
        # zaległego debriefu rundy odbytej, nie zamiast niego.
        prep_index = pick_prep_round([_as_utc(ev.start_time) for ev in evs], now)
        current = evs[index]
        snap = snaps[key]
        all_preps = snap.preps
        snap.interview = _event_ref(current)
        snap.preps = _round_preps(all_preps, evs, index)
        if prep_index is not None and prep_index != index:
            snap.prep_interview = _event_ref(evs[prep_index])
            snap.prep_round_preps = _round_preps(all_preps, evs, prep_index)
        if prep_index is not None:
            snap.late_preps = _late_preps(all_preps, evs, prep_index)
        fb = _debrief_of(current)
        if fb is not None:
            snap.debrief = DebriefRef(
                id=fb.id,
                overall_impression=fb.overall_impression,
                offer_acceptance=fb.offer_acceptance,
                acceptance_condition=fb.acceptance_condition,
                candidate_questions=fb.candidate_questions,
                client_questions=fb.client_questions,
                concerns=fb.concerns,
                no_client_questions=bool(fb.no_client_questions),
            )

    # 0370: stan prepów z NEXUSA (numer, transkrypt, ocena) — jedno zapytanie.
    prep_ids = [
        p.id
        for snap in snaps.values()
        for p in (*snap.preps, *snap.prep_round_preps, *snap.late_preps)
    ]
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

        def _with_info(p: EventRef) -> EventRef:
            if p.id not in info:
                return p
            return replace(
                p,
                prep_no=info[p.id].prep_no,
                transcription_setup=info[p.id].transcription_setup,
                transcript_status=info[p.id].transcript_status,
                review_status=info[p.id].review_status,
                review_level=info[p.id].review_level,
            )

        for snap in snaps.values():
            snap.preps = [_with_info(p) for p in snap.preps]
            snap.prep_round_preps = [_with_info(p) for p in snap.prep_round_preps]
            snap.late_preps = [_with_info(p) for p in snap.late_preps]
    for snap in snaps.values():
        snap.preps = assign_prep_ordinals(snap.preps)
        snap.prep_round_preps = assign_prep_ordinals(snap.prep_round_preps)
        if snap.late_preps:
            # Spóźnione prepy numerujemy RAZEM z prepami swojej rundy: prep bez
            # numeru (spoza NEXUSA) nie może zająć numeru prepu, który jest
            # zaplanowany na czas.
            on_time = (
                snap.prep_round_preps if snap.prep_interview is not None else snap.preps
            )
            late_ids = {p.id for p in snap.late_preps}
            snap.late_preps = [
                p
                for p in assign_prep_ordinals([*on_time, *snap.late_preps])
                if p.id in late_ids
            ]

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
                select(Job.id, job_display_title_expr(), Job.client_id, Client.name)
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
        db, pair_keys, window_start=window_start, window_end=window_end, now=now
    )
    names, jobs = await _labels(
        db,
        sorted({k[0] for k in snaps}),
        sorted({k[1] for k in snaps}),
    )
    is_dl_view = scope != "mine"
    from app.services.workforce_availability import operational_owner_ids

    acting_for = operational_owner_ids(user)

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
                "tentative_interview_at": tentative_interview_start(req),
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
            acting_for=acting_for,
        ):
            todos.append({**t, **pair_info})

        # Runda do debriefu i — gdy inna (runda 8, CAL2) — runda do prepów:
        # panel kandydata pokazuje obie rozmowy i prepy do następnej.
        rounds = [(snap.interview, snap.preps, snap.debrief is not None)]
        if snap.prep_interview is not None:
            rounds.append((snap.prep_interview, snap.prep_round_preps, False))
        # Spóźniony prep zostaje na liście „Prepy i rozmowy” pary — z linkiem
        # Teams i szczegółami, żeby dało się go przełożyć albo odwołać.
        agenda.extend(
            _prep_agenda_entry(pair_info, prep, now, late=True)
            for prep in snap.late_preps
            if window_start <= prep.start <= window_end
        )
        for iv, round_preps, debriefed in rounds:
            agenda.extend(
                _prep_agenda_entry(pair_info, prep, now, late=False)
                for prep in round_preps
                if window_start <= prep.start <= window_end
            )
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
                        "done": debriefed,
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


def _prep_agenda_entry(
    pair_info: dict, prep: EventRef, now: datetime, *, late: bool
) -> dict:
    meta, quality = prep_quality(prep)
    return {
        **pair_info,
        "kind": "prep" if (prep.ordinal or 1) == 1 else "prep2",
        "start": prep.start,
        "end": prep.end,
        "event_id": prep.id,
        "online_meeting_url": prep.online_meeting_url,
        "from_nexus": prep.prep_no is not None,
        "prep_quality": quality,
        "prep_meta": meta if prep.start <= now else None,
        "late": late,
    }


def tentative_interview_start(req: Optional[SlotRef]) -> Optional[str]:
    """Termin rozmowy, który jeszcze NIE jest potwierdzony (ISO UTC).

    Wniosek czeka na potwierdzenie DL → termin wybrany z kandydatem; czeka na
    wybór → najwcześniejsza propozycja klienta. Okno „Zaplanuj prep” ostrzega,
    gdy prep wypada po nim: 02.10.2026 Prep 1 zaplanowano dwa dni po obu
    proponowanych terminach, bo okno nie wiedziało o żadnym.
    """
    if req is None:
        return None
    if req.status == SLOT_STATUS_AWAITING_DL:
        chosen = _chosen_slot(req)
        return chosen["start"] if chosen else None
    if req.status == SLOT_STATUS_AWAITING_RECRUITER and req.slots:
        return min(slot["start"] for slot in req.slots)
    return None


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


_IMPRESSION_TO_OUTCOME = {5: "good", 3: "medium", 1: "bad"}


def _debrief_payload(fb: DebriefRef) -> dict:
    questions = [
        line.strip()
        for line in (fb.client_questions or "").splitlines()
        if line.strip()
    ]
    return {
        "id": fb.id,
        "overall_impression": fb.overall_impression,
        "outcome": _IMPRESSION_TO_OUTCOME.get(fb.overall_impression or 0),
        "offer_acceptance": fb.offer_acceptance,
        "acceptance_condition": fb.acceptance_condition,
        "candidate_comment": fb.concerns,
        "questions_count": len(questions),
        "no_client_questions": fb.no_client_questions,
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


def _iso(value) -> Optional[str]:
    """Termin kroku jako ISO UTC (kroki niosą datę albo gotowy napis slotu)."""
    return _as_utc(value).isoformat() if isinstance(value, datetime) else value


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

    # Zbliżająca się rozmowa i jej prepy — runda prepów (runda 8, CAL2): gdy
    # poprzednia runda jeszcze trwa bez debriefu, a kolejna jest zaplanowana,
    # plakietka mówi o prepach do kolejnej.
    if pair.prep_interview is not None:
        pair = pair.for_preps()
        iv = pair.interview
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


# Faza cyklu rozmowy dla reguły „kto ma ruch” (``pipeline_next_action``,
# ``InterviewPhase``) — liczona z TEJ SAMEJ odznaki, więc krok na karcie
# i plakietka terminarza nie mogą się rozjechać. Lustro frontu czyta pola
# ``phase``/``interview_date`` odznaki (``lib/pipeline-next-action.ts``).
_BADGE_PHASE = {
    "choose_slot": "awaiting_recruiter_pick",
    "awaiting_dl": "awaiting_dl_confirm",
    "prep_weak": "scheduled",
    "prep_missing": "scheduled",
    "prep2": "scheduled",
    "prep_done": "scheduled",
    "slot": "scheduled",
    "call_due": "debrief_due",
    "debrief_done": "debriefed",
}


def badge_phase(
    pair: PairSnapshot, badge: Optional[dict]
) -> tuple[Optional[str], Optional[str]]:
    """``(faza, data rozmowy RRRR-MM-DD w strefie biznesowej)`` dla odznaki pary.

    Data tylko dla fazy ``scheduled`` — rozmowa tej rundy, dla której liczy się
    prepy (ta sama, którą pokazuje odznaka).
    """
    if badge is None:
        return (None, None)
    phase = _BADGE_PHASE.get(badge.get("kind"))
    if phase != "scheduled":
        return (phase, None)
    round_pair = pair.for_preps() if pair.prep_interview is not None else pair
    iv = round_pair.interview
    return (phase, _local(iv.start).date().isoformat() if iv is not None else None)


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
        # Okno prepów z `load_snapshots` (cofa start o 30 dni) — decyduje tylko,
        # KTO ma odznakę; rundę migawka wybiera spośród wszystkich rozmów pary.
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
            now=now,
        )
        for (cid, _jid), snap in snaps.items():
            badge = compute_badge(snap, now, call_window_minutes=call_window)
            if badge is not None:
                # Kreski postępu na karcie i sekcja rozmowy w doku osoby —
                # te same kroki co na ekranie „Rozmowy u klienta”; id rozmowy
                # otwiera debrief prosto z doku. ``at`` czyta okno „Zaplanuj
                # prep” w doku (termin rozmowy): bez niego podpowiadało „jutro
                # 10:00” i nie ostrzegało o prepie po rozmowie.
                badge["steps"] = [
                    {"key": s["key"], "state": s["state"], "at": _iso(s["at"])}
                    for s in compute_steps(snap, now, call_window_minutes=call_window)
                ]
                badge["interview_event_id"] = (
                    snap.interview.id if snap.interview is not None else None
                )
                # Dok osoby planuje prep bez ekranu „Rozmowy u klienta”: musi
                # znać termin, który dopiero czeka na potwierdzenie, i prep
                # zaplanowany po rozmowie (wtedy „Przełóż”, nie „Zaplanuj”).
                badge["tentative_interview_at"] = tentative_interview_start(
                    snap.slot_request
                )
                badge["late_prep_event_id"] = (
                    snap.late_preps[0].id if snap.late_preps else None
                )
                # PR 6 (04.10.2026): panel osoby wybiera i potwierdza termin od
                # klienta oraz pokazuje ocenę prepu bez przechodzenia do
                # kalendarza — potrzebuje otwartego wniosku i prepów pary.
                badge["slot_request"] = (
                    _slot_payload(snap.slot_request)
                    if snap.slot_request is not None
                    and snap.slot_request.status != SLOT_STATUS_CANCELLED
                    else None
                )
                badge["preps"] = [
                    {
                        "id": p.id,
                        "prep_no": p.prep_no if p.prep_no is not None else p.ordinal,
                        "start": _iso(p.start),
                        "review_status": p.review_status,
                        "transcript_status": p.transcript_status,
                    }
                    for p in snap.preps
                ]
                # Podsumowanie zapisanego debriefu w doku osoby (04.10.2026):
                # po zapisie przycisk „Zapisz debrief” znikał i nic go nie
                # zastępowało — warunek kandydata był niewidoczny.
                badge["debrief"] = (
                    _debrief_payload(snap.debrief) if snap.debrief else None
                )
                # 05.10.2026: faza cyklu dla kroku na karcie („kto ma ruch”).
                badge["phase"], badge["interview_date"] = badge_phase(snap, badge)
                badges[cid] = badge
    return badges
