"""
Calendar API
Manages recruitment calendar events — interviews, screenings, prep calls, meetings, deadlines.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db, AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventType, EventStatus
from app.models.candidate import Candidate
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactOpportunity,
)
from app.models.job import Job
from app.models.client import Client
from app.models.interview_feedback import InterviewFeedback
from app.models.notification import Notification, NotificationType
from app.services.notification_access import notification_recipient_has_access
from app.services.operational_tasks import nominal_task_owner, ownership_payload
from app.services.workforce_availability import effective_owner_ids, effective_owner_id
from app.models.user import User, UserRole
from app.api.recruitment_access import (
    CalendarWriteAccess,
    RecruitmentReadAccess,
    ensure_optional_job_membership,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.api.calendar_access import (
    CALENDAR_EVENT_CANCELLED,
    CALENDAR_EVENT_DELETED,
    CALENDAR_EVENT_UPDATED,
    event_visibility_filter,
    personal_event_visibility_filter,
    project_event_fields,
    record_calendar_audit,
    user_can_mutate_event,
    user_can_remove_event,
    user_can_view_event,
    user_is_override,
)
from app.services.candidate_contact_hooks import (
    maybe_remove_calendar_handoff,
    maybe_sync_calendar_handoff,
)
from app.services import loop_heartbeat
from app.services.calendar_all_day import normalize_all_day

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def _is_contact_handoff_event(event: CalendarEvent) -> bool:
    return bool(
        event.candidate_id
        and event.job_id
        and event.event_type in (EventType.screening, EventType.interview)
        and event.status in (EventStatus.scheduled, EventStatus.completed)
    )


async def _owns_open_contact_opportunity(
    db: AsyncSession,
    user_id: int,
    candidate_id: Optional[int],
    job_id: Optional[int],
) -> bool:
    """Czy wołający prowadzi otwartą sprawę kontaktu obejmującą tę parę.

    Kolejka kontaktu jest KANDYDATO-globalna, a członkostwo w ofercie — nie.
    Właścicielem sprawy zostaje się przez przynależność do JEDNEJ z otwartych
    ofert kandydata (``_eligible_users`` bierze sumę zespołów wszystkich
    otwartych szans), ale domknięcie wymaga spotkania na KAŻDEJ z nich —
    a jedyną ścieżką ustawienia ``meeting_event_id`` są trasy kalendarza.
    Sama bramka członkostwa blokowała więc przekazanie, które koordynator już
    zaprojektował: właściciel dostawał sprawę nie do domknięcia i musiał ją
    eskalować.

    To NIE jest poszerzenie ``ensure_job_membership`` — zakres jest wąski i
    pochodny: dokładnie te oferty, które kolejka wręczyła TEMU właścicielowi,
    tylko dopóki szansa jest otwarta, i tylko przy włączonym module (domyślnie
    wyłączony, więc na produkcji zero zmiany zachowania).
    """
    if not settings.CANDIDATE_CONTACT_ENABLED or candidate_id is None or job_id is None:
        return False
    match = await db.scalar(
        select(CandidateContactOpportunity.id)
        .join(
            CandidateContactCase,
            CandidateContactCase.id == CandidateContactOpportunity.case_id,
        )
        .where(
            CandidateContactOpportunity.candidate_id == candidate_id,
            CandidateContactOpportunity.job_id == job_id,
            CandidateContactOpportunity.closed_at.is_(None),
            CandidateContactCase.owner_user_id.in_(
                await effective_owner_ids(db, user_id)
            ),
        )
        .limit(1)
    )
    return match is not None


async def _ensure_calendar_job_scope(
    db: AsyncSession,
    user: User,
    *,
    candidate_id: Optional[int],
    job_id: Optional[int],
) -> None:
    """Zakres oferty dla zapisu kalendarza: członkostwo LUB własna sprawa kontaktu.

    Jedno miejsce decyzji dla wszystkich tras zapisu, żeby drugie źródło zakresu
    nie rozjechało się między tworzeniem a edycją.
    """
    if await _owns_open_contact_opportunity(db, user.id, candidate_id, job_id):
        return
    await ensure_optional_job_membership(db, user, job_id)


# ── Schemas ────────────────────────────────────────────────────────────────────


# Przypomnienie najwyżej dobę przed startem. Pętla przypomnień i tak nie
# patrzy dalej niż 1440 min w przód, więc większa wartość zapisałaby obietnicę,
# której nikt nie spełni. 0 = bez przypomnienia (nie ma tej opcji w UI, ale
# API ją przyjmuje dla integracji).
REMINDER_MAX_MINUTES = 1440
_END_BEFORE_START = "Koniec wydarzenia musi być późniejszy niż jego początek."
_REMINDER_RANGE = (
    f"Przypomnienie musi mieścić się w zakresie 0–{REMINDER_MAX_MINUTES} minut."
)


def _check_reminder(value: Optional[int]) -> Optional[int]:
    if value is not None and not 0 <= value <= REMINDER_MAX_MINUTES:
        raise ValueError(_REMINDER_RANGE)
    return value


class CalendarEventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    event_type: EventType = EventType.meeting
    start_time: datetime
    end_time: Optional[datetime] = None
    all_day: bool = False
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    attendees: Optional[list] = None
    location: Optional[str] = None
    teams_link: Optional[str] = None
    reminder_minutes: int = 15

    @field_validator("reminder_minutes")
    @classmethod
    def _reminder_range(cls, value: Optional[int]) -> Optional[int]:
        return _check_reminder(value)

    @model_validator(mode="after")
    def _end_after_start(self) -> "CalendarEventCreate":
        # Wpis całodniowy dostaje koniec z `normalize_all_day` — tam „ten sam
        # dzień" jest poprawnym wejściem, nie błędem.
        if (
            not self.all_day
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValueError(_END_BEFORE_START)
        return self


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[EventType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_day: Optional[bool] = None
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    attendees: Optional[list] = None
    location: Optional[str] = None
    teams_link: Optional[str] = None
    reminder_minutes: Optional[int] = None
    status: Optional[EventStatus] = None

    @field_validator("reminder_minutes")
    @classmethod
    def _reminder_range(cls, value: Optional[int]) -> Optional[int]:
        return _check_reminder(value)


class CalendarEventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    event_type: str
    start_time: datetime
    end_time: Optional[datetime]
    all_day: bool
    candidate_id: Optional[int]
    candidate_name: Optional[str]
    job_id: Optional[int]
    job_title: Optional[str]
    client_id: Optional[int]
    client_name: Optional[str]
    attendees: Optional[list]
    location: Optional[str]
    teams_link: Optional[str]
    # Phase 7.1 — Graph-generated Teams join URL + Stream recording URL.
    online_meeting_url: Optional[str] = None
    recording_url: Optional[str] = None
    created_by: Optional[int]
    owner_user_id: Optional[int] = None
    effective_user_id: Optional[int] = None
    substitution: Optional[dict] = None
    reminder_minutes: int
    status: str
    created_at: Optional[datetime]
    # Pola, które kolumny niosły od dawna, a odpowiedź nie — więc eskalacja
    # T+2h i potwierdzenie kandydata były zapisywane i nigdzie niewidoczne.
    needs_attention: bool = False
    candidate_confirmed_at: Optional[datetime] = None
    candidate_confirmation_source: Optional[str] = None
    # `microsoft365` / `ical` / `manual` — front decyduje, czy wydarzenie
    # się „odwołuje" (Outlook), czy „usuwa" (wpis tylko w NEXUSIE).
    external_source: Optional[str] = None
    # Strony feedbacku zapisane pod tym wydarzeniem (`candidate_side`,
    # `client_side`) — okno wydarzenia pokazuje „Uzupełnij/Edytuj" bez
    # osobnego zapytania na każde wydarzenie w tygodniu.
    feedback_sources: list[str] = []
    # Czy wołający może odwołać / usunąć wydarzenie (`user_can_remove_event`).
    can_remove: bool = False

    class Config:
        from_attributes = True


def _event_extras(ev: CalendarEvent, current_user: User) -> dict:
    """Pola odpowiedzi wspólne dla WSZYSTKICH konstruktorów odpowiedzi.

    Pięć tras buduje `CalendarEventResponse` ręcznie; nowe pole dopisane do
    jednej z nich i pominięte w pozostałych dawało okno, które po edycji
    „gubiło" odznakę albo link. Jedno miejsce = jeden kontrakt.
    """
    return {
        "needs_attention": bool(ev.needs_attention),
        "candidate_confirmed_at": ev.candidate_confirmed_at,
        "candidate_confirmation_source": ev.candidate_confirmation_source,
        "external_source": ev.external_source,
        # Front pokazuje „Odwołaj"/„Usuń" tylko temu, kogo serwer wpuści
        # (właściciel albo admin — HoR poprawia cudze, ale ich nie odwołuje).
        "can_remove": user_can_remove_event(ev, current_user),
    }


async def _feedback_sources_by_event(
    db: AsyncSession, event_ids: list[int]
) -> dict[int, list[str]]:
    """Strony feedbacku per wydarzenie — jednym zapytaniem na całą stronę."""
    if not event_ids:
        return {}
    rows = await db.execute(
        select(InterviewFeedback.calendar_event_id, InterviewFeedback.feedback_source)
        .where(InterviewFeedback.calendar_event_id.in_(event_ids))
        .order_by(InterviewFeedback.feedback_source)
    )
    out: dict[int, list[str]] = {}
    for event_id, source in rows.all():
        out.setdefault(event_id, []).append(source.value)
    return out


# ── Routes ─────────────────────────────────────────────────────────────────────


# Sufit odpowiedzi dla `GET /calendar/events`. Ta trasa nie ma paginacji i
# nie miała ŻADNEGO limitu: dla admina i head_of_recruitment
# `event_visibility_filter` zwraca `true()`, a `from_date`/`to_date` są
# opcjonalne — więc pojedyncze wywołanie bez parametrów materializowało całą
# tabelę wydarzeń. 500 to sufit, nie rozmiar strony; wołający, któremu on nie
# wystarcza, ma zawęzić okno dat, a nie prosić o więcej.
_EVENTS_MAX = 500


@router.get("/calendar/events", response_model=List[CalendarEventResponse])
async def list_events(
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    event_type: Optional[EventType] = Query(None),
    status: Optional[EventStatus] = Query(None),
    upcoming: bool = Query(False),
    start_from: Optional[datetime] = Query(None),
    limit: int = Query(_EVENTS_MAX, ge=1, le=_EVENTS_MAX),
    mine_only: bool = Query(False),
):
    """List calendar events the caller may see (owner / attendee / admin-HoR).

    Resource scoping (P1-CALENDAR-01): the SQL query is filtered to events the
    caller owns or attends before any row is read; admin/head_of_recruitment
    see all. A non-owner participant receives a redacted projection.

    Powód zmiany to LIMIT i N+1: trasa jest publiczna, nie miała żadnego
    sufitu, a dla konta widzącego wszystko robiła trzy zapytania na każde
    wydarzenie w bazie.

    ``upcoming``/``start_from`` to ŚWIADOME rozszerzenie kontraktu przy okazji:
    FastAPI odrzuca nieznane parametry zapytania w MILCZENIU, więc wołający
    proszący o „5 najbliższych" dostawał 5 NAJSTARSZYCH wydarzeń, bez śladu
    błędu. Dziś nie boli to nikogo — jedyny nadawca tych parametrów
    (`DashboardV2.tsx`) siedzi w komponencie, którego nikt nie importuje —
    ale cicho ignorowany parametr jest pułapką zastawioną na następnego
    wołającego, a nie brakiem funkcji. Domyślne wartości nie zmieniają
    odpowiedzi dla wołających, którzy ich nie podają
    (`app/calendar/page.tsx` filtruje tydzień przez `from_date`/`to_date`).
    """
    visibility = (
        personal_event_visibility_filter(current_user)
        if mine_only
        else event_visibility_filter(current_user)
    )
    query = select(CalendarEvent).where(visibility)
    conditions = []
    if from_date:
        conditions.append(CalendarEvent.start_time >= from_date)
    if to_date:
        conditions.append(CalendarEvent.start_time <= to_date)
    if event_type:
        conditions.append(CalendarEvent.event_type == event_type)
    if status:
        conditions.append(CalendarEvent.status == status)
    if start_from:
        conditions.append(CalendarEvent.start_time >= start_from)
    elif upcoming:
        # `upcoming` bez jawnego progu znaczy „od teraz" — bo inaczej nie
        # znaczy nic i wołający dostaje początek historii pod nagłówkiem
        # obiecującym przyszłość.
        conditions.append(CalendarEvent.start_time >= datetime.now(timezone.utc))
    if conditions:
        query = query.where(and_(*conditions))
    # Rosnąco po `start_time` + limit: przy sortowaniu rosnącym ucięcie
    # zabiera KONIEC okna, więc sufit musi być na tyle wysoki, żeby realne
    # okno (tydzień w kalendarzu) się w nim mieściło.
    query = query.order_by(CalendarEvent.start_time).limit(limit)
    # Nazwy kandydata/rekrutacji/klienta jednym `IN`-em na całą stronę.
    # Wcześniej leciały trzy SELECT-y na KAŻDE wydarzenie, a że limitu nie
    # było, przy koncie widzącym wszystko to były tysiące round-tripów.
    query = query.options(
        selectinload(CalendarEvent.candidate),
        selectinload(CalendarEvent.job),
        selectinload(CalendarEvent.client),
    )

    result = await db.execute(query)
    events = result.scalars().all()
    feedback_sources = await _feedback_sources_by_event(db, [ev.id for ev in events])

    # Enrich with names
    output = []
    for ev in events:
        cand = ev.candidate
        candidate_name = f"{cand.name} {cand.lastname}" if cand else None
        job_title = ev.job.title if ev.job else None
        client_name = ev.client.name if ev.client else None

        projected = project_event_fields(ev, current_user)
        output.append(
            CalendarEventResponse(
                id=ev.id,
                title=ev.title,
                description=projected["description"],
                event_type=ev.event_type.value,
                start_time=ev.start_time,
                end_time=ev.end_time,
                all_day=ev.all_day,
                candidate_id=ev.candidate_id,
                candidate_name=candidate_name,
                job_id=ev.job_id,
                job_title=job_title,
                client_id=ev.client_id,
                client_name=client_name,
                attendees=projected["attendees"],
                location=ev.location,
                teams_link=ev.teams_link,
                online_meeting_url=ev.online_meeting_url,
                recording_url=ev.recording_url,
                created_by=ev.created_by,
                reminder_minutes=ev.reminder_minutes,
                status=ev.status.value,
                created_at=ev.created_at,
                **_event_extras(ev, current_user),
                feedback_sources=feedback_sources.get(ev.id, []),
            )
        )

    return output


@router.post("/calendar/events", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    body: CalendarEventCreate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Create a new calendar event."""
    await _ensure_calendar_job_scope(
        db, current_user, candidate_id=body.candidate_id, job_id=body.job_id
    )
    start_time, end_time = body.start_time, body.end_time
    if body.all_day:
        start_time, end_time = normalize_all_day(start_time, end_time)
    event = CalendarEvent(
        title=body.title,
        description=body.description,
        event_type=body.event_type,
        start_time=start_time,
        end_time=end_time,
        all_day=body.all_day,
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        client_id=body.client_id,
        attendees=body.attendees or [],
        location=body.location,
        teams_link=body.teams_link,
        created_by=current_user.id,
        operational_owner_id=await nominal_task_owner(
            db,
            actor_id=current_user.id,
            job_id=body.job_id,
            candidate_id=body.candidate_id,
        ),
        reminder_minutes=body.reminder_minutes,
        status=EventStatus.scheduled,
    )
    db.add(event)
    await db.flush()
    if _is_contact_handoff_event(event):
        await maybe_sync_calendar_handoff(
            db,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            event_id=event.id,
            scheduled=True,
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )
    await db.commit()
    await db.refresh(event)

    return await _event_response(db, event, current_user)


