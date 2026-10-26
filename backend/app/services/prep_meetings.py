"""Prep 1 / Prep 2 z kandydatem przez Teams — zakładanie z NEXUSA (0370).

Przed każdą rozmową u klienta są dwa prepy (decyzja Artura 23.09.2026):
Prep 1 prowadzi Delivery Lead rekrutacji, Prep 2 — rekruter kandydata.
NEXUS podpowiada organizatora; spotkanie powstaje w JEGO kalendarzu przez
aplikację (``teams_prep_graph``), z linkiem Teams, zaproszeniem kandydata,
akapitem o nagrywaniu i — gdy się da — automatyczną transkrypcją.

Porażka kroków PO utworzeniu spotkania (identyfikator spotkania Teams,
włączenie transkrypcji) nie cofa prepu: spotkanie już istnieje w Outlooku
i kandydat dostał zaproszenie. Zostaje ślad ``transcription_setup=failed``
i ostrzeżenie „włącz transkrypcję ręcznie”.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.prep_meeting import PrepMeeting
from app.models.user import User, UserRole
from app.services import interview_slots, prep_invitation, prep_role
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.calendar import (
    M365_SOURCE,
    _build_event_payload,
    _graph_datetime,
    event_transaction_id,
)
from app.services.m365.graph_client import GraphRequestError
from app.services.workforce_availability import operational_owner_ids

logger = logging.getLogger(__name__)


def candidate_name(candidate: Candidate) -> str:
    return " ".join(p for p in (candidate.name, candidate.lastname) if p) or "Kandydat"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def upcoming_interview_start(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[datetime]:
    """Najbliższa zaplanowana rozmowa u klienta pary — runda, do której robi
    się prepy (ta sama, którą wybiera ``debrief_gate.pick_prep_round``)."""
    start = await db.scalar(
        select(func.min(CalendarEvent.start_time)).where(
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status != EventStatus.cancelled,
            CalendarEvent.start_time > datetime.now(timezone.utc),
        )
    )
    return _utc(start) if start is not None else None


async def suggest_organizer_ids(
    db: AsyncSession, jobs: dict[int, Job], pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], tuple[Optional[int], Optional[int]]]:
    """Podpowiedź organizatora (Prep 1, Prep 2) dla wielu par naraz.

    Stała liczba zapytań niezależnie od liczby par (runda 7, R7-V3-2):
    kolejka „Czeka na Ciebie” liczyła podpowiedź osobno dla każdego
    brakującego prepu, a pulpit woła ją u każdego zalogowanego.
    """
    wanted = [pair for pair in dict.fromkeys(pairs) if pair[1] in jobs]
    if not wanted:
        return {}
    recruiters = await interview_slots.default_recruiter_ids(db, wanted)
    # DL przechodzi tę samą bramkę co rekruter (runda 6 audytu): podpowiedź
    # nieaktywnego DL-a kończyła zapis prepu 422 „Organizator jest nieaktywny”,
    # a okno nie podpowiadało wtedy nikogo, choć rekruter był pod ręką.
    leads = {
        (jobs[jid].delivery_lead_id, jid)
        for _cid, jid in wanted
        if jobs[jid].delivery_lead_id
    }
    eligible_leads = await interview_slots.eligible_slot_recruiters(db, leads)
    out: dict[tuple[int, int], tuple[Optional[int], Optional[int]]] = {}
    for cid, jid in wanted:
        lead = jobs[jid].delivery_lead_id
        if lead and (lead, jid) not in eligible_leads:
            lead = None
        recruiter = recruiters.get((cid, jid))
        out[(cid, jid)] = (lead or recruiter, recruiter or lead)
    return out


async def suggest_organizer_id(
    db: AsyncSession, *, job: Job, candidate_id: int, prep_no: int
) -> Optional[int]:
    """Prep 1 → Delivery Lead rekrutacji, Prep 2 → rekruter kandydata.

    Brak DL-a przy Prepie 1 → rekruter (ktoś musi go poprowadzić); rekruter
    kandydata liczy ``interview_slots.default_recruiter_id`` (ta sama reguła
    co przy terminach od klienta).
    """
    prep1, prep2 = (
        await suggest_organizer_ids(db, {job.id: job}, [(candidate_id, job.id)])
    ).get((candidate_id, job.id), (None, None))
    return prep1 if prep_no == 1 else prep2


def scope_refused_detail(organizer: User) -> str:
    """Odmowa Microsoftu przy zakładaniu spotkania — z nazwiskiem prowadzącego.

    22.10.2026 ogólne „ta osoba nie jest w grupie” nie mówiło planującemu ani
    adminowi, KOGO dopisać; prowadzącym bywa DL rekrutacji, nie planujący.
    """
    who = organizer.name or organizer.email or "prowadzącego"
    address = f" ({organizer.email})" if organizer.name and organizer.email else ""
    return (
        f"Microsoft 365 nie pozwolił założyć spotkania w kalendarzu: {who}{address} "
        "— zwykle dlatego, że ta osoba nie jest w grupie NEXUS-Meetings. Wybierz "
        "innego prowadzącego albo poproś administratora o dopisanie tej osoby."
    )


def app_only_ready() -> bool:
    return bool(settings.TEAMS_PREP_APP_ONLY_ENABLED) and (
        teams_prep_auth.credentials_configured()
    )


async def active_prep(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    prep_no: int,
    at: Optional[datetime] = None,
) -> Optional[PrepMeeting]:
    """Prep o tym numerze w BIEŻĄCEJ rundzie rozmów pary.

    Nie liczą się: odwołany, bez nagrania (trzeba go powtórzyć) i prep sprzed
    rozmowy u klienta, która już się odbyła (kolejna runda ma własne prepy).

    Runda 8 (R8-N9-3): prepy robi się do NAJBLIŻSZEJ przyszłej rozmowy, więc
    runda to przedział (ostatnia rozpoczęta rozmowa, najbliższa przyszła] —
    te same granice co runda prepów w ``interview_cycle.load_snapshots``
    (``debrief_gate.pick_prep_round``; niezależnie od zaległego debriefu
    poprzedniej rundy — runda 8, CAL2). Dotąd górnej granicy
    nie było: przy dwóch zaplanowanych rundach Prep 1 do rundy A blokował 409
    założenie Prepu 1 do rundy B, choć ekran już go żądał.

    Górna granica obowiązuje tylko wtedy, gdy ZA najbliższą rozmową jest
    kolejna. Prep po ostatniej zaplanowanej rozmowie nie ma innej rundy, do
    której mógłby należeć — to spóźniony prep tej samej (zgłoszenie
    02.10.2026: Prep 1 zaplanowano, zanim DL potwierdził termin rozmowy na
    dwa dni wcześniej; ekran poprosił o Prep 1 jeszcze raz, serwer go założył
    i kandydat miał dwa zaproszenia). Lustro ``late_preps`` w
    ``interview_cycle.load_snapshots``.

    ``at`` = chwila, względem której liczy się runda (domyślnie teraz);
    ocena Prepu 2 podaje start tego prepu (audyt 22.10.2026, F42).
    """
    now = _utc(at) if at is not None else datetime.now(timezone.utc)
    starts = [
        _utc(s)
        for s in (
            await db.scalars(
                select(CalendarEvent.start_time).where(
                    CalendarEvent.candidate_id == candidate_id,
                    CalendarEvent.job_id == job_id,
                    CalendarEvent.event_type == EventType.client_interview,
                    CalendarEvent.status != EventStatus.cancelled,
                )
            )
        ).all()
        if s is not None
    ]
    round_start = max((s for s in starts if s <= now), default=None)
    upcoming = sorted(s for s in starts if s > now)
    round_end = upcoming[0] if len(upcoming) > 1 else None
    q = (
        select(PrepMeeting)
        .join(CalendarEvent, CalendarEvent.id == PrepMeeting.calendar_event_id)
        .where(
            PrepMeeting.candidate_id == candidate_id,
            PrepMeeting.job_id == job_id,
            PrepMeeting.prep_no == prep_no,
            PrepMeeting.transcript_status != "missing",
            CalendarEvent.status != EventStatus.cancelled,
        )
    )
    if round_start is not None:
        q = q.where(CalendarEvent.start_time > round_start)
    if round_end is not None:
        q = q.where(CalendarEvent.start_time <= round_end)
    return await db.scalar(q.order_by(PrepMeeting.id.desc()).limit(1))


async def organizer_prep_spans(
    db: AsyncSession, *, organizer_id: int, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Nieodwołane prepy prowadzącego w NEXUSIE, które nachodzą na [start, end).

    Kontrola zajętości przy zapisie prepu pomija blok z Outlooka o tym samym
    przedziale (sierota z poprzedniej próby), więc prep innego kandydata
    w tej samej godzinie trzeba znać z bazy (audyt 22.10, F32).
    """
    rows = (
        await db.execute(
            select(CalendarEvent.start_time, CalendarEvent.end_time)
            .join(PrepMeeting, PrepMeeting.calendar_event_id == CalendarEvent.id)
            .where(
                PrepMeeting.organizer_user_id == organizer_id,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time < end,
                CalendarEvent.end_time > start,
            )
        )
    ).all()
    return [(_utc(s), _utc(e)) for s, e in rows if s is not None and e is not None]


