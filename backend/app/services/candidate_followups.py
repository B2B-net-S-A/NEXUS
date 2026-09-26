"""Follow-up z kandydatem, gdy klient milczy (0372, decyzje Artura 24.09.2026).

Po wysłaniu CV klient bywa cicho tygodniami, a kandydat nie wie, czy dalej
jest w procesie. Rekruter dzwoni więc co 14 dni („nie mamy jeszcze
odpowiedzi, ale dalej jesteś w procesie”). Kandydat bywa w kilku procesach
naraz u różnych rekruterów — dlatego zadanie należy do OSOBY, nie procesu:
jeden telefon od jednego rekrutera, który mówi o wszystkich procesach.

Reguła (jedno źródło — czytają ją „Czeka na Ciebie”, Tablica, profil, skrót):

1. Proces czeka na klienta, gdy rekrutacja jest opublikowana, najnowszy etap
   pary wpada do kolumny „CV wysłane” albo „Rozmowa u klienta” Tablicy
   (kolumna po NAZWIE etapu, jak na tablicy — „Przepuszczony przez DZ” ma kod
   ``interview``, a jest QC), pierwsze „CV wysłane” pary jest z dnia
   ``CANDIDATE_FOLLOWUP_SINCE`` lub późniejszego (bez historii) i nie ma
   zaplanowanej rozmowy u klienta ani otwartego wniosku o terminy.
2. Cisza klienta w procesie trwa od ostatniego ruchu etapu, końca minionej
   rozmowy u klienta albo wniosku o terminy — co nastąpiło później.
3. Kontakt z kandydatem liczy się od KOGOKOLWIEK: notatka-rozmowa (typ
   telefon/spotkanie/mail, także z Traffita), telefon, wysłany mail, minione
   wydarzenie kalendarza, wynik follow-upu. Zwykła notatka to nie rozmowa.
   To on usuwa duplikaty: gdy jeden rekruter rozmawiał wczoraj, nikt inny
   nie dostaje zadania.
4. Termin = max(najstarsza cisza, ostatni kontakt) + 14 dni. „Nie odebrał”
   przesuwa termin o 2 dni robocze, bez limitu prób i bez zerowania zegara;
   „oddzwoń” ustawia wskazany dzień.
5. Dzwoni rekruter procesu, który zaszedł najdalej (rozmowa u klienta przed
   CV wysłanym); przy remisie ten, który ostatnio rozmawiał z kandydatem,
   potem proces wysłany najwcześniej. Właściciel procesu = pierwszy
   weryfikator pary (jak „Moi ludzie”), w jego braku osoba, która wysłała
   CV, potem prowadzący rekrutację. Zastępstwo z COMPASS przejmuje zadanie,
   nieaktywne konto oddaje je właścicielowi kolejnego procesu, „Zrobię to
   ja” wygrywa na bieżącą rundę.

Lista liczy się przy odczycie — tabela ``candidate_followups`` trzyma tylko
wyniki telefonów, których nie da się wyliczyć.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate
from app.models.candidate_followup import CONTACT_OUTCOMES, CandidateFollowup
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.m365 import Email, EmailDirection
from app.models.note import Note, NoteType
from app.models.pipeline_template import PipelineTemplate
from app.models.user import User, UserRole
from app.services.board_stage_badges import BOARD_COLUMN_ORDER, board_column_for

logger = logging.getLogger(__name__)

WAITING_COLUMNS: frozenset[str] = frozenset({"cv_sent", "client_interview"})
_COLUMN_RANK = {column: rank for rank, column in enumerate(BOARD_COLUMN_ORDER)}
# Otwarty wniosek o terminy = klient właśnie odpowiedział, czekamy na nas.
_OPEN_SLOT_STATUSES = ("awaiting_recruiter", "awaiting_dl")
# Notatki, które są ROZMOWĄ z kandydatem: telefon, spotkanie, mail (także
# z Traffita — „Rozmowa telefoniczna”, „Spotkanie”, „Email”/„Reply”) i wynik
# follow-upu (typ „call”). Zwykła notatka (dodanie do innej rekrutacji
# z komentarzem, uwaga rekrutera) nie ukrywa przypomnienia na 14 dni.
CONTACT_NOTE_TYPES = (NoteType.call, NoteType.meeting, NoteType.email)
# Nieudane połączenia nie są kontaktem. Poczta głosowa też nie — nikt z
# kandydatem nie rozmawiał (audyt 25.09.2026, runda 4).
_FAILED_CALLS = (
    CallStatus.missed,
    CallStatus.failed,
    CallStatus.initiated,
    CallStatus.voicemail,
)
# Admin i Head of Recruitment widzą osoby, dla których nie ma kto zadzwonić.
_OVERSIGHT_ROLES = (UserRole.admin, UserRole.head_of_recruitment)

# Dlaczego dzwoni akurat ta osoba — zdanie w doku i w oknie.
CALLER_REASONS = (
    "furthest",  # prowadzi proces, który zaszedł najdalej
    "recent_contact",  # remis — ostatnio rozmawiał z kandydatem
    "substitute",  # zastępstwo z COMPASS za właściciela procesu
    "next_process",  # właściciel najdalszego procesu jest nieaktywny
    "claim",  # „Zrobię to ja”
    "none",  # nie ma nikogo — widzą admin i HoR
)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def local_date(moment: datetime) -> date:
    return moment.astimezone(_tz()).date()


def add_business_days(moment: datetime, days: int) -> date:
    """Data ``days`` dni roboczych po dniu ``moment`` (święta polskie)."""

    current = local_date(moment)
    remaining = max(days, 0)
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(
            datetime.combine(current, time(12), tzinfo=_tz()), settings.BUSINESS_TZ
        ):
            remaining -= 1
    return current


@dataclass(frozen=True)
class WaitingProcess:
    candidate_id: int
    job_id: int
    job_title: str
    client_id: Optional[int]
    client_name: Optional[str]
    column: str
    stage_name: Optional[str]
    sent_at: datetime
    silent_since: datetime
    owner_id: Optional[int]


@dataclass(frozen=True)
class Contact:
    at: datetime
    by: Optional[int]
    kind: str  # note | call | email | meeting | followup


@dataclass(frozen=True)
class LogEntry:
    user_id: Optional[int]
    outcome: str
    callback_on: Optional[date]
    created_at: datetime


@dataclass
class Followup:
    candidate_id: int
    processes: list[WaitingProcess]
    due_on: date
    caller_id: Optional[int]
    caller_reason: str
    owner_ids: frozenset[int]
    last_contact: Optional[Contact]
    no_answer_count: int = 0
    pending: Optional[str] = None  # no_answer | callback — ostatni wpis rundy
    candidate_name: str = ""
    phone: Optional[str] = None

    @property
    def lead(self) -> WaitingProcess:
        return self.processes[0]

    def state(self, today: date) -> str:
        if self.due_on < today:
            return "overdue"
        if self.due_on == today:
            return "today"
        if self.due_on == today + timedelta(days=1):
            return "tomorrow"
        return "scheduled"

    def overdue_days(self, today: date) -> int:
        return max((today - self.due_on).days, 0)


def _latest(*contacts: Optional[Contact]) -> Optional[Contact]:
    present = [c for c in contacts if c is not None]
    return max(present, key=lambda c: c.at) if present else None


def compute_followup(
    processes: Iterable[WaitingProcess],
    contact: Optional[Contact],
    logs: Iterable[LogEntry],
    *,
    days: int,
    retry_business_days: int,
    is_active: Callable[[int], bool],
    performer: Callable[[int], Optional[int]],
) -> Optional[Followup]:
    """Czysta reguła dla JEDNEGO kandydata (punkty 2–5 z nagłówka modułu)."""

    waiting = list(processes)
    if not waiting:
        return None
    ordered_logs = sorted(logs, key=lambda e: e.created_at)
    followup_contact = next(
        (
            Contact(at=e.created_at, by=e.user_id, kind="followup")
            for e in reversed(ordered_logs)
            if e.outcome in CONTACT_OUTCOMES
        ),
        None,
    )
    contact = _latest(contact, followup_contact)
    contact_at = contact.at if contact is not None else None
    round_logs = [
        e for e in ordered_logs if contact_at is None or e.created_at > contact_at
    ]

    oldest_silence = min(p.silent_since for p in waiting)
    anchor = max(oldest_silence, contact_at) if contact_at else oldest_silence
    due_on = local_date(anchor + timedelta(days=days))
    pending: Optional[str] = None
    last_pending = next(
        (e for e in reversed(round_logs) if e.outcome in ("no_answer", "callback")),
        None,
    )
    if last_pending is not None and last_pending.outcome == "callback":
        due_on = last_pending.callback_on or due_on
        pending = "callback"
    elif last_pending is not None:
        due_on = max(
            due_on, add_business_days(last_pending.created_at, retry_business_days)
        )
        pending = "no_answer"

    contact_by = contact.by if contact is not None else None
    waiting.sort(
        key=lambda p: (
            -_COLUMN_RANK.get(p.column, -1),
            0 if contact_by is not None and p.owner_id == contact_by else 1,
            p.sent_at,
            p.job_id,
        )
    )
    top_rank = _COLUMN_RANK.get(waiting[0].column, -1)
    tied = [p for p in waiting if _COLUMN_RANK.get(p.column, -1) == top_rank]

    caller_id: Optional[int] = None
    reason = "none"
    claim = next((e for e in reversed(round_logs) if e.outcome == "claim"), None)
    if claim is not None and claim.user_id is not None and is_active(claim.user_id):
        caller_id, reason = claim.user_id, "claim"
    else:
        for index, process in enumerate(waiting):
            if process.owner_id is None:
                continue
            candidate = performer(process.owner_id)
            if candidate is None or not is_active(candidate):
                continue
            caller_id = candidate
            if candidate != process.owner_id:
                reason = "substitute"
            elif index > 0 and waiting[0].owner_id is not None:
                reason = "next_process"
            elif (
                len(tied) > 1
                and contact_by is not None
                and process.owner_id == contact_by
                and any(p.owner_id != contact_by for p in tied)
            ):
                reason = "recent_contact"
            else:
                reason = "furthest"
            break

    return Followup(
        candidate_id=waiting[0].candidate_id,
        processes=waiting,
        due_on=due_on,
        caller_id=caller_id,
        caller_reason=reason,
        owner_ids=frozenset(p.owner_id for p in waiting if p.owner_id is not None),
        last_contact=contact,
        no_answer_count=sum(1 for e in round_logs if e.outcome == "no_answer"),
        pending=pending,
    )


# ── Odczyt z bazy ────────────────────────────────────────────────────────

_WAITING_SQL = """
WITH sent AS (
    SELECT cs.candidate_id, cs.job_id, min(cs.moved_at) AS sent_at
      FROM candidate_stages cs
      JOIN jobs j ON j.id = cs.job_id AND j.status = 'published'
       -- Request „Zakończony” w NEXUSIE (status z Traffita zostaje
       -- 'published'): nie dzwonimy z „dalej jesteś w procesie” (audyt 24.09).
       AND j.work_state IS DISTINCT FROM :finished_state
     WHERE cs.stage = 'cv_sent'
       AND cs.moved_at >= :since
       {candidate_filter}
     GROUP BY cs.candidate_id, cs.job_id
),
fresh AS (
    -- Tylko CV wysłane od dnia startu (decyzja Artura 24.09.2026): para
    -- wysłana wcześniej nie wraca, nawet jeśli po starcie ktoś ją ruszył.
    SELECT s.* FROM sent s
     WHERE NOT EXISTS (
        SELECT 1 FROM candidate_stages o
         WHERE o.candidate_id = s.candidate_id AND o.job_id = s.job_id
           AND o.stage = 'cv_sent' AND o.moved_at < :since
     )
),
latest AS (
    SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
           cs.candidate_id, cs.job_id, cs.stage::text AS stage,
           cs.stage_def_id, cs.moved_at, f.sent_at
      FROM candidate_stages cs
      JOIN fresh f ON f.candidate_id = cs.candidate_id AND f.job_id = cs.job_id
     ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
)
SELECT l.candidate_id, l.job_id, l.stage, l.stage_def_id, l.moved_at, l.sent_at,
       COALESCE(j.pipeline_template_id, :default_template_id) AS template_id,
       j.title, j.client_id, cl.name AS client_name, j.recruiter_id,
       (SELECT v.moved_by FROM candidate_stages v
         WHERE v.candidate_id = l.candidate_id AND v.job_id = l.job_id
           AND v.stage = 'verified' AND v.verification_status = 'active'
           AND v.moved_by IS NOT NULL
         ORDER BY v.moved_at, v.id LIMIT 1) AS verifier_id,
       (SELECT s.moved_by FROM candidate_stages s
         WHERE s.candidate_id = l.candidate_id AND s.job_id = l.job_id
           AND s.stage = 'cv_sent' AND s.moved_by IS NOT NULL
         ORDER BY s.moved_at, s.id LIMIT 1) AS sender_id
  FROM latest l
  JOIN jobs j ON j.id = l.job_id
  LEFT JOIN clients cl ON cl.id = j.client_id