async def _event_response(
    db: AsyncSession,
    event: CalendarEvent,
    current_user: User,
    *,
    project: bool = False,
) -> CalendarEventResponse:
    """Odpowiedź dla JEDNEGO wydarzenia (tworzenie, odczyt, edycja, odwołanie).

    Wcześniej każda z tych tras składała odpowiedź po swojemu: edycja zwracała
    `job_title=None` i `client_name=None`, więc okno po zapisie „gubiło"
    rekrutację, a nowe pola trafiały tylko do części tras.
    """
    candidate_name = None
    job_title = None
    client_name = None

    if event.candidate_id:
        cand = await db.scalar(
            select(Candidate).where(Candidate.id == event.candidate_id)
        )
        if cand:
            candidate_name = f"{cand.name} {cand.lastname}".strip()
    if event.job_id:
        job_title = await db.scalar(select(Job.title).where(Job.id == event.job_id))
    if event.client_id:
        client_name = await db.scalar(
            select(Client.name).where(Client.id == event.client_id)
        )

    # Projekcja dla uczestnika dotyczy ODCZYTU. Zapis (tworzenie, edycja,
    # odwołanie) wykonał twórca albo rola nadzoru — jak dotąd pełny rekord.
    projected = (
        project_event_fields(event, current_user)
        if project
        else {"attendees": event.attendees or [], "description": event.description}
    )
    feedback_sources = await _feedback_sources_by_event(db, [event.id])
    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=projected["description"],
        event_type=event.event_type.value if event.event_type else "meeting",
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        candidate_id=event.candidate_id,
        candidate_name=candidate_name,
        job_id=event.job_id,
        job_title=job_title,
        client_id=event.client_id,
        client_name=client_name,
        attendees=projected["attendees"],
        location=event.location,
        teams_link=event.teams_link,
        online_meeting_url=event.online_meeting_url,
        recording_url=event.recording_url,
        created_by=event.created_by,
        **await ownership_payload(
            db,
            event.operational_owner_id or event.created_by,
            open_task=event.status == EventStatus.scheduled,
        ),
        reminder_minutes=event.reminder_minutes,
        status=event.status.value if event.status else "scheduled",
        created_at=event.created_at,
        **_event_extras(event, current_user),
        feedback_sources=feedback_sources.get(event.id, []),
    )