async def already_scheduled_message(db: AsyncSession, prep: PrepMeeting) -> str:
    """Zdanie dla 409: kiedy jest istniejący prep i czy wypada po rozmowie."""
    start = await db.scalar(
        select(CalendarEvent.start_time).where(
            CalendarEvent.id == prep.calendar_event_id
        )
    )
    if start is None:
        return (
            f"Prep {prep.prep_no} jest już zaplanowany. Zmień jego termin "
            "albo go odwołaj."
        )
    when = prep_invitation.when_label(start)
    interview = await upcoming_interview_start(
        db, candidate_id=prep.candidate_id, job_id=prep.job_id
    )
    if interview is not None and _utc(start) > interview:
        return (
            f"Prep {prep.prep_no} jest już zaplanowany na {when}, czyli po "
            "rozmowie u klienta. Przełóż go przed rozmowę albo odwołaj, zamiast "
            "zakładać drugi."
        )
    return (
        f"Prep {prep.prep_no} jest już zaplanowany na {when}. Zmień jego termin "
        "albo go odwołaj."
    )


async def prep_for_event(db: AsyncSession, event_id: int) -> Optional[PrepMeeting]:
    return await db.scalar(
        select(PrepMeeting).where(PrepMeeting.calendar_event_id == event_id)
    )


