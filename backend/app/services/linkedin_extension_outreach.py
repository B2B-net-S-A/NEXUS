"""Recruiter Lite we wtyczce (1.0.8, decyzja Artura 12.11.2026).

InMaile, zapisane odpowiedzi, „kto i kiedy się odzywał” na profilu i liście
oraz zestaw do wyszukiwarki Recruitera. Kontrakt: ``extension/API.md`` →
„Recruiter Lite”. Nic tu nie czyta LinkedIna i nic nie wysyła.

Odpowiedź osoby to notatka ``contact_attempt`` ze śladem
``linkedin_extension:reply:<outcome>:<id kontaktu>`` — bez nowej tabeli
i migracji; kontakt, na który odpowiedziano, wynika ze śladu.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import (
    business_date,
    business_today,
    local_day_start_utc,
    local_month_bounds,
)
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.user import User
from app.schemas.linkedin_extension import (
    BatchItem,
    InmailUsageOut,
    LastReplyOut,
    OpenInmailOut,
    OutreachOut,
    SearchKitResponse,
    TeamContactOut,
)
from app.services.canonical_text import _skill_names
from app.services.linkedin_extension_lookup import CHANNEL_LABELS, CONTACT_SOURCE_PREFIX
from app.services.note_kinds import CONTACT_ATTEMPT

REPLY_PREFIX = f"{CONTACT_SOURCE_PREFIX}reply:"
REPLY_OUTCOMES = ("interested", "not_now", "no_reply")
#: Kanały, na które osoba może odpowiedzieć na LinkedInie (telefon nie).
REPLYABLE_CHANNELS = ("inmail", "invitation", "linkedin_message")
INMAIL_REF = f"{CONTACT_SOURCE_PREFIX}inmail"
RECENT_CONTACT_DAYS = 30
#: LinkedIn oddaje kredyt za InMail z odpowiedzią w ciągu 90 dni.
INMAIL_REFUND_DAYS = 90
# Przypomnienie z ``writes.log_contact``: „Odezwij się: <osoba> (LinkedIn)”.
REMINDER_TITLE_LIKE = "Odezwij się:%(LinkedIn)"

_NOTE_TYPE_LABELS = {
    NoteType.call: "telefon",
    NoteType.email: "e-mail",
    NoteType.meeting: "spotkanie",
}
_REPLY_TEXT = {"interested": "chce rozmawiać", "not_now": "nie teraz"}
_REPLY_REF_RE = re.compile(
    r"^linkedin_extension:reply:(interested|not_now|no_reply):(\d+)$"
)
_LOCATION_SPLIT_RE = re.compile(r"\s*(?:[,;]|\s/\s)\s*")
_PLAIN_TERM_RE = re.compile(r"[^\W_]+")


# ── Ślady notatek ────────────────────────────────────────────────────────────


def reply_ref(outcome: str, note_id: int) -> str:
    return f"{REPLY_PREFIX}{outcome}:{note_id}"


def parse_reply_ref(source_ref: Optional[str]) -> Optional[tuple[str, int]]:
    """``(outcome, id kontaktu)`` ze śladu odpowiedzi albo None."""
    match = _REPLY_REF_RE.match(source_ref or "")
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def channel_of(source_ref: Optional[str]) -> Optional[str]:
    """Kanał kontaktu z wtyczki (``inmail``…) albo None dla innych notatek."""
    if not source_ref or not source_ref.startswith(CONTACT_SOURCE_PREFIX):
        return None
    channel = source_ref[len(CONTACT_SOURCE_PREFIX) :]
    return channel if channel in CHANNEL_LABELS else None


def contact_label(
    note_type: Any,
    source_ref: Optional[str],
    origin_refs: Mapping[int, Optional[str]] | None = None,
) -> str:
    """Etykieta kontaktu w panelu. Odpowiedź mówi, na co odpowiedziano
    (``origin_refs`` = id kontaktu → jego ślad)."""
    reply = parse_reply_ref(source_ref)
    if reply is not None:
        outcome, note_id = reply
        if outcome == "no_reply":
            return "brak odpowiedzi"
        channel = channel_of((origin_refs or {}).get(note_id))
        return f"odpowiedź na {CHANNEL_LABELS[channel]}" if channel else "odpowiedź"
    if source_ref and source_ref.startswith(CONTACT_SOURCE_PREFIX):
        return CHANNEL_LABELS.get(source_ref[len(CONTACT_SOURCE_PREFIX) :], "kontakt")
    return _NOTE_TYPE_LABELS.get(note_type, "próba kontaktu")


async def reply_origins(
    db: AsyncSession, source_refs: Iterable[Optional[str]]
) -> dict[int, Optional[str]]:
    """Ślady kontaktów, na które odpowiadają podane notatki (jedno zapytanie)."""
    ids = {r[1] for r in map(parse_reply_ref, source_refs) if r is not None}
    if not ids:
        return {}
    rows = await db.execute(select(Note.id, Note.source_ref).where(Note.id.in_(ids)))
    return {row[0]: row[1] for row in rows.all()}


def reply_content(outcome: str, channel: str, sent_on: date) -> str:
    """„Odpowiedź na InMail z 21.10.2026: chce rozmawiać” itp."""
    what = f"{CHANNEL_LABELS[channel]} z {sent_on.strftime('%d.%m.%Y')}"
    if outcome == "no_reply":
        return f"Brak odpowiedzi na {what}"
    return f"Odpowiedź na {what}: {_REPLY_TEXT[outcome]}"


# ── Daty w kalendarzu firmy ──────────────────────────────────────────────────


def refund_until(sent_at: datetime) -> date:
    return business_date(sent_at) + timedelta(days=INMAIL_REFUND_DAYS)


def days_ago(at: datetime, today: Optional[date] = None) -> int:
    """Dni kalendarza firmy między dniem kontaktu a dziś (dziś = 0)."""
    return ((today or business_today()) - business_date(at)).days


# ── Kontakty zespołu ─────────────────────────────────────────────────────────


def _not_reply():
    # ``NOT LIKE`` na NULL daje NULL — notatka bez śladu też jest kontaktem.
    return or_(Note.source_ref.is_(None), ~Note.source_ref.like(f"{REPLY_PREFIX}%"))


async def latest_team_contacts(
    db: AsyncSession, user: User, candidate_ids: list[int]
) -> dict[int, TeamContactOut]:
    """Najnowszy kontakt zespołu z każdą osobą — notatki kontaktu i rozmowy,
    jak lista „Kontakty” w panelu, bez zapisanych odpowiedzi. Dwa zapytania
    na całą listę osób (``DISTINCT ON``)."""
    if not candidate_ids:
        return {}
    note_rows = (
        await db.execute(
            select(
                Note.candidate_id,
                Note.created_at,
                Note.author_id,
                User.name,
                Note.note_type,
                Note.source_ref,
            )
            .outerjoin(User, User.id == Note.author_id)
            .where(
                Note.candidate_id.in_(candidate_ids),
                or_(
                    Note.kind == CONTACT_ATTEMPT,
                    Note.note_type.in_(list(_NOTE_TYPE_LABELS)),
                ),
                _not_reply(),
            )
            .distinct(Note.candidate_id)
            .order_by(Note.candidate_id, Note.created_at.desc())
        )
    ).all()
    call_at = func.coalesce(Call.started_at, Call.created_at)
    call_rows = (
        await db.execute(
            select(Call.candidate_id, call_at, Call.user_id, User.name)
            .outerjoin(User, User.id == Call.user_id)
            .where(Call.candidate_id.in_(candidate_ids), call_at.is_not(None))
            .distinct(Call.candidate_id)
            .order_by(Call.candidate_id, call_at.desc())
        )
    ).all()
    today = business_today()
    out: dict[int, TeamContactOut] = {}
    contacts = [
        (cid, at, author_id, name, contact_label(note_type, source_ref))
        for cid, at, author_id, name, note_type, source_ref in note_rows
    ] + [(cid, at, uid, name, "telefon") for cid, at, uid, name in call_rows]
    for cid, at, author_id, name, label in contacts:
        if at is None or (cid in out and out[cid].at >= at):
            continue
        out[cid] = TeamContactOut(
            at=at,
            user_name=name,
            channel_label=label,
            is_me=author_id == user.id,
            days_ago=days_ago(at, today),
        )
    return out


async def ids_with_phone(db: AsyncSession, candidate_ids: list[int]) -> set[int]:
    if not candidate_ids:
        return set()
    rows = await db.execute(
        select(Candidate.id).where(
            Candidate.id.in_(candidate_ids),
            func.length(func.trim(func.coalesce(Candidate.phone, ""))) > 0,
        )
    )
    return set(rows.scalars())


async def _open_inmail(
    db: AsyncSession, user: User, candidate_id: int
) -> Optional[OpenInmailOut]:
    """Mój najnowszy InMail z wtyczki z 90 dni, na który nikt nie zapisał odpowiedzi."""
    since = local_day_start_utc(business_today() - timedelta(days=INMAIL_REFUND_DAYS))
    sent = (
        await db.execute(
            select(Note.id, Note.created_at, Note.job_id)
            .where(
                Note.candidate_id == candidate_id,
                Note.author_id == user.id,
                Note.source_ref == INMAIL_REF,
                Note.created_at >= since,
            )
            .order_by(Note.created_at.desc())
            .limit(20)
        )
    ).all()
    if not sent:
        return None
    refs = [reply_ref(o, row[0]) for row in sent for o in REPLY_OUTCOMES]
    replied = {
        parsed[1]
        for parsed in map(
            parse_reply_ref,
            (await db.execute(select(Note.source_ref).where(Note.source_ref.in_(refs))))
            .scalars()
            .all(),
        )
        if parsed is not None
    }
    open_row = next((row for row in sent if row[0] not in replied), None)
    if open_row is None:
        return None
    note_id, at, job_id = open_row
    job_title = (
        await db.scalar(select(Job.title).where(Job.id == job_id)) if job_id else None
    )
    return OpenInmailOut(
        note_id=note_id, at=at, job_title=job_title, refund_until=refund_until(at)
    )


async def _last_reply(db: AsyncSession, candidate_id: int) -> Optional[LastReplyOut]:
    rows = (
        await db.execute(
            select(Note.created_at, Note.source_ref)
            .where(
                Note.candidate_id == candidate_id,
                Note.source_ref.like(f"{REPLY_PREFIX}%"),
            )
            .order_by(Note.created_at.desc())
            .limit(5)
        )
    ).all()
    for at, source_ref in rows:
        parsed = parse_reply_ref(source_ref)
        if parsed is not None:
            return LastReplyOut(at=at, outcome=parsed[0])
    return None


async def load_outreach(db: AsyncSession, user: User, candidate_id: int) -> OutreachOut:
    """Sekcja ``outreach`` profilu: telefon, świeży kontakt, otwarty InMail, odpowiedź."""
    latest = (await latest_team_contacts(db, user, [candidate_id])).get(candidate_id)
    return OutreachOut(
        has_phone=bool(await ids_with_phone(db, [candidate_id])),
        recent_contact=latest
        if latest is not None and latest.days_ago <= RECENT_CONTACT_DAYS
        else None,
        open_inmail=await _open_inmail(db, user, candidate_id),
        last_reply=await _last_reply(db, candidate_id),
    )


async def enrich_batch(
    db: AsyncSession, user: User, items: list[BatchItem]
) -> list[BatchItem]:
    """Telefon i ostatni kontakt zespołu (bez limitu czasu) dla osób z bazy."""
    ids = sorted({i.candidate_id for i in items if i.candidate_id is not None})
    phones = await ids_with_phone(db, ids)
    contacts = await latest_team_contacts(db, user, ids)
    return [
        item.model_copy(
            update={
                "has_phone": item.candidate_id in phones,
                "last_contact": contacts.get(item.candidate_id),
            }
        )
        if item.candidate_id is not None
        else item
        for item in items
    ]


async def inmail_month(db: AsyncSession, user: User) -> InmailUsageOut:
    """Moje InMaile z wtyczki w bieżącym miesiącu firmy i odpowiedzi na InMaile
    (``interested``/``not_now``) zapisane w tym miesiącu."""
    bounds = local_month_bounds(business_today())
    in_month = (
        Note.author_id == user.id,
        Note.created_at >= bounds.start_utc,
        Note.created_at < bounds.end_utc,
    )
    sent = await db.scalar(
        select(func.count(Note.id)).where(*in_month, Note.source_ref == INMAIL_REF)
    )
    reply_refs = (
        (
            await db.execute(
                select(Note.source_ref).where(
                    *in_month,
                    or_(
                        Note.source_ref.like(f"{REPLY_PREFIX}interested:%"),
                        Note.source_ref.like(f"{REPLY_PREFIX}not_now:%"),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    origin_ids = {p[1] for p in map(parse_reply_ref, reply_refs) if p is not None}
    replied = 0
    if origin_ids:
        replied = await db.scalar(
            select(func.count(Note.id)).where(
                Note.id.in_(origin_ids), Note.source_ref == INMAIL_REF
            )
        )
    return InmailUsageOut(
        sent_month=int(sent or 0),
        replied_month=int(replied or 0),
        credits_month=settings.LINKEDIN_INMAIL_MONTHLY_CREDITS,
    )


# ── Zapis odpowiedzi ─────────────────────────────────────────────────────────


async def close_reminders(db: AsyncSession, user: User, candidate_id: int) -> int:
    """Moje zaplanowane „Odezwij się: … (LinkedIn)” przy tej osobie → wykonane."""
    events = (
        (
            await db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.candidate_id == candidate_id,
                    CalendarEvent.created_by == user.id,
                    CalendarEvent.event_type == EventType.deadline,
                    CalendarEvent.status == EventStatus.scheduled,
                    CalendarEvent.title.like(REMINDER_TITLE_LIKE),
                )
            )
        )
        .scalars()
        .all()
    )
    for event in events:
        event.status = EventStatus.completed
    return len(events)


async def record_reply(
    db: AsyncSession, user: User, candidate_id: int, note_id: int, outcome: str
) -> tuple[int, int, Any]:
    """``(id notatki, zamknięte przypomnienia, wynik apply_note_create | None)``.

    404, gdy ``note_id`` nie jest moim kontaktem z wtyczki (InMail, zaproszenie,
    wiadomość) przy tej osobie. Drugi zapis do tego samego kontaktu oddaje
    istniejącą notatkę. Blokada wiersza kontaktu szereguje równoległe zapisy.
    """
    from app.services.linkedin_extension_writes import add_note

    original = (
        await db.execute(
            select(
                Note.candidate_id,
                Note.author_id,
                Note.source_ref,
                Note.created_at,
                Note.job_id,
            )
            .where(Note.id == note_id)
            .with_for_update()
        )
    ).one_or_none()
    channel = channel_of(original.source_ref) if original is not None else None
    if (
        original is None
        or original.candidate_id != candidate_id
        or original.author_id != user.id
        or channel not in REPLYABLE_CHANNELS
    ):
        raise HTTPException(
            status_code=404, detail="Nie ma takiego kontaktu z wtyczki."
        )
    existing = await db.scalar(
        select(Note.id)
        .where(Note.source_ref.in_([reply_ref(o, note_id) for o in REPLY_OUTCOMES]))
        .order_by(Note.id.asc())
        .limit(1)
    )
    if existing is not None:
        return existing, 0, None
    created = await add_note(
        db,
        user,
        candidate_id,
        reply_content(outcome, channel, business_date(original.created_at)),
        job_id=original.job_id,
        kind=CONTACT_ATTEMPT,
        source_ref=reply_ref(outcome, note_id),
    )
    closed = await close_reminders(db, user, candidate_id)
    await db.flush()
    return created.note.id, closed, created


# ── Zestaw do wyszukiwarki Recruitera ────────────────────────────────────────


def _clean(term: Any) -> str:
    return " ".join(str(term or "").replace('"', " ").split())


def _unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean(value)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def search_term(term: str) -> str:
    """Jedno słowo z liter i cyfr zostaje gołe, reszta w cudzysłowie („C++”, „Spring Boot”)."""
    return term if _PLAIN_TERM_RE.fullmatch(term) else f'"{term}"'


def search_titles(working_title: Optional[str], title: Optional[str]) -> list[str]:
    return _unique([working_title, title])


def search_keywords(titles: list[str], must_skills: list[str]) -> str:
    """``("T1" OR "T2") AND SQL AND "C++"`` — składnia wyszukiwarki Recruitera."""
    parts: list[str] = []
    quoted = [f'"{t}"' for t in titles]
    if len(quoted) == 1:
        parts.append(quoted[0])
    elif quoted:
        parts.append("(" + " OR ".join(quoted) + ")")
    parts.extend(search_term(s) for s in must_skills)
    return " AND ".join(parts)


def split_locations(location: Optional[str]) -> list[str]:
    return _unique(_LOCATION_SPLIT_RE.split(location or ""))


def build_search_kit(job: Any, exclude_companies: Iterable[str]) -> SearchKitResponse:
    """Zestaw do wyszukiwarki z rekrutacji — deterministycznie, bez modelu AI."""
    titles = search_titles(getattr(job, "working_title", None), job.title)
    must = _unique(_skill_names(job.must_skills))
    remote = job.remote_policy
    return SearchKitResponse(
        job_id=job.id,
        title=job.title,
        keywords=search_keywords(titles, must),
        titles=titles,
        skills_must=must,
        skills_nice=_unique(_skill_names(job.nice_skills)),
        locations=split_locations(job.location),
        remote=getattr(remote, "value", remote) if remote else None,
        exclude_companies=sorted(_unique(exclude_companies), key=str.lower),
    )


async def search_kit(db: AsyncSession, job_id: int) -> Optional[SearchKitResponse]:
    """None, gdy rekrutacji nie ma albo jest zamknięta."""
    from app.services.client_off_limits import off_limits_labels

    job = await db.scalar(select(Job).where(Job.id == job_id, Job.is_open.is_(True)))
    if job is None:
        return None
    labels = await off_limits_labels(db)
    return build_search_kit(job, (shown for _label, _cid, shown in labels))