@router.get("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    # Anti-enumeration (P1-CALENDAR-01): a caller with no relationship to the
    # event gets the same 404 as a non-existent id — existence is not revealed.
    if not event or not user_can_view_event(event, current_user):
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")
    return await _event_response(db, event, current_user, project=True)


def _is_outlook_event(event: CalendarEvent) -> bool:
    """Wydarzenie żyje w Outlooku — NEXUS trzyma jego kopię z synchronizacji."""
    from app.services.m365.calendar import M365_SOURCE

    return event.external_source == M365_SOURCE and bool(event.external_id)


# Pola, które przy wydarzeniu z Outlooka należą do Outlooka: sync nadpisuje je
# przy każdej zmianie `changeKey`, więc lokalna edycja byłaby cicho cofnięta,
# a uczestnicy i tak dostaliby stary termin. W NEXUSIE edytujemy wtedy
# wyłącznie metadane rekrutacyjne (typ, kandydat, rekrutacja, przypomnienie).
_OUTLOOK_OWNED_FIELDS = frozenset(
    {
        "title",
        "description",
        "start_time",
        "end_time",
        "all_day",
        "location",
        "attendees",
        "teams_link",
    }
)


# 0338 („oba kierunki”): te pola NEXUS umie przepchnąć do Outlooka PATCH-em na
# wydarzeniu organizatora. Uczestników, całodniowości i ręcznego linku Teams
# nie przepychamy — to zmiana zaproszenia, którą zostawiamy Outlookowi.
_OUTLOOK_PUSHABLE_FIELDS = frozenset(
    {"title", "description", "start_time", "end_time", "location"}
)


def _outlook_changed_fields(event: CalendarEvent, changes: dict) -> list[str]:
    if not _is_outlook_event(event):
        return []
    return sorted(
        field
        for field in _OUTLOOK_OWNED_FIELDS & changes.keys()
        if getattr(event, field) != changes[field]
    )


def _reject_outlook_owned_changes(event: CalendarEvent, changes: dict) -> None:
    if not _is_outlook_event(event):
        return
    changed = _outlook_changed_fields(event, changes)
    if changed and not set(changed) <= _OUTLOOK_PUSHABLE_FIELDS:
        raise HTTPException(
            status_code=409,
            detail=(
                "To wydarzenie pochodzi z Outlooka — uczestników, cały dzień "
                "i link do spotkania zmień w Outlooku. W NEXUSIE możesz zmienić "
                "termin, tytuł, miejsce, opis, typ, kandydata, rekrutację "
                "i przypomnienie."
            ),
        )
    if (
        changes.get("status") == EventStatus.cancelled
        and event.status != EventStatus.cancelled
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Wydarzenie z Outlooka odwołaj przyciskiem „Odwołaj” — zmiana "
                "samego statusu nie powiadomi uczestników."
            ),
        )