"""


def _value(item) -> Optional[str]:
    if item is None:
        return None
    return getattr(item, "value", item)


def _stage_column(
    catalog, template_id, stage_def_id, stage
) -> tuple[Optional[str], Optional[str]]:
    """(kolumna Tablicy, nazwa etapu) — ta sama reguła co tablica."""

    if stage_def_id is None:
        return board_column_for(None, stage), None
    effective = catalog.effective_def_id(template_id, stage_def_id)
    stage_def = catalog.defs.get(effective) if effective is not None else None
    if stage_def is None:
        # Etap bez odpowiednika w szablonie — „poza szablonem”, nie follow-up.
        return None, None
    column = board_column_for(
        stage_def.name,
        stage_def.legacy_enum_value,
        category=_value(stage_def.category),
        terminal_type=_value(getattr(stage_def, "terminal_type", None)),
    )
    return column, stage_def.name


async def _waiting_processes(
    db: AsyncSession, *, now: datetime, candidate_ids: Optional[list[int]]
) -> dict[int, list[WaitingProcess]]:
    from app.services.board_tasks import _catalog  # noqa: PLC0415 — cykl importu

    since = datetime.combine(settings.CANDIDATE_FOLLOWUP_SINCE, time(0), tzinfo=_tz())
    from app.services.request_work_state import FINISHED  # noqa: PLC0415

    params: dict = {"since": since, "finished_state": FINISHED}
    candidate_filter = ""
    if candidate_ids is not None:
        if not candidate_ids:
            return {}
        candidate_filter = "AND cs.candidate_id = ANY(:candidate_ids)"
        params["candidate_ids"] = list(candidate_ids)
    params["default_template_id"] = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    rows = (
        await db.execute(
            text(_WAITING_SQL.format(candidate_filter=candidate_filter)), params
        )
    ).all()
    if not rows:
        return {}
    catalog = await _catalog(db)

    pairs: list[tuple] = []
    for r in rows:
        column, name = _stage_column(catalog, r.template_id, r.stage_def_id, r.stage)
        if column not in WAITING_COLUMNS:
            continue
        pairs.append((r, column, name))
    if not pairs:
        return {}

    cand_ids = sorted({r.candidate_id for r, _, _ in pairs})
    # Runda 8 (R8-N7-1): właściciel procesu = pierwsza AKTYWNA osoba z łańcucha
    # weryfikator → wysyłający CV → prowadzący. Wyłączone konto weryfikatora
    # dawało „nikt nie dzwoni” i sygnał „rezygnuje” wysyłany w próżnię, choć
    # wysyłający albo prowadzący pracują dalej.
    chain_ids = {
        uid
        for r, _, _ in pairs
        for uid in (r.verifier_id, r.sender_id, r.recruiter_id)
        if uid is not None
    }
    active_ids = (
        {
            uid
            for (uid,) in (
                await db.execute(
                    select(User.id).where(
                        User.id.in_(sorted(chain_ids)), User.is_active.is_(True)
                    )
                )
            ).all()
        }
        if chain_ids
        else set()
    )

    def _owner(r) -> Optional[int]:
        chain = [u for u in (r.verifier_id, r.sender_id, r.recruiter_id) if u]
        return next((u for u in chain if u in active_ids), chain[0] if chain else None)

    events = (
        await db.execute(
            select(
                CalendarEvent.candidate_id,
                CalendarEvent.job_id,
                CalendarEvent.start_time,
                CalendarEvent.end_time,
            ).where(
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.candidate_id.in_(cand_ids),
                CalendarEvent.job_id.is_not(None),
            )
        )
    ).all()
    upcoming: set[tuple[int, int]] = set()
    last_interview: dict[tuple[int, int], datetime] = {}
    for cid, jid, start, end in events:
        if start > now:
            upcoming.add((cid, jid))
            continue
        moment = end if end is not None and end <= now else start
        key = (cid, jid)
        if key not in last_interview or moment > last_interview[key]:
            last_interview[key] = moment

    slots = (
        await db.execute(
            select(
                ClientInterviewSlotRequest.candidate_id,
                ClientInterviewSlotRequest.job_id,
                ClientInterviewSlotRequest.status,
                ClientInterviewSlotRequest.created_at,
            ).where(ClientInterviewSlotRequest.candidate_id.in_(cand_ids))
        )
    ).all()
    open_slots: set[tuple[int, int]] = set()
    last_slots: dict[tuple[int, int], datetime] = {}
    for cid, jid, status, created in slots:
        key = (cid, jid)
        if status in _OPEN_SLOT_STATUSES:
            open_slots.add(key)
        if key not in last_slots or created > last_slots[key]:
            last_slots[key] = created

    out: dict[int, list[WaitingProcess]] = {}
    for r, column, name in pairs:
        key = (r.candidate_id, r.job_id)
        # Rozmowa u klienta przed nami albo wniosek o terminy w toku: klient
        # odpowiedział, nie ma czego podtrzymywać.
        if key in upcoming or key in open_slots:
            continue
        signals = [r.moved_at, last_interview.get(key), last_slots.get(key)]
        out.setdefault(r.candidate_id, []).append(
            WaitingProcess(
                candidate_id=r.candidate_id,
                job_id=r.job_id,
                job_title=r.title,
                client_id=r.client_id,
                client_name=r.client_name,
                column=column,
                stage_name=name,
                sent_at=r.sent_at,
                silent_since=max(s for s in signals if s is not None),
                owner_id=_owner(r),
            )
        )
    return out


async def _last_contacts(
    db: AsyncSession, candidate_ids: list[int], *, now: datetime
) -> dict[int, Contact]:
    """Ostatni kontakt kogokolwiek z kandydatem (punkt 3 reguły)."""

    best: dict[int, Contact] = {}

    def offer(cid: int, at: Optional[datetime], by: Optional[int], kind: str) -> None:
        if at is None or at > now:
            return
        current = best.get(cid)
        if current is None or at > current.at:
            best[cid] = Contact(at=at, by=by, kind=kind)

    notes = (
        await db.execute(
            select(Note.candidate_id, Note.created_at, Note.author_id)
            .where(
                Note.candidate_id.in_(candidate_ids),
                Note.note_type.in_(CONTACT_NOTE_TYPES),
            )
            .distinct(Note.candidate_id)
            .order_by(Note.candidate_id, Note.created_at.desc(), Note.id.desc())
        )
    ).all()
    for cid, at, by in notes:
        offer(cid, at, by, "note")

    call_at = func.coalesce(Call.started_at, Call.created_at)
    calls = (
        await db.execute(
            select(Call.candidate_id, call_at, Call.user_id)
            .where(
                Call.candidate_id.in_(candidate_ids),
                Call.status.not_in(_FAILED_CALLS),
            )
            .distinct(Call.candidate_id)
            .order_by(Call.candidate_id, call_at.desc())
        )
    ).all()
    for cid, at, by in calls:
        offer(cid, at, by, "call")

    email_at = func.coalesce(Email.sent_at, Email.received_at)
    emails = (
        await db.execute(
            select(Email.candidate_id, email_at, Email.user_id)
            .where(
                Email.candidate_id.in_(candidate_ids),
                Email.direction == EmailDirection.sent,
                or_(Email.send_state.is_(None), Email.send_state == "sent"),
            )
            .distinct(Email.candidate_id)
            .order_by(Email.candidate_id, email_at.desc())
        )
    ).all()
    for cid, at, by in emails:
        offer(cid, at, by, "email")

    event_by = func.coalesce(
        CalendarEvent.operational_owner_id, CalendarEvent.created_by
    )
    meetings = (
        await db.execute(
            select(CalendarEvent.candidate_id, CalendarEvent.start_time, event_by)
            .where(
                CalendarEvent.candidate_id.in_(candidate_ids),
                CalendarEvent.event_type != EventType.client_interview,
                CalendarEvent.event_type != EventType.deadline,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time <= now,
            )
            .distinct(CalendarEvent.candidate_id)
            .order_by(CalendarEvent.candidate_id, CalendarEvent.start_time.desc())
        )
    ).all()
    for cid, at, by in meetings:
        offer(cid, at, by, "meeting")
    return best


async def _logs(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, list[LogEntry]]:
    rows = (
        await db.scalars(
            select(CandidateFollowup)
            .where(CandidateFollowup.candidate_id.in_(candidate_ids))
            .order_by(CandidateFollowup.created_at, CandidateFollowup.id)
        )
    ).all()
    out: dict[int, list[LogEntry]] = {}
    for row in rows:
        out.setdefault(row.candidate_id, []).append(
            LogEntry(
                user_id=row.user_id,
                outcome=row.outcome,
                callback_on=row.callback_on,
                created_at=row.created_at,
            )
        )
    return out


async def load_followups(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    candidate_ids: Optional[Iterable[int]] = None,
) -> dict[int, Followup]:
    """Follow-upy wszystkich (albo wskazanych) kandydatów czekających na klienta."""

    if not settings.CANDIDATE_FOLLOWUP_ENABLED:
        return {}
    from app.services.workforce_availability import workforce_context  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    ids = sorted(set(candidate_ids)) if candidate_ids is not None else None
    waiting = await _waiting_processes(db, now=now, candidate_ids=ids)
    if not waiting:
        return {}
    cand_ids = sorted(waiting)
    contacts = await _last_contacts(db, cand_ids, now=now)
    logs = await _logs(db, cand_ids)

    workforce = await workforce_context(db)
    owner_ids = {p.owner_id for items in waiting.values() for p in items if p.owner_id}
    people = owner_ids | {workforce.performer(o) for o in owner_ids}
    people |= {e.user_id for items in logs.values() for e in items if e.user_id}
    active = {
        uid
        for (uid,) in (
            await db.execute(
                select(User.id).where(
                    User.id.in_([p for p in people if p is not None]),
                    User.is_active.is_(True),
                )
            )
        ).all()
    }
    candidates = {
        c.id: c
        for c in (
            await db.execute(
                select(
                    Candidate.id, Candidate.name, Candidate.lastname, Candidate.phone
                ).where(Candidate.id.in_(cand_ids))
            )
        ).all()
    }

    out: dict[int, Followup] = {}
    for cid, items in waiting.items():
        followup = compute_followup(
            items,
            contacts.get(cid),
            logs.get(cid, []),
            days=settings.CANDIDATE_FOLLOWUP_DAYS,
            retry_business_days=settings.CANDIDATE_FOLLOWUP_RETRY_BUSINESS_DAYS,
            is_active=lambda uid: uid in active,
            performer=workforce.performer,
        )
        if followup is None:
            continue
        cand = candidates.get(cid)
        if cand is not None:
            followup.candidate_name = (
                " ".join(p for p in (cand.name, cand.lastname) if p) or "Kandydat"
            )
            followup.phone = cand.phone
        out[cid] = followup
    return out


async def load_followups_safely(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    candidate_ids: Optional[Iterable[int]] = None,
) -> dict[int, Followup]:
    """``load_followups`` dla pulpitu i Tablicy: awaria = pusta lista + log.

    Follow-up to dodatek do ekranu, nie jego treść — padnięte zapytanie
    (np. brak tabeli po przegranym zamku w entrypoincie) nie może dawać 500
    całego pulpitu ani tablicy. Savepoint, bo sesja żądania jedzie dalej.
    """

    try:
        async with db.begin_nested():
            return await load_followups(db, now=now, candidate_ids=candidate_ids)
    except Exception:  # noqa: BLE001
        logger.exception("candidate_followups: nie udało się policzyć follow-upów")
        return {}


def today_local(now: Optional[datetime] = None) -> date:
    return local_date(now or datetime.now(timezone.utc))


def _sees_unassigned(user: User) -> bool:
    return user.has_any_role(*_OVERSIGHT_ROLES)


def for_user(
    followups: dict[int, Followup], user: User, *, today: date
) -> list[Followup]:
    """Telefony do zrobienia przez tę osobę — termin do końca jutra."""

    horizon = today + timedelta(days=1)
    rows = [
        f
        for f in followups.values()
        if f.due_on <= horizon
        and (f.caller_id == user.id or (f.caller_id is None and _sees_unassigned(user)))
    ]
    rows.sort(key=lambda f: (f.due_on, f.candidate_name))
    return rows


def others_for_user(
    followups: dict[int, Followup], user: User, *, limit: int = 20
) -> list[Followup]:
    """Kandydaci, u których prowadzisz proces, a dzwoni ktoś inny."""

    rows = [
        f
        for f in followups.values()
        if user.id in f.owner_ids and f.caller_id is not None and f.caller_id != user.id
    ]
    rows.sort(key=lambda f: (f.due_on, f.candidate_name))
    return rows[:limit]


async def user_names(db: AsyncSession, ids: Iterable[Optional[int]]) -> dict[int, str]:
    wanted = sorted({i for i in ids if i is not None})
    if not wanted:
        return {}
    rows = (
        await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    ).all()
    return {uid: name for uid, name in rows}


@dataclass
class DigestCounts:
    due: int = 0
    overdue: int = 0


def digest_counts(
    followups: dict[int, Followup],
    *,
    today: date,
    oversight_ids: Iterable[int] = (),
) -> dict[int, DigestCounts]:
    """Poranny skrót: ile telefonów ma dziś każda osoba (i ile zaległych).

    Follow-up bez dzwoniącego liczy się adminom i Head of Recruitment
    (``oversight_ids``) — ta sama reguła co panel (``_sees_unassigned``).
    Do 25.09.2026 skrót go pomijał, a panel pokazywał (audyt, runda 4).
    """

    oversight = sorted(set(oversight_ids))
    out: dict[int, DigestCounts] = {}
    for f in followups.values():
        if f.due_on > today:
            continue
        recipients = [f.caller_id] if f.caller_id is not None else oversight
        for uid in recipients:
            line = out.setdefault(uid, DigestCounts())
            line.due += 1
            if f.due_on < today:
                line.overdue += 1
    return out


async def oversight_user_ids(db: AsyncSession) -> list[int]:
    """Aktywni admini i Head of Recruitment — odbiorcy follow-upów bez
    dzwoniącego w porannym skrócie (lustro ``_sees_unassigned``)."""

    return list(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(
                        User.role.in_(_OVERSIGHT_ROLES),
                        *(User.roles.contains([r.value]) for r in _OVERSIGHT_ROLES),
                    ),
                )
            )
        ).all()
    )


__all__ = [
    "CALLER_REASONS",
    "WAITING_COLUMNS",
    "Contact",
    "DigestCounts",
    "Followup",
    "LogEntry",
    "WaitingProcess",
    "add_business_days",
    "compute_followup",
    "digest_counts",
    "for_user",
    "load_followups",
    "local_date",
    "others_for_user",
    "oversight_user_ids",
    "today_local",
    "user_names",
]