@dataclass(frozen=True)
class CreatedPrep:
    event: CalendarEvent
    prep: PrepMeeting


def _fetch_after(end: datetime) -> datetime:
    aware = end if end.tzinfo is not None else end.replace(tzinfo=timezone.utc)
    return aware + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)


def role_description_for_invitation(job: Job, edited: Optional[str]) -> str:
    """Opis roli do zaproszenia: z okna (sprawdzony) albo z Championa."""
    if edited is not None:
        text = edited.replace("\r\n", "\n").strip()[: prep_role.DESCRIPTION_MAX]
        found = prep_role.findings(text)
        if found:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "PREP_ROLE_DESCRIPTION_FINDINGS",
                    "message": (
                        "Opis roli zawiera treści, których nie wysyłamy "
                        "kandydatowi — popraw je albo wyłącz opis."
                    ),
                    "findings": [f.as_dict() for f in found],
                },
            )
        return text
    text = prep_role.description(job)
    if text and prep_role.findings(text):
        logger.info("prep invitation: default role description dropped (lint)")
        return ""
    return text


async def create_prep(
    db: AsyncSession,
    *,
    actor: User,
    candidate: Candidate,
    job: Job,
    prep_no: int,
    organizer: User,
    start: datetime,
    end: datetime,
    extra_attendees: list[User],
    note: Optional[str],
    client_request_id: Optional[str],
    client_name: Optional[str] = None,
    extra_emails: Sequence[str] = (),
    interview_start: Optional[datetime] = None,
    role_title: Optional[str] = None,
    role_description: Optional[str] = None,
) -> CreatedPrep:
    """Spotkanie w kalendarzu organizatora + wiersze NEXUSA. Flush, bez commitu.

    ``extra_emails`` — zaproszeni spoza NEXUSA (decyzja D1, 17.10.2026: Delivery
    Lead chciał dopisać kogoś spoza zespołu rekrutacji, a lista pozwalała tylko
    na zespół).

    ``interview_start`` — termin rozmowy wybrany w oknie, który czeka jeszcze
    na DL-a (przełożenie). Wygrywa z najbliższą rozmową z kalendarza, bo ta
    jest wtedy STARĄ rozmową (decyzja Artura 22.10.2026, audyt F37).

    ``role_title`` / ``role_description`` — stanowisko i opis roli poprawione
    w oknie (26.10.2026); ``None`` = z Championa (``prep_role``), pusty opis =
    zaproszenie bez opisu. Opis z okna ze znaleziskiem kontroli = 422, opis
    domyślny ze znaleziskiem po cichu wypada — okno „Umów rozmowę i prepy” nie
    ma go jak poprawić, a prep nie może przez to przepaść.
    """
    if not organizer.email:
        raise HTTPException(
            status_code=422,
            detail="Organizator nie ma adresu e-mail w NEXUSIE — nie da się "
            "założyć spotkania w jego kalendarzu.",
        )
    if not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="Kandydat nie ma adresu e-mail — nie da się wysłać zaproszenia.",
        )

    title = prep_invitation.title(prep_no, candidate_name(candidate), client_name)
    # Termin rozmowy trafia do treści tylko wtedy, gdy prep jest PRZED nią —
    # zaproszenie na prep po rozmowie nie może jej zapowiadać.
    if interview_start is not None:
        interview_start = _utc(interview_start)
    else:
        interview_start = await upcoming_interview_start(
            db, candidate_id=candidate.id, job_id=job.id
        )
    if interview_start is not None and _utc(start) >= interview_start:
        interview_start = None
    # Kandydat dostaje nazwę roli z Championa albo oczyszczoną nazwę od
    # klienta — bez numeru zapytania („… Prioritization (42874)”, 22.10.2026;
    # „PL_IT_Developer_expert_TP#40379”, 26.10.2026).
    role = " ".join((role_title or "").split())[: prep_role.TITLE_MAX]
    if not role:
        role, _ = await prep_role.title(db, job)
    role_text = role_description_for_invitation(job, role_description)
    role_block = prep_invitation.role_section(role, role_text)
    invitation = prep_invitation.text(
        prep_no=prep_no,
        client_name=client_name,
        job_title=role,
        interview_start=interview_start,
        note=note,
        organizer_name=organizer.name or "",
        role_hint=prep_invitation.ROLE_HINT if role_block else None,
    )
    description = prep_invitation.as_plain(invitation, role_block)
    attendees = attendee_emails(
        candidate_email=candidate.email,
        organizer_email=organizer.email,
        users=extra_attendees,
        emails=extra_emails,
    )
    payload = _build_event_payload(
        title=title,
        description=prep_invitation.as_html(invitation, role_block),
        start=start,
        end=end,
        attendee_emails=attendees,
        want_teams=True,
        transaction_id=event_transaction_id(
            owner_user_id=organizer.id,
            title=title,
            start=start,
            end=end,
            attendee_emails=attendees,
            # Odcisk organizatora i terminu w intencji (runda 6 audytu): okno
            # trzyma ten sam `client_request_id`, gdy ktoś po błędzie zmieni
            # termin albo osobę — Graph oddawał wtedy STARE spotkanie, a NEXUS
            # zapisywał nowy termin, którego w Outlooku nie było.
            intent_id=(
                f"prep|{candidate.id}|{job.id}|{prep_no}|{client_request_id}"
                f"|{organizer.id}|{start.isoformat()}|{end.isoformat()}"
                if client_request_id
                else None
            ),
        ),
    )

    try:
        created = await teams_prep_graph.create_event(organizer.email, payload)
    except AppOnlyTokenUnavailable as exc:
        logger.warning("teams prep: no app-only token (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Integracja z Teams nie jest skonfigurowana. W NEXUSIE nic "
            "nie zostało zapisane.",
        ) from exc
    except GraphRequestError as exc:
        logger.warning("teams prep: create event Graph %s", exc.status)
        if exc.status in (403, 404):
            raise HTTPException(
                status_code=409,
                detail=scope_refused_detail(organizer),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Outlook nie przyjął spotkania — spróbuj ponownie za chwilę. "
            "W NEXUSIE nic nie zostało zapisane.",
        ) from exc

    # Termin z odpowiedzi Outlooka, nie z żądania — to on dostał zaproszenie.
    start = created.start or start
    end = created.end or end
    event = CalendarEvent(
        title=title,
        description=description,
        event_type=EventType.prep_call,
        start_time=start,
        end_time=end,
        all_day=False,
        attendees=[{"address": a} for a in attendees],
        candidate_id=candidate.id,
        job_id=job.id,
        status=EventStatus.scheduled,
        external_source=M365_SOURCE,
        external_id=created.graph_event_id,
        created_by=organizer.id,
        operational_owner_id=organizer.id,
        m365_change_key=created.change_key,
        online_meeting_url=created.join_url,
        reminder_minutes=15,
    )
    db.add(event)
    await db.flush()

    prep = PrepMeeting(
        calendar_event_id=event.id,
        candidate_id=candidate.id,
        job_id=job.id,
        prep_no=prep_no,
        organizer_user_id=organizer.id,
        organizer_upn=organizer.email,
        scheduled_by_user_id=actor.id,
        transcription_setup="pending",
        transcript_status="waiting",
        next_fetch_at=_fetch_after(end),
        # Kandydat jeszcze nie odpowiedział (0453) — pierwsze „przyjął” dzwoni.
        candidate_response="none",
    )
    db.add(prep)
    await db.flush()
    await setup_transcription(prep, join_url=created.join_url)
    await db.flush()
    return CreatedPrep(event=event, prep=prep)