@router.patch("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: int,
    body: CalendarEventUpdate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    # 404 when the caller may not even see it (anti-enumeration); 403 when they
    # can see it (owner/attendee) but are not allowed to mutate — P1-CALENDAR-01.
    if not event or not user_can_view_event(event, current_user):
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")
    if not user_can_mutate_event(event, current_user):
        raise HTTPException(
            status_code=403, detail="Brak uprawnień do edycji tego wydarzenia"
        )
    # Status `cancelled` przez PATCH to odwołanie — ta sama bramka co
    # `/cancel` i DELETE (HoR poprawia cudze wydarzenia, ale ich nie odwołuje).
    if (
        body.status == EventStatus.cancelled
        and event.status != EventStatus.cancelled
        and not user_can_remove_event(event, current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Odwołać wydarzenie może tylko jego właściciel albo administrator.",
        )

    previous_handoff = (
        event.candidate_id,
        event.job_id,
        event.id,
        _is_contact_handoff_event(event),
    )
    changes = body.model_dump(exclude_unset=True)
    _reject_outlook_owned_changes(event, changes)

    # CAL-01: KAŻDA lokalna odmowa (daty wynikowe, zakres rekrutacji) zapada
    # PRZED wywołaniem Outlooka. Dawniej Graph przyjmował zmianę, a dopiero
    # potem NEXUS odmawiał 403/422 i cofał transakcję — Outlook i NEXUS
    # rozjeżdżały się, a uczestnicy dostawali już powiadomienie o zmianie.
    #
    # Walidacja na WYNIKU, nie na samym żądaniu: PATCH bywa częściowy, więc
    # nowy koniec trzeba porównać z zapisanym początkiem (i odwrotnie).
    new_start = changes.get("start_time", event.start_time)
    new_end = changes.get("end_time", event.end_time)
    new_all_day = changes.get("all_day", event.all_day)
    normalize_all_day_range = bool(new_all_day) and bool(
        changes.keys() & {"all_day", "start_time", "end_time"}
    )
    if (
        not normalize_all_day_range
        and new_start is not None
        and new_end is not None
        and new_end <= new_start
    ):
        raise HTTPException(status_code=422, detail=_END_BEFORE_START)
    # Bramkujemy PRZEJŚCIE `job_id`, nie wartość po mutacji — poprzedni wariant
    # był jednocześnie za surowy i trywialnie omijalny:
    # (a) przy nietkniętym `job_id` odbierał twórcy edycję WŁASNEGO wydarzenia,
    #     gdy tylko wypadł z zespołu oferty. `user_can_mutate_event` wyżej i tak
    #     zawęża do twórcy / admina / HoR, a wydarzenie związane z ofertą mógł
    #     stworzyć tylko ktoś, kto w chwili tworzenia przez tę bramkę przeszedł;
    # (b) jawne `"job_id": null` jest w `exclude_unset`, więc `setattr` zerował
    #     atrybut PRZED sprawdzeniem i `ensure_optional_job_membership` wracał
    #     na `None` — odpięcie od oferty, wraz z rozmontowaniem przekazania
    #     kontaktu (`maybe_remove_calendar_handoff` niżej działa na SNAPSHOCIE),
    #     przechodziło bez żadnej kontroli.
    # Przepięcie i odpięcie wymagają teraz zakresu na obu ofertach — starej
    # (z `previous_handoff`) i nowej. Warunkiem jest FAKTYCZNA zmiana wartości,
    # nie sama obecność klucza: klient odsyłający cały obiekt (a więc i
    # niezmienione `job_id`) nie robi żadnego przepięcia i nie może przez to
    # wrócić do problemu (a).
    new_job_id = changes.get("job_id", event.job_id)
    if "job_id" in changes and new_job_id != previous_handoff[1]:
        await _ensure_calendar_job_scope(
            db,
            current_user,
            candidate_id=previous_handoff[0],
            job_id=previous_handoff[1],
        )
        await _ensure_calendar_job_scope(
            db,
            current_user,
            candidate_id=changes.get("candidate_id", event.candidate_id),
            job_id=new_job_id,
        )

    await _reject_teams_meeting_relink(db, event, changes)
    outlook_fields = _outlook_changed_fields(event, changes)
    if outlook_fields:
        await _push_outlook_changes(db, event, changes, outlook_fields)
    for field, value in changes.items():
        setattr(event, field, value)
    if normalize_all_day_range:
        event.start_time, event.end_time = normalize_all_day(
            event.start_time, event.end_time
        )

    current_handoff = (
        event.candidate_id,
        event.job_id,
        event.id,
        _is_contact_handoff_event(event),
    )
    if previous_handoff[3] and (
        not current_handoff[3] or previous_handoff[:3] != current_handoff[:3]
    ):
        await maybe_remove_calendar_handoff(
            db,
            candidate_id=previous_handoff[0],
            job_id=previous_handoff[1],
            event_id=previous_handoff[2],
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )
    if current_handoff[3]:
        await maybe_sync_calendar_handoff(
            db,
            candidate_id=current_handoff[0],
            job_id=current_handoff[1],
            event_id=current_handoff[2],
            scheduled=True,
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )

    record_calendar_audit(
        db,
        action=CALENDAR_EVENT_UPDATED,
        user_id=current_user.id,
        event_id=event.id,
        override=user_is_override(current_user),
    )
    await db.commit()
    await db.refresh(event)
    return await _event_response(db, event, current_user)


async def _reject_teams_meeting_relink(
    db: AsyncSession, event: CalendarEvent, changes: dict
) -> None:
    """Prep i follow-up w Teams są przypięte do osoby (i rekrutacji) na stałe.

    PATCH ``candidate_id``/``job_id`` zmieniał wydarzenie, a wiersz prepu
    (``prep_meetings``) zostawał przy starej parze: transkrypt, notatka
    i ocena prepu lądowały u innego kandydata niż spotkanie, a zaproszenie
    w Teams i tak miała stara osoba (runda 6 audytu). Zmiana osoby = nowy prep.
    """
    moved = {
        field
        for field in ("candidate_id", "job_id")
        if field in changes and changes[field] != getattr(event, field)
    }
    if not moved:
        return
    from app.services.followup_meetings import followup_for_event
    from app.services.prep_meetings import prep_for_event

    prep = await prep_for_event(db, event.id)
    followup = None if prep else await followup_for_event(db, event.id)
    if prep is not None or (followup is not None and "candidate_id" in moved):
        raise HTTPException(
            status_code=409,
            detail=(
                "To spotkanie w Teams jest założone dla konkretnego kandydata — "
                "nie da się go przepiąć. Odwołaj je i zaplanuj nowe dla właściwej "
                "osoby."
            ),
        )


async def _push_outlook_changes(
    db: AsyncSession, event: CalendarEvent, changes: dict, fields: list[str]
) -> None:
    """Przepchnij zmianę terminu/tytułu do Outlooka ZANIM zapiszemy ją lokalnie.

    Sync nadpisuje pola Outlooka przy każdej zmianie `changeKey`, więc zapis
    tylko w NEXUSIE zostałby cicho cofnięty przy następnej synchronizacji,
    a uczestnicy zostaliby przy starym terminie. Dlatego odwrotnie: najpierw
    Outlook (organizator = twórca wiersza), potem baza. Każda odmowa zostawia
    wydarzenie w NEXUSIE nietknięte.
    """
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import build_update_payload, update_graph_event
    from app.services.m365.graph_client import GraphRequestError
    from app.services.m365.oauth import M365ReauthRequired

    new_start = changes.get("start_time", event.start_time)
    new_end = changes.get("end_time", event.end_time)
    if new_end is not None and new_start is not None and new_end <= new_start:
        raise HTTPException(status_code=422, detail=_END_BEFORE_START)

    # 0370: prep z NEXUSA żyje w kalendarzu organizatora, który zwykle nie ma
    # połączonego konta M365 — zmieniamy go tą samą aplikacją, która go założyła.
    # Follow-up z kandydatem w Teams tak samo (runda 6 audytu).
    from app.services.followup_meetings import app_only_meeting_for_event

    prep = await app_only_meeting_for_event(db, event.id)
    if prep is not None:
        await _push_prep_changes(
            event, prep, changes, fields, new_start=new_start, new_end=new_end
        )
        return

    conn = (
        await db.scalar(
            select(M365Connection).where(M365Connection.user_id == event.created_by)
        )
        if event.created_by is not None
        else None
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status_code=409,
            detail=(
                "Tego wydarzenia nie da się zmienić z NEXUSA — właściciel nie ma "
                "połączonej skrzynki Outlook. Zmień termin w Outlooku albo połącz "
                "skrzynkę w Ustawieniach."
            ),
        )
    payload = build_update_payload(
        title=changes["title"] if "title" in fields else None,
        description=changes.get("description") if "description" in fields else None,
        start=new_start if {"start_time", "end_time"} & set(fields) else None,
        end=new_end if {"start_time", "end_time"} & set(fields) else None,
        location=changes.get("location"),
        set_location="location" in fields,
    )
    try:
        change_key = await update_graph_event(db, conn, event.external_id, payload)
    except M365ReauthRequired as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Połączenie z Outlookiem wygasło — połącz skrzynkę ponownie "
                "w Ustawieniach. W NEXUSIE nic nie zostało zmienione."
            ),
        ) from exc
    except GraphRequestError as exc:
        if exc.status in (400, 403, 404):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Outlook nie pozwolił zmienić tego spotkania — zwykle dlatego, "
                    "że organizuje je ktoś inny. Zmień termin w Outlooku. W NEXUSIE "
                    "nic nie zostało zmienione."
                ),
            ) from exc
        logger.warning("calendar update: Graph %s for event %s", exc.status, event.id)
        raise HTTPException(
            status_code=502,
            detail=(
                "Outlook nie przyjął zmiany — spróbuj ponownie za chwilę. "
                "W NEXUSIE nic nie zostało zmienione."
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — sieć
        logger.exception("calendar update: Graph call failed for %s", event.id)
        raise HTTPException(
            status_code=502,
            detail=(
                "Nie udało się połączyć z Outlookiem. W NEXUSIE nic nie zostało "
                "zmienione."
            ),
        ) from exc
    if change_key:
        event.m365_change_key = change_key


async def _push_prep_changes(
    event: CalendarEvent,
    prep,
    changes: dict,
    fields: list[str],
    *,
    new_start: Optional[datetime],
    new_end: Optional[datetime],
) -> None:
    """Zmiana prepu z NEXUSA w kalendarzu organizatora (app-only, 0370)."""
    from app.services import prep_meetings as prep_meetings_svc
    from app.services.m365 import teams_prep_graph
    from app.services.m365.calendar import build_update_payload
    from app.services.m365.graph_client import GraphRequestError

    moved = bool({"start_time", "end_time"} & set(fields))
    payload = build_update_payload(
        title=changes["title"] if "title" in fields else None,
        description=changes.get("description") if "description" in fields else None,
        start=new_start if moved else None,
        end=new_end if moved else None,
        location=changes.get("location"),
        set_location="location" in fields,
    )
    try:
        change_key = await teams_prep_graph.update_event(
            prep.organizer_upn, event.external_id, payload
        )
    except GraphRequestError as exc:
        logger.warning("prep update: Graph %s for event %s", exc.status, event.id)
        raise HTTPException(
            status_code=502 if exc.status >= 500 else 409,
            detail="Outlook nie przyjął zmiany spotkania w Teams. W NEXUSIE nic nie zostało "
            "zmienione.",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — token, sieć
        logger.warning("prep update: %s for event %s", type(exc).__name__, event.id)
        raise HTTPException(
            status_code=502,
            detail="Nie udało się połączyć z Outlookiem. W NEXUSIE nic nie zostało "
            "zmienione.",
        ) from exc
    if change_key:
        event.m365_change_key = change_key
    if moved and new_end is not None:
        prep_meetings_svc.reschedule_fetch(prep, new_end)


async def _load_mutable_event(
    db: AsyncSession, event_id: int, current_user: User, *, forbidden_detail: str
) -> CalendarEvent:
    """Kontrakt 404/403 jak edycja (P1-CALENDAR-01), ale z bramką usuwania.

    Obaj wołający (odwołanie i usunięcie) kończą życie wydarzenia, więc
    obowiązuje `user_can_remove_event` (właściciel albo admin), nie szersze
    `user_can_mutate_event` — patrz decyzja przy `user_can_remove_event`.
    """
    event = await db.scalar(select(CalendarEvent).where(CalendarEvent.id == event_id))
    if not event or not user_can_view_event(event, current_user):
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")
    if not user_can_remove_event(event, current_user):
        raise HTTPException(status_code=403, detail=forbidden_detail)
    return event


class CalendarEventCancelResponse(BaseModel):
    event: CalendarEventResponse
    # Co stało się po stronie Outlooka:
    # `cancelled` — organizator odwołał, uczestnicy dostali odwołanie;
    # `deleted` — nie jesteśmy organizatorem, wpis zniknął z kalendarza twórcy;
    # `gone` — Outlook już go nie ma; `skipped` — brak aktywnego połączenia
    # M365 twórcy, odwołane tylko w NEXUSIE; `not_applicable` — wydarzenie
    # istnieje tylko w NEXUSIE; `already_cancelled` — nic nie zmieniono.
    outlook: str


@router.post(
    "/calendar/events/{event_id}/cancel",
    response_model=CalendarEventCancelResponse,
)
async def cancel_event(
    event_id: int,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Odwołaj wydarzenie: w Outlooku (gdy stamtąd pochodzi) i w NEXUSIE.

    Do 09.2026 jedyną akcją było „Usuń", które kasowało sam wiersz: spotkanie
    w Outlooku zostawało, uczestnicy nie dostawali odwołania, a najbliższa
    synchronizacja odtwarzała wpis. Odwołanie zostawia wiersz ze statusem
    `cancelled` — z feedbackiem i historią — i jest idempotentne.
    """
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import cancel_graph_event
    from app.services.m365.graph_client import GraphRequestError
    from app.services.m365.oauth import M365ReauthRequired

    event = await _load_mutable_event(
        db,
        event_id,
        current_user,
        forbidden_detail="Brak uprawnień do odwołania tego wydarzenia",
    )
    if event.status == EventStatus.cancelled:
        return CalendarEventCancelResponse(
            event=await _event_response(db, event, current_user),
            outlook="already_cancelled",
        )

    outlook = "not_applicable"
    from app.services.followup_meetings import app_only_meeting_for_event

    # Prep i follow-up w Teams (aplikacja „NEXUS Teams Prep”, runda 6 audytu).
    prep = await app_only_meeting_for_event(db, event.id)
    if prep is not None and _is_outlook_event(event):
        from app.services.m365 import teams_prep_graph

        try:
            outlook = await teams_prep_graph.cancel_event(
                prep.organizer_upn, event.external_id, "Spotkanie zostało odwołane."
            )
        except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
            logger.warning("prep cancel: %s for event %s", type(exc).__name__, event.id)
            raise HTTPException(
                status_code=502,
                detail="Outlook nie przyjął odwołania spotkania w Teams — spróbuj ponownie za "
                "chwilę. W NEXUSIE nic nie zostało zmienione.",
            ) from exc
        if prep.transcript_status == "waiting":
            prep.transcript_status = "cancelled"
    elif _is_outlook_event(event):
        conn = (
            await db.scalar(
                select(M365Connection).where(M365Connection.user_id == event.created_by)
            )
            if event.created_by is not None
            else None
        )
        if conn is None or not conn.is_active:
            outlook = "skipped"
        else:
            try:
                outlook = await cancel_graph_event(db, conn, event.external_id)
            except M365ReauthRequired:
                # Połączenie właśnie przestało być aktywne — ta sama sytuacja
                # co jego brak: odwołujemy lokalnie i mówimy o tym wprost.
                outlook = "skipped"
            except GraphRequestError as exc:
                logger.warning(
                    "calendar cancel: Graph %s for event %s", exc.status, event.id
                )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Outlook nie przyjął odwołania — spróbuj ponownie za chwilę. "
                        "W NEXUSIE nic nie zostało zmienione."
                    ),
                ) from exc
            except Exception as exc:  # noqa: BLE001 — sieć, właściciel bez dostępu
                logger.exception("calendar cancel: Graph call failed for %s", event.id)
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Nie udało się połączyć z Outlookiem. W NEXUSIE nic nie "
                        "zostało zmienione."
                    ),
                ) from exc

    if _is_contact_handoff_event(event):
        await maybe_remove_calendar_handoff(
            db,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            event_id=event.id,
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )
    event.status = EventStatus.cancelled
    record_calendar_audit(
        db,
        action=CALENDAR_EVENT_CANCELLED,
        user_id=current_user.id,
        event_id=event.id,
        override=user_is_override(current_user),
        details={"outlook": outlook},
    )
    await db.commit()
    await db.refresh(event)
    return CalendarEventCancelResponse(
        event=await _event_response(db, event, current_user), outlook=outlook
    )


@router.delete("/calendar/events/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    event = await _load_mutable_event(
        db,
        event_id,
        current_user,
        forbidden_detail="Brak uprawnień do usunięcia tego wydarzenia",
    )
    if _is_outlook_event(event):
        # Skasowany wiersz wracał przy następnej synchronizacji, a spotkanie
        # w Outlooku zostawało bez odwołania.
        raise HTTPException(
            status_code=409,
            detail=(
                "Wydarzenia z Outlooka nie usuwa się w NEXUSIE — użyj „Odwołaj”, "
                "żeby odwołać je także w Outlooku."
            ),
        )
    if _is_contact_handoff_event(event):
        await maybe_remove_calendar_handoff(
            db,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            event_id=event.id,
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )
    record_calendar_audit(
        db,
        action=CALENDAR_EVENT_DELETED,
        user_id=current_user.id,
        event_id=event.id,
        override=user_is_override(current_user),
    )
    await db.delete(event)
    await db.commit()


# ── Conflict detection (Phase 5.4) ────────────────────────────────────────────
#
# Looks at the user's own `CalendarEvent` rows to surface overlaps inside a
# requested window (typically the slot a recruiter is about to book). This is
# complementary to the M365 free-busy endpoint (Phase 4d): free-busy queries
# Microsoft Graph for attendees' Outlook availability, while this endpoint
# stays inside Nexus and answers "do I already have a Nexus interview /
# screening / meeting in this window?".
#
# Default duration when `end_time IS NULL` is 1 hour — same heuristic the M365
# invite path uses for its minimum slot length.

_CONFLICT_DEFAULT_DURATION = timedelta(hours=1)
_CONFLICT_MAX_WINDOW = timedelta(days=7)


class CalendarConflictItem(BaseModel):
    id: int
    title: str
    event_type: str
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    candidate_id: Optional[int]
    candidate_name: Optional[str]


class CalendarConflictsResponse(BaseModel):
    user_id: int
    start: datetime
    end: datetime
    conflicts: list[CalendarConflictItem]


def _validate_window(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="`end` must be after `start`")
    if (end - start) > _CONFLICT_MAX_WINDOW:
        raise HTTPException(
            status_code=422,
            detail=f"window too large (max {_CONFLICT_MAX_WINDOW.days} days)",
        )


def _resolve_scope_user(requested_user_id: Optional[int], current_user) -> int:
    """Default: own events; Finance also has org-wide conflict read access."""
    if requested_user_id is None or requested_user_id == current_user.id:
        return current_user.id
    if not current_user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.finance,
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Cross-user conflict lookups require admin/head_of_recruitment/finance"
            ),
        )
    return requested_user_id


@router.get("/calendar/conflicts", response_model=CalendarConflictsResponse)
async def list_conflicts(
    current_user: RecruitmentReadAccess,
    start: datetime = Query(..., description="Window start (inclusive)"),
    end: datetime = Query(..., description="Window end (exclusive)"),
    exclude_event_id: Optional[int] = Query(
        None, description="Skip this event (use when editing existing)"
    ),
    user_id: Optional[int] = Query(
        None, description="Defaults to current user; admin-only override"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return calendar events that overlap [start, end) for the scoped user.

    Used by ScheduleInterviewModal to warn before booking on top of an existing
    interview/screening.
    """
    _validate_window(start, end)
    scope_user_id = _resolve_scope_user(user_id, current_user)

    effective_end = func.coalesce(
        CalendarEvent.end_time,
        CalendarEvent.start_time + _CONFLICT_DEFAULT_DURATION,
    )

    conditions = [
        func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by).in_(
            await effective_owner_ids(db, scope_user_id)
        ),
        CalendarEvent.status != EventStatus.cancelled,
        # Urlop/OOO z Outlooka to nie rezerwacja slotu — wpis całodniowy
        # kolidowałby z każdą rozmową tego dnia i uczył ignorować ostrzeżenia.
        CalendarEvent.all_day.is_(False),
        CalendarEvent.start_time < end,
        effective_end > start,
    ]
    if exclude_event_id is not None:
        conditions.append(CalendarEvent.id != exclude_event_id)

    rows = (
        (
            await db.execute(
                select(CalendarEvent)
                .where(and_(*conditions))
                .order_by(CalendarEvent.start_time)
            )
        )
        .scalars()
        .all()
    )

    items: list[CalendarConflictItem] = []
    for ev in rows:
        candidate_name = None
        if ev.candidate_id:
            cand = await db.scalar(
                select(Candidate).where(Candidate.id == ev.candidate_id)
            )
            if cand:
                candidate_name = f"{cand.name} {cand.lastname}".strip()
        items.append(
            CalendarConflictItem(
                id=ev.id,
                title=ev.title,
                event_type=ev.event_type.value,
                status=ev.status.value,
                start_time=ev.start_time,
                end_time=ev.end_time,
                candidate_id=ev.candidate_id,
                candidate_name=candidate_name,
            )
        )

    return CalendarConflictsResponse(
        user_id=scope_user_id, start=start, end=end, conflicts=items
    )


class CalendarConflictsSummaryResponse(BaseModel):
    user_id: int
    start: datetime
    end: datetime
    # event_id -> ids of events that overlap with it inside the window
    pairs: dict[int, list[int]]


@router.get(
    "/calendar/conflicts-summary", response_model=CalendarConflictsSummaryResponse
)
async def conflicts_summary(
    current_user: RecruitmentReadAccess,
    start: datetime = Query(...),
    end: datetime = Query(...),
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Map each event in the window to ids of events it overlaps with.

    Frontend uses this to flag conflicting events on the calendar grid without
    having to fan out a per-event request.
    """
    _validate_window(start, end)
    scope_user_id = _resolve_scope_user(user_id, current_user)

    rows = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                CalendarEvent.end_time,
            )
            .where(
                func.coalesce(
                    CalendarEvent.operational_owner_id, CalendarEvent.created_by
                ).in_(await effective_owner_ids(db, scope_user_id)),
                CalendarEvent.status != EventStatus.cancelled,
                # Jak w `/calendar/conflicts`: całodniowy wpis nie jest kolizją.
                CalendarEvent.all_day.is_(False),
                CalendarEvent.start_time < end,
                func.coalesce(
                    CalendarEvent.end_time,
                    CalendarEvent.start_time + _CONFLICT_DEFAULT_DURATION,
                )
                > start,
            )
            .order_by(CalendarEvent.start_time)
        )
    ).all()

    spans = [
        (
            row.id,
            row.start_time,
            row.end_time or (row.start_time + _CONFLICT_DEFAULT_DURATION),
        )
        for row in rows
    ]

    pairs: dict[int, list[int]] = {ev_id: [] for ev_id, _, _ in spans}
    # n is bounded by what fits in 7 days of a single user's calendar — a flat
    # O(n^2) sweep is fine here and keeps the result deterministic.
    for i in range(len(spans)):
        i_id, i_start, i_end = spans[i]
        for j in range(i + 1, len(spans)):
            j_id, j_start, j_end = spans[j]
            if j_start >= i_end:
                # spans are sorted by start_time → no further j can overlap i
                break
            if i_start < j_end and j_start < i_end:
                pairs[i_id].append(j_id)
                pairs[j_id].append(i_id)

    return CalendarConflictsSummaryResponse(
        user_id=scope_user_id, start=start, end=end, pairs=pairs
    )


# ── iCal URL import (Phase 7b.6) ──────────────────────────────────────────────


class ICalImportRequest(BaseModel):
    url: str
    since_days: int = 7
    source_tag: str = "ical"


@router.post("/calendar/import-ical")
async def import_ical(
    body: ICalImportRequest,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pull events from a public iCal feed URL (Outlook/Google publish-as-iCal)."""
    from app.services.ical_import import import_ical_url

    # P0.8: https only (webcal is https under the hood). Plain http is rejected
    # so a feed cannot be pointed at an internal http service.
    raw_url = (body.url or "").strip()
    if not raw_url.startswith(("https://", "webcal://")):
        raise HTTPException(
            status_code=422, detail="URL musi zaczynać się od https:// lub webcal://"
        )
    url = raw_url.replace("webcal://", "https://", 1)
    res = await import_ical_url(
        db,
        url,
        since_days=body.since_days,
        source_tag=body.source_tag,
        creator_id=current_user.id,
    )
    return res.as_dict()


# ── Microsoft 365 calendar invites ────────────────────────────────────────────


class M365InviteRequest(BaseModel):
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    title: str
    description: Optional[str] = ""
    start: datetime
    end: datetime
    event_type: EventType = EventType.interview
    extra_attendees: list[str] = []
    invite_candidate: bool = True
    # Phase 7.1 — opt-in/out of Graph-generated Teams meeting. None lets the
    # service helper apply the event-type default (on for interview/screening).
    add_teams_meeting: Optional[bool] = None
    reminder_minutes: int = 15
    # audyt 22.09 r2 (FIX-08): identyfikator intencji nadany przy OTWARCIU
    # okna tworzenia wydarzenia i powtarzany przy ponowieniach. Z niego
    # powstaje ``transactionId`` Graph. Bez niego ``transactionId`` liczył się
    # z treści, więc świadome utworzenie DRUGIEGO identycznego spotkania
    # (np. druga runda o tej samej porze) Graph traktował jak ponowienie.
    client_request_id: Optional[str] = Field(
        default=None, pattern=r"^[A-Za-z0-9-]{8,64}$"
    )

    @field_validator("reminder_minutes")
    @classmethod
    def _reminder_range(cls, value: int) -> int:
        return _check_reminder(value)


@router.post(
    "/calendar/events/m365-invite",
    response_model=CalendarEventResponse,
    status_code=201,
)
async def create_m365_invite(
    body: M365InviteRequest,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Create a Graph event in the user's Outlook calendar + auto-invite candidate.

    Requires an active `M365Connection`. Falls through to 412 Precondition
    Failed when the user has not connected their mailbox yet.
    """
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import create_event as m365_create_event

    if body.end <= body.start:
        raise HTTPException(status_code=422, detail=_END_BEFORE_START)
    await _ensure_calendar_job_scope(
        db, current_user, candidate_id=body.candidate_id, job_id=body.job_id
    )

    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == current_user.id)
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status_code=412,
            detail="No active Microsoft 365 connection — connect under /settings.",
        )

    if body.invite_candidate and body.candidate_id is None:
        raise HTTPException(status_code=422, detail="candidate is required to invite")
    candidate = (
        await db.get(Candidate, body.candidate_id)
        if body.candidate_id is not None
        else None
    )
    if body.candidate_id is not None and candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if body.invite_candidate and candidate and not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="candidate has no email — cannot invite",
        )

    row = await m365_create_event(
        db,
        conn,
        candidate=candidate,
        title=body.title,
        description=body.description or "",
        start=body.start,
        end=body.end,
        event_type=body.event_type,
        extra_attendees=body.extra_attendees,
        invite_candidate=body.invite_candidate,
        with_teams_meeting=body.add_teams_meeting,
        intent_id=(
            f"invite-form|{current_user.id}|{body.client_request_id}"
            if body.client_request_id
            else None
        ),
    )
    row.job_id = body.job_id
    row.reminder_minutes = body.reminder_minutes
    row.operational_owner_id = await nominal_task_owner(
        db, actor_id=current_user.id, job_id=body.job_id, candidate_id=body.candidate_id
    )
    await db.flush()
    if _is_contact_handoff_event(row):
        await maybe_sync_calendar_handoff(
            db,
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            event_id=row.id,
            scheduled=True,
            actor_user_id=current_user.id,
            occurred_at=datetime.now(timezone.utc),
        )
    await db.commit()
    await db.refresh(row)
    return await _event_response(db, row, current_user)


# ── Background reminder task ──────────────────────────────────────────────────


def _minutes_pl(n: int) -> str:
    if n == 1:
        return "1 minutę"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} minuty"
    return f"{n} minut"


def reminder_due(start: datetime, minutes: int, tick: datetime) -> bool:
    """Czysty bliźniak predykatu `_due_reminder_ids` — ta sama arytmetyka.

    Przypomnienie jest należne, gdy wydarzenie jeszcze się nie zaczęło, a do
    startu zostało nie więcej niż WYBRANE `reminder_minutes` (sufit doba).
    Dolnej granicy okna brak: pierwszy tick po restarcie dogania wszystko, co
    przespał (patrz docstring `calendar_reminder_loop`).
    """
    if minutes <= 0:
        return False
    window = timedelta(minutes=min(minutes, REMINDER_MAX_MINUTES))
    return tick < start <= tick + window


async def _due_reminder_ids(db: AsyncSession, now: datetime) -> list[int]:
    """Wydarzenia, dla których właśnie wypada przypomnienie.

    Do 09.2026 okno było sztywne (16 min), a wybór „5/10/30/60 min" w
    formularzu był martwy. Teraz okno liczy się per wydarzenie z
    `reminder_minutes`: `start_time <= now + make_interval(mins := reminder_minutes)`,
    zapisane jako `start_time - make_interval(...) <= now`, żeby parametr `now`
    stał po stronie porównania z kolumną `timestamptz` (asyncpg nie zgadnie
    typu `$1 + interval`). Wpisy całodniowe (urlop, OOO) i `reminder_minutes = 0`
    nie dostają przypomnienia.
    """
    minutes_interval = func.make_interval(0, 0, 0, 0, 0, CalendarEvent.reminder_minutes)
    return list(
        (
            await db.scalars(
                select(CalendarEvent.id).where(
                    # `> now` zostaje, żeby pętla nie budziła przypomnień dla
                    # wydarzeń, które już się odbyły.
                    CalendarEvent.start_time > now,
                    CalendarEvent.start_time - minutes_interval <= now,
                    CalendarEvent.start_time
                    <= now + timedelta(minutes=REMINDER_MAX_MINUTES),
                    CalendarEvent.reminder_minutes > 0,
                    CalendarEvent.all_day.is_(False),
                    CalendarEvent.status == EventStatus.scheduled,
                    CalendarEvent.reminder_sent_at.is_(None),
                )
            )
        ).all()
    )


async def _dispatch_reminder(event_id: int) -> None:
    """Send one T-15min reminder, durably + atomically.

    Restart-safety (audyt P1): the reminder is deduped by a persisted
    `reminder_sent_at` stamp, not an in-memory set. We claim the row with
    `SELECT ... FOR UPDATE SKIP LOCKED` so at most one worker sends per event
    even with multiple uvicorn workers, then persist the Notification and the
    stamp in the SAME transaction. A restart re-scans the table and skips any
    event that already has a stamp — so no duplicate reminders.

    The WebSocket push happens AFTER commit (best-effort): the Notification row
    is already durable, so a dropped socket only means the user sees it in their
    notification list instead of a live toast.
    """
    # Import here to avoid circular imports
    from app.api import ws as ws_manager

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CalendarEvent)
            .where(CalendarEvent.id == event_id)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            # Locked by another worker or deleted between scan and claim.
            return
        # Re-check under the lock — status may have changed, or another worker
        # may have won the race and already stamped it.
        if event.status != EventStatus.scheduled or event.reminder_sent_at is not None:
            return

        now = datetime.now(timezone.utc)
        if event.all_day or event.reminder_minutes <= 0:
            # Wydarzenie zmieniło się między skanem a blokadą — nie przypominamy,
            # ale stemplujemy, żeby skaner nie wracał do niego co minutę.
            event.reminder_sent_at = now
            await db.commit()
            return
        link = f"/calendar?event={event.id}"
        recipient_id = await effective_owner_id(
            db, event.operational_owner_id or event.created_by
        )
        if not recipient_id:
            # Nothing to notify, but stamp so we don't re-examine it every tick.
            event.reminder_sent_at = now
            await db.commit()
            return

        if not await notification_recipient_has_access(
            db,
            recipient_id,
            NotificationType.interview_scheduled,
            related_entity_type="calendar_event",
            link=link,
        ):
            # Revoked users must not receive either a persisted row or the
            # realtime reminder; stamp the event so the scanner does not spin.
            event.reminder_sent_at = now
            await db.commit()
            return

        # Realna liczba minut do startu, nie deklarowana: tick po restarcie
        # bywa spóźniony, a „Za 15 minut" 3 minuty przed rozmową wprowadza w błąd.
        minutes_left = max(1, round((event.start_time - now).total_seconds() / 60))
        notif = Notification(
            user_id=recipient_id,
            title="Przypomnienie o wydarzeniu",
            message=f"Za {_minutes_pl(minutes_left)}: {event.title}",
            # Link otwiera TO wydarzenie (`?event=`), nie sam kalendarz.
            link=link,
            notification_type=NotificationType.interview_scheduled,
        )
        db.add(notif)
        event.reminder_sent_at = now
        await db.commit()

        # Capture scalars (session uses expire_on_commit=False, so these stay
        # populated) for the post-commit WS push.
        user_id = recipient_id
        payload = {
            "id": notif.id,
            "title": notif.title,
            "message": notif.message,
            "link": notif.link,
            "notification_type": NotificationType.interview_scheduled.value,
            "created_at": now.isoformat(),
        }

    await ws_manager.notify_user(user_id, {"type": "notification", "data": payload})
    logger.info("Reminder sent for event %s to user %s", event_id, user_id)


async def calendar_reminder_loop():
    """
    Background loop that checks every minute for events whose own
    `reminder_minutes` window has opened (see `_due_reminder_ids`)
    and sends reminder notifications to the event creator.

    Dedup is durable (`calendar_events.reminder_sent_at`) and the per-event send
    is atomic (`FOR UPDATE SKIP LOCKED`), so this is safe across restarts and
    multiple uvicorn workers — see `_dispatch_reminder`.

    Okno jest ograniczone TYLKO od góry, i to jest istota poprawki. Wersja
    dwustronna (`>= now+14min AND <= now+16min`) dawała każdemu wydarzeniu
    ledwie 120-sekundowy przedział kwalifikowalności: tick musiał trafić w
    `T ∈ [S-960s, S-840s]`. Każda przerwa między tickami dłuższa niż 2 minuty
    gubiła BEZPOWROTNIE pasmo startów o szerokości `przerwa − 120s` — a przerwy
    tej wielkości są tu rutyną, bo Coolify przebudowuje backend przy każdym
    pushu na main, a `entrypoint.sh` robi alembica i siatkę DDL przed
    `exec uvicorn` (deploy.yml mówi wprost o 4-6 min zimnego builda). Gdy start
    zdarzenia spadł poniżej dolnej granicy, `reminder_sent_at` zostawało NULL
    na zawsze i nikt się o rozmowie nie dowiadywał — bez błędu, bez fallbacku.
    Dolna granica to teraz `now` (a nie `now+14min`), więc pierwszy tick po
    restarcie dogania wszystko, co przespał. Duplikatów to nie tworzy:
    at-most-once gwarantuje trwały stempel + `FOR UPDATE SKIP LOCKED`.
    """
    # MON-04: tick na początku iteracji; cisza dłuższa niż próg = „stalled”.
    beat = loop_heartbeat.register("calendar_reminder", max_silence_seconds=1800)
    while True:
        beat.tick()
        try:
            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                # Bez dolnej granicy `now+14min` — patrz docstring.
                due_ids = await _due_reminder_ids(db, now)

            for event_id in due_ids:
                try:
                    await _dispatch_reminder(event_id)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "calendar reminder dispatch failed for event %s", event_id
                    )

        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # `exception`, nie `warning`: Sentry ma `event_level=logging.ERROR`,
            # więc trwale padający cykl na WARNING nie wygenerowałby żadnego
            # zdarzenia — przypomnienia o rozmowach po prostu przestałyby
            # przychodzić, bez śladu poza logiem kontenera.
            logger.exception("Calendar reminder loop cycle error")

        await asyncio.sleep(60)
