"""Sprzedaż → Aktywności i zadania: telefony, maile, spotkania, zadania, notatki.

Prefiks ``/api/sales/activities`` (wpięty w ``app/main.py``). Jedna tabela
zamiast dwóch z Atlasa (aktywności szansy i firmy). Aktywność przy szansie
należy też do jej firmy. Zrobiona aktywność odświeża „ostatnią aktywność”
szansy — z niej liczymy szanse zaniedbane. Usuwa autor albo admin.

„Dziś” i „po terminie” liczymy w kalendarzu firmy (``app/core/scheduling``).
Lista zadań obejmuje też telefony z terminem (``TASK_KINDS``) — w Atlasie
Task Center pokazywał każdy otwarty rodzaj. Na osi szansy można dołożyć maile
i spotkania jej firmy z Outlooka (``with_company_mail``), jak karta szansy
w Atlasie: synchronizacja przypina je do firmy, nie do szansy. Do szansy
przypina handlowiec (``/pin``, ``services/sales/meeting_decisions``).
Spotkanie z transkryptem Teams niesie na osi podsumowanie, a organizator wysyła
z NEXUSA podsumowanie dla klienta (``services/sales/meeting_client_mail``).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.scheduling import (
    DEFAULT_TZ,
    business_today,
    local_day_bounds,
    local_now,
)
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesMeetingTranscript,
    SalesOpportunity,
    SalesPipelineStage,
)
from app.models.m365 import M365Connection
from app.models.user import User
from app.services import sales_schema as schema
from app.services.action_permissions import ProductAction, has_permission
from app.services.client_duplicates import load_client_name_index
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import (
    client_gate,
    meeting_autopin,
    meeting_client_mail,
    meeting_decisions,
)
from app.services.sales.next_step import not_system_entry
from app.services.sales.task_scope import not_orphaned, task_items
from app.services.sales.timeline import Scope, merge_duplicates

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiej aktywności."
AUTHOR_ONLY_DETAIL = "Aktywność usuwa jej autor albo administrator."
EDIT_AUTHOR_ONLY_DETAIL = (
    "Aktywność poprawia jej autor, osoba przypisana albo administrator."
)
#: Maile i spotkania z Outlooka (Microsoft Graph) — ``external_source`` z Atlasa.
COMPANY_MAIL_SOURCE_PATTERN = "msgraph-%"
MEETING_PREVIEW_CHARS = 300
#: Oś firmy i szansy: największa firma na kopii z 08.11 ma mniej wpisów.
TIMELINE_LIMIT = 500
OUTLOOK_EVENT_SOURCE = "msgraph-event"
#: Pierwszy blok listy spotkań: dziś i najbliższy tydzień.
MEETING_SOON_DAYS = 7
TRANSCRIPT_NOT_FOUND_DETAIL = "To spotkanie nie ma transkryptu."
CLIENT_MAIL_CANDIDATE_DETAIL = (
    "Wśród adresatów jest osoba z bazy kandydatów. Podsumowań z Sprzedaży do "
    "kandydatów nie wysyłamy: usuń ten adres."
)
CLIENT_MAIL_ORGANIZER_DETAIL = (
    "Podsumowanie dla klienta wysyła organizator spotkania albo administrator."
)

Kind = Literal[schema.ACTIVITY_KINDS]  # type: ignore[valid-type]
Priority = Literal[schema.PRIORITIES]  # type: ignore[valid-type]
TaskKind = Literal[schema.TASK_KINDS]  # type: ignore[valid-type]


class ActivityFields(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=500)
    body: Optional[str] = Field(default=None, max_length=50_000)
    priority: Optional[Priority] = None
    due_at: Optional[datetime] = None
    occurred_at: Optional[datetime] = None
    contact_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    is_pinned: Optional[bool] = None


class ActivityCreate(ActivityFields):
    kind: Kind
    company_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    done: bool = False


class ActivityUpdate(ActivityFields):
    kind: Optional[Kind] = None


class CompleteTasksRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class CompleteTasksOut(BaseModel):
    updated: int


class Ref(BaseModel):
    id: int
    name: str


class ActivityOut(BaseModel):
    id: int
    kind: str
    subject: Optional[str]
    body: Optional[str]
    priority: Optional[str]
    due_at: Optional[datetime]
    occurred_at: Optional[datetime]
    done_at: Optional[datetime]
    is_pinned: bool
    company: Optional[Ref]
    opportunity: Optional[Ref]
    contact: Optional[Ref]
    assignee: Optional[Ref]
    author: Optional[Ref]
    overdue: bool
    created_at: datetime
    external_source: Optional[str] = None
    web_link: Optional[str] = None
    direction: Optional[str] = None
    duration_minutes: Optional[int] = None
    #: Wynik rozmowy zapisanej z karty szansy (``CALL_OUTCOMES``).
    outcome: Optional[str] = None
    #: Mail albo spotkanie firmy dołożone do osi szansy (``with_company_mail``).
    from_company: bool = False


class TaskList(BaseModel):
    items: list[ActivityOut]
    total: int


class TimelineItem(ActivityOut):
    scope: Scope
    #: Skąd wpis: po sklejeniu duplikatów może być kilka źródeł.
    sources: list[str]
    #: Spotkanie z pobranym transkryptem Teams: aktywność z Outlooka, przy której
    #: leży transkrypt (po sklejeniu duplikatów nie musi to być ``id`` wiersza).
    transcript_activity_id: Optional[int] = None
    transcript_summary: Optional[str] = None
    #: Organizator spotkania albo admin z „Sprzedaż: edycja”.
    can_send_client_summary: bool = False
    client_mail_sent_at: Optional[datetime] = None


class TimelineCounts(BaseModel):
    all: int
    opportunity: int
    company: int
    other_opportunity: int


class TimelineOut(BaseModel):
    items: list[TimelineItem]
    counts: TimelineCounts


MeetingDecision = Literal[
    "linked", "client", "internal", "create", "pin", "choose", "company_only"
]
MeetingTiming = Literal["soon", "past", "later"]


class MeetingOpportunityOption(BaseModel):
    id: int
    title: str
    stage_name: str
    value: Optional[Decimal]
    currency: str


class MeetingOut(ActivityOut):
    transcript_status: Optional[str] = None
    transcript_summary: Optional[str] = None
    #: Co handlowiec ma zrobić z tym spotkaniem (kolumna „Co dalej”).
    decision: MeetingDecision = "company_only"
    timing: MeetingTiming = "past"
    can_unpin: bool = False
    #: Przypiął je automat, bo firma miała jedną otwartą szansę (``meeting_autopin``).
    auto_pinned: bool = False
    open_opportunities: list[MeetingOpportunityOption] = Field(default_factory=list)
    client_name: Optional[str] = None
    delivery_lead: Optional[str] = None


class MeetingCounts(BaseModel):
    pin: int
    create: int
    upcoming: int


class MeetingList(BaseModel):
    items: list[MeetingOut]
    total: int
    counts: MeetingCounts


class PinRequest(BaseModel):
    opportunity_id: int


class MeetingDraftPerson(BaseModel):
    id: int
    name: str
    title: Optional[str]
    attended: bool


class MeetingDraftOut(BaseModel):
    company: Ref
    occurred_at: Optional[datetime]
    duration_minutes: Optional[int]
    suggested_title: str
    attendees_known: bool
    people: list[MeetingDraftPerson]


class MeetingTranscriptOut(BaseModel):
    subject: Optional[str]
    summary: Optional[str]
    plain_text: str


class ClientMailRecipient(BaseModel):
    address: str
    name: Optional[str]
    blocked: Optional[Literal["candidate"]] = None


class ClientMailDraftOut(BaseModel):
    subject: str
    body: str
    #: Model nie dał szkicu: okno zostawia puste pole do napisania ręcznie.
    model_failed: bool
    recipients: list[ClientMailRecipient]
    mailbox: Literal["ok", "missing", "no_send_scope"]
    sender_address: Optional[str]
    sent_at: Optional[datetime]


class ClientMailSend(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)
    to: list[str] = Field(min_length=1, max_length=meeting_client_mail.MAX_RECIPIENTS)
    #: Nadawany przy otwarciu okna: drugi klik z tym samym kluczem nie wysyła drugi raz.
    request_id: UUID
    #: Karta, z której wysłano; liczy się tylko dla spotkania nieprzypiętego.
    opportunity_id: Optional[int] = None


def _ref(id_: Optional[int], name: Optional[str]) -> Optional[Ref]:
    return Ref(id=id_, name=name or "") if id_ is not None else None


def _base_query():
    assignee = aliased(User)
    author = aliased(User)
    return (
        select(
            SalesActivity,
            SalesCompany.name.label("company_name"),
            SalesOpportunity.title.label("opportunity_title"),
            SalesContact.full_name.label("contact_name"),
            assignee.name.label("assignee_name"),
            author.name.label("author_name"),
        )
        .outerjoin(SalesCompany, SalesCompany.id == SalesActivity.company_id)
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
        )
        .outerjoin(SalesContact, SalesContact.id == SalesActivity.contact_id)
        .outerjoin(assignee, assignee.id == SalesActivity.assignee_user_id)
        .outerjoin(author, author.id == SalesActivity.created_by_user_id)
    )


def _is_open_item(kind: str, due_at: Optional[datetime]) -> bool:
    """Zadanie albo telefon z terminem — pozycja listy zadań, nie wpis historii."""

    return kind == "task" or (kind in schema.TASK_KINDS and due_at is not None)


def _out(row, now: datetime, *, from_company: bool = False) -> ActivityOut:
    activity: SalesActivity = row.SalesActivity
    return ActivityOut(
        id=activity.id,
        kind=activity.kind,
        subject=activity.subject,
        body=activity.body,
        priority=activity.priority,
        due_at=activity.due_at,
        occurred_at=activity.occurred_at,
        done_at=activity.done_at,
        is_pinned=activity.is_pinned,
        company=_ref(activity.company_id, row.company_name),
        opportunity=_ref(activity.opportunity_id, row.opportunity_title),
        contact=_ref(activity.contact_id, row.contact_name),
        assignee=_ref(activity.assignee_user_id, row.assignee_name),
        author=_ref(activity.created_by_user_id, row.author_name),
        overdue=(
            activity.done_at is None
            and activity.due_at is not None
            and activity.due_at < now
        ),
        created_at=activity.created_at,
        external_source=activity.external_source,
        web_link=activity.web_link,
        direction=activity.direction,
        duration_minutes=activity.duration_minutes,
        outcome=activity.outcome,
        from_company=from_company,
    )


async def _load(db: AsyncSession, activity_id: int) -> ActivityOut:
    row = (
        await db.execute(_base_query().where(SalesActivity.id == activity_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return _out(row, datetime.now(timezone.utc))


async def _touch_opportunity(
    db: AsyncSession, activity: SalesActivity, when: datetime
) -> None:
    """Zrobiona aktywność (nie zaplanowane zadanie) to ślad pracy przy szansie."""

    if activity.opportunity_id is None:
        return
    if activity.kind in schema.TASK_KINDS and activity.done_at is None:
        return
    opp = await db.get(SalesOpportunity, activity.opportunity_id)
    if opp is not None and (
        opp.last_activity_at is None or opp.last_activity_at < when
    ):
        opp.last_activity_at = when


async def _check_links(db: AsyncSession, fields: dict) -> None:
    contact_id = fields.get("contact_id")
    if contact_id is not None and await db.get(SalesContact, contact_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiego kontaktu."
        )
    assignee_id = fields.get("assignee_user_id")
    if assignee_id is not None:
        user = await db.get(User, assignee_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Zadanie przypisz aktywnemu kontu w NEXUSIE.",
            )


async def _default_assignee(
    db: AsyncSession, opportunity_id: Optional[int], author_id: int
) -> int:
    """Zadanie przy szansie należy do jej opiekuna (decyzja Artura 28.10.2026).

    Bez szansy albo bez aktywnego opiekuna zostaje u autora: na koncie
    nieaktywnym nikt by go nie zobaczył.
    """

    if opportunity_id is not None:
        owner_id = await db.scalar(
            select(User.id)
            .join(SalesOpportunity, SalesOpportunity.owner_user_id == User.id)
            .where(SalesOpportunity.id == opportunity_id, User.is_active.is_(True))
        )
        if owner_id is not None:
            return owner_id
    return author_id


@router.get("", response_model=list[ActivityOut])
async def list_activities(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    company_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    kind: Optional[Kind] = None,
    with_company_mail: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ActivityOut]:
    """Oś czasu firmy albo szansy: najpierw przypięte, potem od najnowszych."""

    if company_id is None and opportunity_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Podaj firmę albo szansę, której historię chcesz zobaczyć.",
        )
    query = _base_query()
    if company_id is not None:
        query = query.where(SalesActivity.company_id == company_id)
    if opportunity_id is not None:
        scope = SalesActivity.opportunity_id == opportunity_id
        mail_company_id = (
            await db.scalar(
                select(SalesOpportunity.company_id).where(
                    SalesOpportunity.id == opportunity_id
                )
            )
            if with_company_mail
            else None
        )
        if mail_company_id is not None:
            scope = or_(
                scope,
                and_(
                    SalesActivity.company_id == mail_company_id,
                    SalesActivity.opportunity_id.is_(None),
                    SalesActivity.external_source.like(COMPANY_MAIL_SOURCE_PATTERN),
                ),
            )
        query = query.where(scope)
    if kind:
        query = query.where(SalesActivity.kind == kind)
    rows = (
        await db.execute(
            query.order_by(
                SalesActivity.is_pinned.desc(),
                func.coalesce(
                    SalesActivity.occurred_at, SalesActivity.created_at
                ).desc(),
                SalesActivity.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    now = datetime.now(timezone.utc)
    return [
        _out(
            row,
            now,
            from_company=(
                opportunity_id is not None
                and row.SalesActivity.opportunity_id != opportunity_id
            ),
        )
        for row in rows
    ]


@router.get("/timeline", response_model=TimelineOut)
async def opportunity_timeline(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=TIMELINE_LIMIT, ge=1, le=TIMELINE_LIMIT),
) -> TimelineOut:
    """Oś szansy i jej firmy: skąd jest wpis, jedno zdarzenie w jednym wierszu."""

    company_id = await db.scalar(
        select(SalesOpportunity.company_id).where(SalesOpportunity.id == opportunity_id)
    )
    if company_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie ma takiej szansy.")
    rows = (
        await db.execute(
            _base_query()
            .where(
                or_(
                    SalesActivity.opportunity_id == opportunity_id,
                    SalesActivity.company_id == company_id,
                ),
                not_system_entry(),
            )
            .order_by(
                func.coalesce(
                    SalesActivity.occurred_at, SalesActivity.created_at
                ).desc(),
                SalesActivity.id.desc(),
            )
            .limit(limit)
        )
    ).all()
    now = datetime.now(timezone.utc)
    by_id = {row.SalesActivity.id: row for row in rows}
    entries = merge_duplicates([row.SalesActivity for row in rows])
    transcripts = await _timeline_transcripts(db, entries)
    may_edit = has_permission(current_user, ProductAction.sales_edit)
    admin = is_admin(current_user)
    items = []
    for entry in entries:
        found = next(
            (
                (member.id, transcripts[member.external_id])
                for member in entry.members
                if member.external_source == OUTLOOK_EVENT_SOURCE
                and member.external_id in transcripts
            ),
            None,
        )
        meeting_id, transcript = found or (None, None)
        items.append(
            TimelineItem(
                **{
                    **_out(by_id[entry.activity.id], now).model_dump(),
                    "body": entry.body,
                    "web_link": entry.web_link,
                },
                scope=entry.scope(opportunity_id),
                sources=entry.sources,
                transcript_activity_id=meeting_id,
                transcript_summary=transcript.summary if transcript else None,
                can_send_client_summary=bool(
                    transcript
                    and may_edit
                    and meeting_client_mail.may_send(
                        current_user.id, transcript, admin=admin
                    )
                ),
                client_mail_sent_at=(
                    transcript.client_mail_sent_at if transcript else None
                ),
            )
        )
    tally = Counter(item.scope for item in items)
    return TimelineOut(
        items=items,
        counts=TimelineCounts(
            all=len(items),
            opportunity=tally["opportunity"],
            company=tally["company"],
            other_opportunity=tally["other_opportunity"],
        ),
    )


async def _timeline_transcripts(
    db: AsyncSession, entries
) -> dict[str, SalesMeetingTranscript]:
    """Pobrane transkrypty spotkań z osi, po ``iCalUId``."""

    uids = {
        member.external_id
        for entry in entries
        for member in entry.members
        if member.kind == "meeting"
        and member.external_source == OUTLOOK_EVENT_SOURCE
        and member.external_id
    }
    if not uids:
        return {}
    found = await db.scalars(
        select(SalesMeetingTranscript).where(
            SalesMeetingTranscript.ical_uid.in_(uids),
            SalesMeetingTranscript.status == "fetched",
        )
    )
    return {row.ical_uid: row for row in found.all()}


@router.get("/tasks", response_model=TaskList)
async def list_tasks(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["mine", "team"] = "mine",
    bucket: Literal["open", "overdue", "today", "done"] = "open",
    kind: Optional[TaskKind] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TaskList:
    """Zadania i telefony z terminem (Task Center z Atlasa)."""

    query = _base_query().where(task_items())
    if kind:
        query = query.where(SalesActivity.kind == kind)
    if scope == "mine":
        query = query.where(SalesActivity.assignee_user_id == current_user.id)
    now = datetime.now(timezone.utc)
    day = local_day_bounds(local_now())
    if bucket == "done":
        query = query.where(SalesActivity.done_at.is_not(None))
        order = (SalesActivity.done_at.desc(), SalesActivity.id.desc())
    else:
        query = query.where(SalesActivity.done_at.is_(None), not_orphaned())
        if bucket == "overdue":
            query = query.where(SalesActivity.due_at < now)
        elif bucket == "today":
            query = query.where(
                SalesActivity.due_at >= day.start_utc,
                SalesActivity.due_at <= day.end_utc,
            )
        order = (SalesActivity.due_at.asc().nulls_last(), SalesActivity.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(*order).limit(limit).offset(offset))).all()
    return TaskList(items=[_out(row, now) for row in rows], total=int(total or 0))


def _outlook_source():
    return func.coalesce(SalesActivity.external_source, "").like(
        COMPANY_MAIL_SOURCE_PATTERN
    )


async def _meeting_options(
    db: AsyncSession, company_ids: set[int]
) -> dict[int, list[MeetingOpportunityOption]]:
    """Otwarte szanse firm z bieżącej strony: najpierw największe."""

    if not company_ids:
        return {}
    rows = (
        await db.execute(
            select(SalesOpportunity, SalesPipelineStage.name)
            .join(
                SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
            )
            .where(
                SalesOpportunity.company_id.in_(company_ids),
                SalesOpportunity.status == "open",
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.value.desc().nulls_last(), SalesOpportunity.id)
        )
    ).all()
    options: dict[int, list[MeetingOpportunityOption]] = {}
    for opportunity, stage_name in rows:
        options.setdefault(opportunity.company_id, []).append(
            MeetingOpportunityOption(
                id=opportunity.id,
                title=opportunity.title,
                stage_name=stage_name,
                value=opportunity.value,
                currency=opportunity.currency,
            )
        )
    return options


@router.get("/meetings", response_model=MeetingList)
async def list_meetings(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, max_length=200),
    linked: Optional[Literal["opportunity", "company"]] = None,
    has_transcript: bool = False,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    mine: bool = False,
    queue: Optional[Literal["pin", "create"]] = None,
    upcoming: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> MeetingList:
    """Wszystkie spotkania w jednym miejscu, przy każdym decyzja, co z nim zrobić.

    Jedno spotkanie to jeden wiersz, także gdy synchronizacja dopasowała je do
    kilku firm: najpierw kopia już przypięta, potem firma, przy której jest co
    zrobić (nie nasza spółka ani klient NEXUSA), a w niej ta z otwartą szansą.
    Tak samo para z importu Atlasa: nagranie przy szansie i wydarzenie z kalendarza.
    Kolejność: dziś i najbliższy tydzień, potem przeszłe, na końcu dalsza
    przyszłość, bo tam lądują błędne daty z kalendarza.
    """

    held_at = func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at)
    held_day = func.date(func.timezone(DEFAULT_TZ, held_at))
    today = business_today()
    names = await load_client_name_index(db)
    # Alias, bo szansa aktywności jest też w FROM zapytania głównego.
    company_opportunity = aliased(SalesOpportunity)
    open_count = (
        select(func.count(company_opportunity.id))
        .where(
            company_opportunity.company_id == SalesActivity.company_id,
            company_opportunity.status == "open",
            company_opportunity.archived_at.is_(None),
        )
        .correlate(SalesActivity)
        .scalar_subquery()
    )
    is_client = func.coalesce(
        or_(
            SalesCompany.client_id.in_(sorted(names.display_by_id)),
            SalesCompany.normalized_name.in_(sorted(names.ids_by_key)),
        ),
        False,
    )
    is_own_company = func.coalesce(
        SalesCompany.normalized_name == client_gate.OWN_COMPANY_KEY, False
    )
    decision = case(
        (SalesActivity.opportunity_id.is_not(None), "linked"),
        (
            or_(SalesActivity.company_id.is_(None), ~_outlook_source()),
            "company_only",
        ),
        (is_own_company, "internal"),
        (is_client, "client"),
        (open_count == 0, "create"),
        (open_count == 1, "pin"),
        else_="choose",
    )
    timing = case(
        (held_day < today, "past"),
        (held_day < today + timedelta(days=MEETING_SOON_DAYS), "soon"),
        else_="later",
    )
    same_meeting = func.coalesce(
        SalesActivity.external_source + "|" + SalesActivity.external_id,
        cast(SalesActivity.id, String),
    )
    # Import z Atlasa dał to samo spotkanie dwa razy: nagranie przy szansie
    # i wydarzenie z kalendarza. Wspólne mają firmę, minutę i temat.
    same_slot = func.coalesce(
        cast(SalesActivity.company_id, String)
        + "|"
        + cast(func.date_trunc("minute", held_at), String)
        + "|"
        + func.lower(SalesActivity.subject),
        cast(SalesActivity.id, String),
    )
    matching = (
        select(
            SalesActivity.id.label("id"),
            held_at.label("held_at"),
            decision.label("decision"),
            timing.label("timing"),
            same_slot.label("same_slot"),
            func.row_number()
            .over(
                partition_by=same_meeting,
                order_by=(
                    SalesActivity.opportunity_id.is_(None),
                    is_own_company,
                    is_client,
                    (open_count == 0),
                    SalesActivity.company_id,
                    SalesActivity.id,
                ),
            )
            .label("copy_rank"),
        )
        .select_from(SalesActivity)
        .outerjoin(SalesCompany, SalesCompany.id == SalesActivity.company_id)
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
        )
        .outerjoin(
            SalesMeetingTranscript,
            and_(
                SalesActivity.external_source == OUTLOOK_EVENT_SOURCE,
                SalesActivity.external_id == SalesMeetingTranscript.ical_uid,
            ),
        )
        .where(SalesActivity.kind == "meeting")
    )
    if mine:
        matching = matching.where(SalesActivity.created_by_user_id == current_user.id)
    if linked == "opportunity":
        matching = matching.where(SalesActivity.opportunity_id.is_not(None))
    elif linked == "company":
        matching = matching.where(SalesActivity.opportunity_id.is_(None))
    if has_transcript:
        matching = matching.where(SalesMeetingTranscript.status == "fetched")
    if date_from is not None:
        matching = matching.where(held_day >= date_from)
    if date_to is not None:
        matching = matching.where(held_day <= date_to)
    text = (q or "").strip()
    if text:
        matching = matching.where(
            or_(
                polish_folded_ilike(func.coalesce(SalesActivity.subject, ""), text),
                polish_folded_ilike(func.coalesce(SalesCompany.name, ""), text),
                polish_folded_ilike(func.coalesce(SalesOpportunity.title, ""), text),
            )
        )
    ranked = matching.subquery()
    one_copy = select(ranked).where(ranked.c.copy_rank == 1).subquery()
    slotted = select(
        one_copy,
        func.row_number()
        .over(
            partition_by=one_copy.c.same_slot,
            order_by=(one_copy.c.decision != "linked", one_copy.c.id),
        )
        .label("slot_rank"),
    ).subquery()
    meetings = select(slotted).where(slotted.c.slot_rank == 1).subquery()

    to_pin = meetings.c.decision.in_(("pin", "choose"))
    to_create = meetings.c.decision == "create"
    ahead = meetings.c.timing != "past"
    in_queue = {"pin": to_pin, "create": to_create}.get(queue or "")
    in_period = ahead if upcoming else None
    wanted = [condition for condition in (in_queue, in_period) if condition is not None]
    period_only = [in_period] if in_period is not None else []
    queue_only = [in_queue] if in_queue is not None else []
    totals = (
        await db.execute(
            select(
                func.count().filter(*wanted).label("total")
                if wanted
                else func.count().label("total"),
                func.count().filter(to_pin, *period_only).label("pin"),
                func.count().filter(to_create, *period_only).label("create"),
                func.count().filter(ahead, *queue_only).label("upcoming"),
            ).select_from(meetings)
        )
    ).one()

    block = case(
        (meetings.c.timing == "soon", 0), (meetings.c.timing == "past", 1), else_=2
    )
    epoch = func.extract("epoch", meetings.c.held_at)
    page = (
        await db.execute(
            select(meetings.c.id, meetings.c.decision, meetings.c.timing)
            .where(*wanted)
            .order_by(
                block,
                case((meetings.c.timing == "past", -epoch), else_=epoch),
                meetings.c.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    ids = [row.id for row in page]
    rows = (
        await db.execute(
            _base_query()
            .add_columns(
                SalesMeetingTranscript.status.label("transcript_status"),
                SalesMeetingTranscript.summary.label("transcript_summary"),
                SalesCompany.client_id.label("company_client_id"),
                SalesCompany.normalized_name.label("company_key"),
            )
            .outerjoin(
                SalesMeetingTranscript,
                and_(
                    SalesActivity.external_source == OUTLOOK_EVENT_SOURCE,
                    SalesActivity.external_id == SalesMeetingTranscript.ical_uid,
                ),
            )
            .where(SalesActivity.id.in_(ids or [-1]))
        )
    ).all()
    row_by_id = {row.SalesActivity.id: row for row in rows}
    options = await _meeting_options(
        db,
        {
            row_by_id[item.id].SalesActivity.company_id
            for item in page
            if item.decision in ("pin", "choose")
        },
    )
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=row_by_id[item.id].SalesActivity.company_id,
                client_id=row_by_id[item.id].company_client_id,
                normalized_name=row_by_id[item.id].company_key,
            )
            for item in page
            if item.decision == "client"
        ],
    )
    linked_ids = [item.id for item in page if item.decision == "linked"]
    pinned_by_automat = (
        set(
            (
                await db.scalars(
                    select(SalesActivity.id).where(
                        SalesActivity.id.in_(linked_ids),
                        meeting_autopin.auto_pinned(SalesActivity.id),
                    )
                )
            ).all()
        )
        if linked_ids
        else set()
    )
    now = datetime.now(timezone.utc)
    items = []
    for item in page:
        row = row_by_id[item.id]
        base = _out(row, now)
        # Transkrypcja z Atlasa potrafi mieć setki kB, a lista pokazuje jedną linię.
        base.body = base.body[:MEETING_PREVIEW_CHARS] if base.body else base.body
        company_id = row.SalesActivity.company_id
        client = clients.get(company_id) if item.decision == "client" else None
        items.append(
            MeetingOut(
                **base.model_dump(),
                transcript_status=row.transcript_status,
                transcript_summary=row.transcript_summary,
                decision=item.decision,
                timing=item.timing,
                can_unpin=(
                    item.decision == "linked"
                    and meeting_decisions.is_outlook(row.SalesActivity)
                ),
                auto_pinned=item.id in pinned_by_automat,
                open_opportunities=(
                    options.get(company_id, [])
                    if item.decision in ("pin", "choose")
                    else []
                ),
                client_name=client.client_name if client else None,
                delivery_lead=client.delivery_lead if client else None,
            )
        )
    return MeetingList(
        items=items,
        total=int(totals.total),
        counts=MeetingCounts(
            pin=int(totals.pin),
            create=int(totals.create),
            upcoming=int(totals.upcoming),
        ),
    )


@router.get("/{activity_id}/opportunity-draft", response_model=MeetingDraftOut)
async def meeting_opportunity_draft(
    activity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingDraftOut:
    """Podpowiedzi do okna „Załóż szansę”: temat bez znaczników i uczestnicy."""

    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    company = (
        await db.get(SalesCompany, activity.company_id)
        if activity.company_id is not None
        else None
    )
    if company is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="To spotkanie nie jest przy żadnej firmie.",
        )
    people = await meeting_decisions.company_people(db, company.id)
    attended = await meeting_decisions.attendee_contact_ids(db, activity, people)
    return MeetingDraftOut(
        company=Ref(id=company.id, name=company.name),
        occurred_at=activity.occurred_at,
        duration_minutes=activity.duration_minutes,
        suggested_title=(
            meeting_decisions.clean_meeting_title(activity.subject) or company.name
        ),
        attendees_known=bool(attended),
        people=[
            MeetingDraftPerson(
                id=person.id,
                name=person.full_name,
                title=person.title,
                attended=person.id in attended,
            )
            for person in people
        ],
    )


@router.get("/{activity_id}/transcript", response_model=MeetingTranscriptOut)
async def meeting_transcript(
    activity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingTranscriptOut:
    """Pełny transkrypt Teams; lista niesie samo podsumowanie."""

    row = (
        await db.execute(
            select(SalesActivity.subject, SalesMeetingTranscript)
            .join(
                SalesMeetingTranscript,
                and_(
                    SalesActivity.external_source == OUTLOOK_EVENT_SOURCE,
                    SalesActivity.external_id == SalesMeetingTranscript.ical_uid,
                ),
            )
            .where(
                SalesActivity.id == activity_id,
                SalesMeetingTranscript.status == "fetched",
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=TRANSCRIPT_NOT_FOUND_DETAIL
        )
    subject, transcript = row
    return MeetingTranscriptOut(
        subject=subject,
        summary=transcript.summary,
        plain_text=transcript.plain_text or "",
    )


async def _client_mail_meeting(
    db: AsyncSession, activity_id: int, user: User, *, lock: bool = False
) -> meeting_client_mail.Meeting:
    meeting = await meeting_client_mail.load(db, activity_id, lock=lock)
    if meeting is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=TRANSCRIPT_NOT_FOUND_DETAIL
        )
    if not meeting_client_mail.may_send(
        user.id, meeting.transcript, admin=is_admin(user)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=CLIENT_MAIL_ORGANIZER_DETAIL
        )
    return meeting


async def _own_connection(db: AsyncSession, user_id: int) -> Optional[M365Connection]:
    return await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )


@router.get("/{activity_id}/client-summary", response_model=ClientMailDraftOut)
async def meeting_client_summary_draft(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ClientMailDraftOut:
    """Szkic maila do klienta po spotkaniu: treść z modelu, adresaci spoza firmy."""

    meeting = await _client_mail_meeting(db, activity_id, current_user)
    connection = await _own_connection(db, current_user.id)
    sender_address = connection.mailbox_upn if connection is not None else None
    subject = meeting_client_mail.default_subject(meeting.activity)
    sent_at = meeting.transcript.client_mail_sent_at
    recipients = await meeting_client_mail.attendees(
        db, meeting.activity, sender_address or meeting.transcript.organizer_upn
    )
    mailbox = meeting_client_mail.mailbox_state(connection)
    body, model_failed = await meeting_client_mail.client_summary(
        db, meeting, user_id=current_user.id
    )
    return ClientMailDraftOut(
        subject=subject,
        body=body,
        model_failed=model_failed,
        recipients=[
            ClientMailRecipient(
                address=recipient.address,
                name=recipient.name,
                blocked=recipient.blocked,
            )
            for recipient in recipients
        ],
        mailbox=mailbox,
        sender_address=sender_address,
        sent_at=sent_at,
    )


@router.post("/{activity_id}/client-summary/send", response_model=ActivityOut)
async def send_meeting_client_summary(
    activity_id: int,
    payload: ClientMailSend,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    """Wyślij podsumowanie klientowi ze swojej skrzynki i zapisz mail na osi szansy."""

    # Najpierw organizator albo admin: odpowiedź o adresach kandydatów nie może
    # trafić do kogoś, kto tego spotkania nie wysyła.
    await _client_mail_meeting(db, activity_id, current_user)
    addresses: list[str] = []
    invalid: list[str] = []
    for value in payload.to:
        address = meeting_client_mail.normalize_address(value)
        if address is None:
            invalid.append(value.strip()[:80])
        elif address not in addresses:
            addresses.append(address)
    if invalid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Niepoprawny adres: {', '.join(invalid)}.",
        )
    subject = payload.subject.strip()
    body = payload.body.strip()
    if not subject or not body:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mail musi mieć temat i treść.",
        )
    # Bramka kandydatów zostaje: ta ścieżka nie pisze do osób z bazy kandydatów.
    # Bez wymieniania adresów, żeby wpisywanie nie sprawdzało, kto jest w bazie.
    if await meeting_client_mail.candidate_addresses(db, addresses):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=CLIENT_MAIL_CANDIDATE_DETAIL,
        )
    connection = await _own_connection(db, current_user.id)
    mailbox = meeting_client_mail.mailbox_state(connection)
    if mailbox != "ok":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Podłącz skrzynkę Outlook w Sprzedaży, żeby wysłać mail."
                if mailbox == "missing"
                else "Połącz skrzynkę Outlook ponownie: brakuje zgody na wysyłkę."
            ),
        )

    meeting = await _client_mail_meeting(db, activity_id, current_user, lock=True)
    request_id = str(payload.request_id)
    if meeting.transcript.client_mail_request_id == request_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ten mail jest już wysyłany albo wyszedł. Sprawdź oś szansy.",
        )
    opportunity_id = meeting.activity.opportunity_id
    if opportunity_id is None and payload.opportunity_id is not None:
        card = await db.get(SalesOpportunity, payload.opportunity_id)
        if card is not None and card.company_id == meeting.activity.company_id:
            opportunity_id = card.id
    transcript_id = meeting.transcript.id
    meeting.transcript.client_mail_request_id = request_id
    await db.commit()  # klucz widzi drugie żądanie, zanim mail wyjdzie

    try:
        draft = await meeting_client_mail.deliver(
            db, connection, subject=subject, body=body, to=addresses
        )
    except meeting_client_mail.Undelivered:
        await db.rollback()
        row = await db.get(
            SalesMeetingTranscript, transcript_id, populate_existing=True
        )
        if row is not None and row.client_mail_request_id == request_id:
            row.client_mail_request_id = None
            await db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Outlook nie przyjął maila. Nic nie wyszło, spróbuj ponownie.",
        )
    except meeting_client_mail.Uncertain:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Nie wiadomo, czy mail wyszedł. Sprawdź folder Wysłane w Outlooku, "
                "zanim spróbujesz ponownie."
            ),
        )

    now = datetime.now(timezone.utc)
    row = await db.get(SalesMeetingTranscript, transcript_id, populate_existing=True)
    if row is not None:
        row.client_mail_sent_at = now
    sent_id = await meeting_client_mail.record_sent(
        db,
        meeting,
        opportunity_id=opportunity_id,
        user_id=current_user.id,
        subject=subject,
        body=body,
        internet_message_id=draft.get("internetMessageId"),
        now=now,
    )
    await db.commit()
    return await _load(db, sent_id)


@router.post("/{activity_id}/pin", response_model=ActivityOut)
async def pin_activity(
    activity_id: int,
    payload: PinRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    """Przypnij mail albo spotkanie z Outlooka do otwartej szansy tej samej firmy."""

    activity = await meeting_decisions.lock_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if not meeting_decisions.is_outlook(activity):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Przypiąć można tylko spotkanie albo mail z Outlooka.",
        )
    opportunity = await db.get(SalesOpportunity, payload.opportunity_id)
    if opportunity is None or opportunity.archived_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiej szansy."
        )
    if activity.opportunity_id == opportunity.id:
        return await _load(db, activity_id)
    if activity.opportunity_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="To jest już przypięte do innej szansy. Najpierw cofnij przypięcie.",
        )
    if opportunity.company_id != activity.company_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Szansa należy do innej firmy.",
        )
    if opportunity.status != "open":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Ta szansa jest już zamknięta."
        )
    meeting_decisions.attach(
        db,
        activity,
        opportunity,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await _load(db, activity_id)


@router.delete("/{activity_id}/pin", response_model=ActivityOut)
async def unpin_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    """Cofnij przypięcie: aktywność wraca do firmy, data szansy do stanu sprzed niego."""

    activity = await meeting_decisions.lock_activity(db, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if not meeting_decisions.is_outlook(activity):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cofnąć można tylko przypięcie spotkania albo maila z Outlooka.",
        )
    if activity.opportunity_id is None:
        return await _load(db, activity_id)
    opportunity = await db.get(SalesOpportunity, activity.opportunity_id)
    await meeting_decisions.detach(
        db,
        activity,
        opportunity,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await _load(db, activity_id)


@router.post("/tasks/complete", response_model=CompleteTasksOut)
async def complete_tasks(
    payload: CompleteTasksRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompleteTasksOut:
    """Odhacz kilka zadań naraz; zrobione wcześniej zostają bez zmian."""

    now = datetime.now(timezone.utc)
    done = (
        await db.execute(
            update(SalesActivity)
            .where(
                SalesActivity.id.in_(set(payload.ids)),
                SalesActivity.done_at.is_(None),
                task_items(),
            )
            .values(done_at=now)
            .returning(SalesActivity.opportunity_id)
        )
    ).all()
    opportunity_ids = {row[0] for row in done if row[0] is not None}
    if opportunity_ids:
        await db.execute(
            update(SalesOpportunity)
            .where(
                SalesOpportunity.id.in_(opportunity_ids),
                or_(
                    SalesOpportunity.last_activity_at.is_(None),
                    SalesOpportunity.last_activity_at < now,
                ),
            )
            .values(last_activity_at=now)
        )
    await db.commit()
    return CompleteTasksOut(updated=len(done))


@router.post("", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
async def create_activity(
    payload: ActivityCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    fields = payload.model_dump(
        exclude={"kind", "company_id", "opportunity_id", "done"}, exclude_none=True
    )
    company_id = payload.company_id
    if payload.opportunity_id is not None:
        opp = await db.get(SalesOpportunity, payload.opportunity_id)
        if opp is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiej szansy."
            )
        if company_id is not None and company_id != opp.company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Szansa należy do innej firmy.",
            )
        company_id = opp.company_id
    if company_id is not None and await db.get(SalesCompany, company_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nie ma takiej firmy w kartotece sprzedaży.",
        )
    open_item = _is_open_item(payload.kind, payload.due_at)
    if (
        payload.kind != "task"
        and not ((payload.subject or "") + (payload.body or "")).strip()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wpisz temat albo treść.",
        )
    if payload.kind == "task" and not (payload.subject or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Wpisz, co jest do zrobienia."
        )
    await _check_links(db, fields)
    now = datetime.now(timezone.utc)
    activity = SalesActivity(
        kind=payload.kind,
        company_id=company_id,
        opportunity_id=payload.opportunity_id,
        created_by_user_id=current_user.id,
    )
    for key, value in fields.items():
        setattr(activity, key, value.strip() if isinstance(value, str) else value)
    if open_item:
        # Zadanie albo telefon z terminem: jawne przypisanie wygrywa, potem
        # opiekun szansy, potem autor.
        activity.assignee_user_id = (
            activity.assignee_user_id
            or await _default_assignee(db, payload.opportunity_id, current_user.id)
        )
        if payload.done:
            activity.done_at = now
    else:
        activity.occurred_at = activity.occurred_at or now
        activity.done_at = activity.done_at or activity.occurred_at
    db.add(activity)
    await _touch_opportunity(db, activity, activity.done_at or now)
    await db.commit()
    return await _load(db, activity.id)


@router.patch("/{activity_id}", response_model=ActivityOut)
async def update_activity(
    activity_id: int,
    payload: ActivityUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    # Przypisany przekłada też zadanie z importu i zadanie założone przez kogoś innego.
    if current_user.id not in (
        activity.created_by_user_id,
        activity.assignee_user_id,
    ) and not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=EDIT_AUTHOR_ONLY_DETAIL)
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("kind", "") is None:
        fields.pop("kind")
    await _check_links(db, fields)
    for key, value in fields.items():
        if key == "is_pinned" and value is None:
            continue
        setattr(activity, key, value.strip() if isinstance(value, str) else value)
    if activity.kind == "task" and not (activity.subject or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Wpisz, co jest do zrobienia."
        )
    if (
        _is_open_item(activity.kind, activity.due_at)
        and activity.done_at is None
        and activity.assignee_user_id is None
    ):
        activity.assignee_user_id = await _default_assignee(
            db, activity.opportunity_id, current_user.id
        )
    await db.commit()
    return await _load(db, activity_id)


@router.post("/{activity_id}/done", response_model=ActivityOut)
async def complete_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if activity.done_at is None:
        activity.done_at = datetime.now(timezone.utc)
        await _touch_opportunity(db, activity, activity.done_at)
        await db.commit()
    return await _load(db, activity_id)


@router.post("/{activity_id}/reopen", response_model=ActivityOut)
async def reopen_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if _is_open_item(activity.kind, activity.due_at) and activity.done_at is not None:
        activity.done_at = None
        await db.commit()
    return await _load(db, activity_id)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if activity.created_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=AUTHOR_ONLY_DETAIL)
    await db.delete(activity)
    await db.commit()