async def setup_transcription(prep: PrepMeeting, *, join_url: Optional[str]) -> None:
    """Identyfikatory spotkania Teams i automatyczna transkrypcja. Nigdy nie rzuca."""
    try:
        if not prep.organizer_aad_id:
            prep.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                prep.organizer_upn
            )
        if prep.organizer_aad_id and join_url and not prep.online_meeting_id:
            prep.online_meeting_id = await teams_prep_graph.find_online_meeting(
                prep.organizer_aad_id, join_url
            )
        if not settings.TEAMS_PREP_AUTO_TRANSCRIBE:
            prep.transcription_setup = "disabled"
            return
        if not (prep.organizer_aad_id and prep.online_meeting_id):
            prep.transcription_setup = "failed"
            prep.last_error = "meeting_not_found"
            return
        await teams_prep_graph.enable_auto_transcription(
            prep.organizer_aad_id, prep.online_meeting_id
        )
        prep.transcription_setup = "enabled"
    except GraphRequestError as exc:
        prep.transcription_setup = "failed"
        prep.last_error = f"setup_http_{exc.status}"
        logger.warning(
            "teams prep %s: transcription setup Graph %s", prep.id, exc.status
        )
    except Exception as exc:  # noqa: BLE001 — sieć, token
        prep.transcription_setup = "failed"
        prep.last_error = f"setup_{type(exc).__name__}"[:120]
        logger.warning("teams prep %s: transcription setup failed", prep.id)


def reschedule_fetch(prep: PrepMeeting, end: datetime) -> None:
    """Nowy termin spotkania = nowy moment pytania o transkrypt.

    Prep „bez nagrania” (albo z błędem) przełożony na nowy termin znów czeka
    na transkrypt — spotkanie jeszcze się nie odbyło.
    """
    if prep.transcript_status in ("waiting", "missing", "error", "forbidden"):
        prep.transcript_status = "waiting"
        prep.fetch_attempts = 0
        prep.next_fetch_at = _fetch_after(end)


async def suggestion_summary(
    db: AsyncSession, *, job: Job, candidate_id: int
) -> dict[int, Optional[int]]:
    """Podpowiedzi organizatora dla obu prepów (okno „Zaplanuj prep”)."""
    prep1, prep2 = (
        await suggest_organizer_ids(db, {job.id: job}, [(candidate_id, job.id)])
    ).get((candidate_id, job.id), (None, None))
    return {1: prep1, 2: prep2}


# ── Zmiana i odwołanie prepu przez ludzi pary (decyzje D1–D4, 17.10.2026) ────

_PREP_OVERSIGHT = (UserRole.admin, UserRole.head_of_recruitment)
DEFAULT_CANCEL_COMMENT = "Spotkanie zostało odwołane."


def attendee_emails(
    *,
    candidate_email: str,
    organizer_email: Optional[str],
    users: Sequence[User],
    emails: Sequence[str],
) -> list[str]:
    """Adresy zaproszonych: kandydat pierwszy, bez organizatora i bez powtórzeń."""
    out = [candidate_email]
    seen = {candidate_email.lower(), (organizer_email or "").lower()}
    for raw in [*(u.email for u in users), *emails]:
        address = (raw or "").strip()
        if address and address.lower() not in seen:
            seen.add(address.lower())
            out.append(address)
    return out


async def prep_editor_ids(
    db: AsyncSession, prep: PrepMeeting, job: Optional[Job]
) -> set[int]:
    """Ludzie pary, którzy mogą zmienić i odwołać prep (decyzja D2).

    Prowadzący, osoba, która prep zaplanowała, Delivery Lead rekrutacji
    i rekruter kandydata (``default_recruiter_ids`` — ta sama reguła co
    podpowiedź Prepu 2). Do 17.10.2026 prep zmieniał tylko właściciel
    wydarzenia, czyli prowadzący: rekruter, który założył Prep 1 w kalendarzu
    DL-a, dostawał 404 na „Szczegóły” i 403 na zmianę terminu, choć to on
    ustala termin z kandydatem.
    """
    ids = {prep.organizer_user_id, prep.scheduled_by_user_id}
    if job is not None:
        ids.add(job.delivery_lead_id)
    pair = (prep.candidate_id, prep.job_id)
    ids.add((await interview_slots.default_recruiter_ids(db, [pair])).get(pair))
    return {i for i in ids if i}


def user_can_edit_prep(user: User, editor_ids: set[int]) -> bool:
    """Admin i Head of Recruitment zawsze; reszta, gdy jest kimś z pary
    (albo go zastępuje — ``operational_owner_ids``).

    Odwołanie cudzego wydarzenia zostaje zastrzeżone dla właściciela
    (``calendar_access.user_can_remove_event``, decyzja z 17.09.2026), bo idzie
    połączonym kontem M365 twórcy. Prep zmienia aplikacja w kalendarzu
    prowadzącego niezależnie od tego, kto klika, więc tamten powód tu nie
    występuje.
    """
    if user.has_any_role(*_PREP_OVERSIGHT):
        return True
    return bool(operational_owner_ids(user) & editor_ids)


def ensure_prep_open(event: CalendarEvent, now: Optional[datetime] = None) -> None:
    """Zmienić i odwołać da się tylko prep, który jest przed nami."""
    now = now or datetime.now(timezone.utc)
    if event.status == EventStatus.cancelled:
        raise HTTPException(
            status_code=409, detail="Ten prep jest odwołany. Zaplanuj nowy."
        )
    end = event.end_time or event.start_time
    if end is not None and _utc(end) <= now:
        raise HTTPException(
            status_code=409,
            detail="Ten prep już się odbył — zmienić można tylko prep, który jest "
            "przed nami.",
        )


def _graph_failure(exc: Exception, event_id: int, what: str) -> HTTPException:
    if isinstance(exc, GraphRequestError):
        logger.warning("prep %s: Graph %s for event %s", what, exc.status, event_id)
        return HTTPException(
            status_code=502 if exc.status >= 500 else 409,
            detail="Outlook nie przyjął zmiany prepu. W NEXUSIE nic nie zostało "
            "zmienione.",
        )
    logger.warning("prep %s: %s for event %s", what, type(exc).__name__, event_id)
    return HTTPException(
        status_code=502,
        detail="Nie udało się połączyć z Outlookiem. W NEXUSIE nic nie zostało "
        "zmienione.",
    )


async def push_prep_update(
    prep: PrepMeeting,
    event: CalendarEvent,
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    attendees: Optional[list[str]],
) -> None:
    """Nowy termin albo nowa lista zaproszonych w kalendarzu prowadzącego.

    Najpierw Outlook, potem baza (jak ``_push_prep_changes``): zapis tylko
    w NEXUSIE cofnęłoby odświeżenie terminu z Outlooka, a kandydat zostałby
    przy starym. Graph wysyła aktualizację tego samego zaproszenia, nowym
    osobom zaproszenie, a usuniętym odwołanie.
    """
    payload: dict = {}
    if start is not None and end is not None:
        payload["start"] = _graph_datetime(start)
        payload["end"] = _graph_datetime(end)
    if attendees is not None:
        payload["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees
        ]
    if not payload:
        return
    try:
        change_key = await teams_prep_graph.update_event(
            prep.organizer_upn, event.external_id, payload
        )
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        raise _graph_failure(exc, event.id, "update") from exc
    if change_key:
        event.m365_change_key = change_key
    if start is not None and end is not None:
        event.start_time, event.end_time = start, end
        reschedule_fetch(prep, end)
        # Outlook zeruje odpowiedzi zaproszonych przy nowym terminie (0453).
        prep.candidate_response = "none"
        prep.candidate_response_at = None
        prep.proposed_start = None
        prep.proposed_end = None
    if attendees is not None:
        event.attendees = [{"address": a} for a in attendees]


async def cancel_prep(
    prep: PrepMeeting, event: CalendarEvent, comment: Optional[str]
) -> str:
    """Odwołanie w kalendarzu prowadzącego; kandydat i zaproszeni dostają odwołanie."""
    try:
        outlook = await teams_prep_graph.cancel_event(
            prep.organizer_upn,
            event.external_id,
            (comment or "").strip() or DEFAULT_CANCEL_COMMENT,
        )
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        raise _graph_failure(exc, event.id, "cancel") from exc
    event.status = EventStatus.cancelled
    if prep.transcript_status == "waiting":
        prep.transcript_status = "cancelled"
    return outlook


async def replace_organizer(
    db: AsyncSession,
    *,
    actor: User,
    prep: PrepMeeting,
    event: CalendarEvent,
    candidate: Candidate,
    job: Job,
    organizer: User,
    start: datetime,
    end: datetime,
    users: list[User],
    emails: Sequence[str],
    client_request_id: Optional[str],
    client_name: Optional[str],
) -> CreatedPrep:
    """Inny prowadzący = nowe zaproszenie i odwołanie starego (decyzja D4).

    Microsoft nie przenosi spotkania między kalendarzami. Najpierw powstaje
    nowe spotkanie, potem znika stare — kandydat przez chwilę ma dwa
    zaproszenia, ale nigdy żadnego. Gdy odwołanie starego się nie uda, nowe
    jest odwoływane, a wiersze NEXUSA cofa rollback żądania.
    """
    created = await create_prep(
        db,
        actor=actor,
        candidate=candidate,
        job=job,
        prep_no=prep.prep_no,
        organizer=organizer,
        start=start,
        end=end,
        extra_attendees=users,
        note=None,
        client_request_id=client_request_id,
        client_name=client_name,
        extra_emails=emails,
    )
    who = organizer.name or "inna osoba"
    try:
        await teams_prep_graph.cancel_event(
            prep.organizer_upn,
            event.external_id,
            f"Prep poprowadzi {who}. Nowe zaproszenie przyszło w osobnej wiadomości.",
        )
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        logger.warning(
            "prep replace: old cancel %s for event %s", type(exc).__name__, event.id
        )
        try:
            await teams_prep_graph.cancel_event(
                created.prep.organizer_upn,
                created.event.external_id,
                DEFAULT_CANCEL_COMMENT,
            )
        except Exception as undo:  # noqa: BLE001
            logger.warning(
                "prep replace: undo %s for new event of %s",
                type(undo).__name__,
                event.id,
            )
        raise HTTPException(
            status_code=502,
            detail="Nie udało się zmienić prowadzącego — Outlook nie przyjął "
            "odwołania starego spotkania. Nic się nie zmieniło.",
        ) from exc
    event.status = EventStatus.cancelled
    if prep.transcript_status == "waiting":
        prep.transcript_status = "cancelled"
    return created
