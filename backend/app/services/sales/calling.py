"""Kolejka dzwonienia: rekordy kampanii i szanse dzwoniącego, wynik jednym kliknięciem.

Decyzje Artura z 10.11.2026 (``docs/claude/sprzedaz/dzwonienie-kampanie-i-import-listy.md``):

* wynik telefonu nie jest szansą. „Oferta ogólna wysłana” to wpis w kolejce z datą
  oddzwonienia, a szansa powstaje dopiero z umówionego spotkania;
* kolejka jest zawsze zalogowanej osoby i ma stałą kolejność: oddzwonienia na dziś,
  spotkania bez terminu, nowe rekordy kampanii. Celu dziennego, paska postępu
  ani przełącznika osoby nie ma z założenia;
* nic nie dzwoni i nie wysyła się samo: kolejka tylko układa pracę.

Źródła pozycji:

* rekord kampanii przypisany do osoby (``sales_call_records``);
* otwarta szansa tej osoby na etapie „Lead” lejka Sprzedaż. Dopóki nie ma wyniku
  z kolejki, wraca po ``OFFER_CALLBACK_WORKDAYS`` dniach roboczych od założenia
  i stoi za oddzwonieniami z ustaloną datą, od najnowszej. Pierwszy wynik zakłada
  jej rekord bez kampanii i dalej rządzi data z rekordu;
* otwarta szansa tej osoby na etapie „Spotkanie kwalifikujące”, dla której firma nie
  ma w NEXUSIE żadnego spotkania od dnia założenia szansy: „spotkanie bez terminu”.

Każdy wynik zapisuje też telefon w ``sales_activities`` (ten sam dziennik i słownik
``CALL_OUTCOMES`` co karta szansy), więc rozmowy z kolejki da się policzyć.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import (
    DEFAULT_TZ,
    business_date,
    business_today,
    is_business_day,
    local_day_start_utc,
)
from app.models.sales import (
    SalesActivity,
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services import sales_schema as schema
from app.services.candidate_followups import add_business_days
from app.services.sales import client_gate, history
from app.services.sales.calls import DO_NOT_CONTACT, OBJECTION_DETAIL, OUTCOME_LABELS
from app.services.sales.lifecycle import apply_stage
from app.services.sales.next_step import not_system_entry
from app.services.sales.touch import not_cancelled
from app.services.sales_schema import OpportunityEventKind

NEW = schema.CALL_RECORD_NEW
#: Stany, z których rekord sam wraca do kolejki w dniu ``callback_on``.
RETURNING_STATES: tuple[str, ...] = ("no_answer", "call_back", "not_now", "offer_sent")
OPEN_STATES: tuple[str, ...] = (NEW, *RETURNING_STATES)
#: „Nie zainteresowany” wraca tylko z datą (domyślnie za pół roku); bez daty = nigdy.
NOT_INTERESTED = "not_interested"
#: „Zły numer / brak danych” zamyka rekord; nowy numer przychodzi z importu.
BAD_CONTACT = "bad_contact"
NOT_INTERESTED_DAYS = 182
MEETING_BOOKED = "meeting_booked"
#: Telefon z kolejki w dzienniku: ``external_id`` = „<id rekordu>:<numer próby>”.
#: Po nim „Skuteczność” łączy telefon z kampanią i listą (``calling_stats.py``);
#: numer próby, bo ``ux_sales_activities_outlook`` nie wpuści dwóch takich samych id.
CALL_SOURCE = "call_queue"
LEAD_STAGE_KEY = "lead"
MEETING_STAGE_KEY = "qualifying-meeting"
QUEUE_PIPELINE_KEY = schema.DEFAULT_PIPELINE_KEY
OFFER_CALLBACK_WORKDAYS = 3
NOT_NOW_DAYS = 30
SECTION_LIMIT = 300
NEW_LIMIT = 100
HISTORY_LIMIT = 6
HISTORY_SUBJECT_CHARS = 200
NOTE_CHARS = 600

RECORD_NOT_FOUND = "Nie ma takiego rekordu w kolejce."
OPPORTUNITY_NOT_FOUND = "Nie ma takiej szansy."
NOT_YOURS_DETAIL = "Ten rekord jest w kolejce innej osoby."
CLOSED_DETAIL = "Ten rekord jest już zamknięty w kolejce."
NOT_IN_QUEUE_DETAIL = "Ta szansa nie jest już w kolejce dzwonienia."
PAST_DATE_DETAIL = "Data oddzwonienia nie może być w przeszłości."
MEETING_NEEDS_OPPORTUNITY = (
    "Umówione spotkanie zapisz razem z szansą: bez niej rekord zniknąłby z kolejki."
)
OTHER_COMPANY_OPPORTUNITY = "Ta szansa należy do innej firmy niż rekord."
CLOSED_OPPORTUNITY = "Ta szansa jest już zamknięta. Załóż nową z umówionego spotkania."

QueueOutcome = Literal[schema.CALL_QUEUE_OUTCOMES]  # type: ignore[valid-type]
Section = Literal["callbacks", "meetings", "new"]


class OutcomeRequest(BaseModel):
    outcome: QueueOutcome
    #: Dzień powrotu; pusty bierze domyślny dla wyniku (brak pola nie blokuje zapisu).
    callback_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=5000)
    #: Szansa założona z umówionego spotkania (rekord kampanii).
    opportunity_id: Optional[int] = None
    #: „Nie zainteresowany” bez powrotu do kolejki.
    never: bool = False


@dataclass(frozen=True)
class QueueItem:
    key: str
    section: Section
    record_id: Optional[int]
    opportunity_id: Optional[int]
    opportunity_title: Optional[str]
    company_id: int
    company_name: str
    campaign_id: Optional[int]
    campaign_name: Optional[str]
    person_name: Optional[str]
    person_title: Optional[str]
    phone: Optional[str]
    state: str
    due_on: Optional[date]
    attempts: int
    last_outcome_at: Optional[datetime]
    since: datetime


@dataclass(frozen=True)
class DayCounts:
    """Licznik dnia bez celu: zastępuje ręczny wiersz „Podsumowanie” z Excela."""

    calls: int = 0
    talks: int = 0
    offers: int = 0
    meetings: int = 0


@dataclass(frozen=True)
class Queue:
    today: date
    callbacks: list[QueueItem]
    callbacks_total: int
    meetings: list[QueueItem]
    new: list[QueueItem]
    new_total: int
    later: int
    campaigns: list[tuple[int, str]]
    today_counts: DayCounts = DayCounts()
    yesterday: Optional[date] = None
    yesterday_counts: DayCounts = DayCounts()


@dataclass(frozen=True)
class HistoryEntry:
    kind: str
    direction: Optional[str]
    outcome: Optional[str]
    subject: Optional[str]
    at: datetime


@dataclass(frozen=True)
class Card:
    company_id: int
    company_name: str
    domain: Optional[str]
    contact_id: Optional[int]
    email: Optional[str]
    contact_source: Optional[str]
    note: Optional[str]
    service: Optional[str]
    script: Optional[str]
    linkedin_url: Optional[str]
    do_not_contact: bool
    client_refusal: Optional[str]
    can_save: bool
    history: list[HistoryEntry]


@dataclass(frozen=True)
class OutcomeResult:
    record_id: int
    state: str
    callback_on: Optional[date]
    opportunity_id: Optional[int]


# ── Daty ──────────────────────────────────────────────────────────────────


def _noon(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=ZoneInfo(DEFAULT_TZ))


def workdays_after(day: date, workdays: int) -> date:
    return add_business_days(_noon(day), workdays)


def on_business_day(day: date) -> date:
    """Ten sam dzień, a z weekendu albo święta najbliższy roboczy."""

    return workdays_after(day - timedelta(days=1), 1)


def default_callback(outcome: str, today: date) -> Optional[date]:
    if outcome == "offer_sent":
        return workdays_after(today, OFFER_CALLBACK_WORKDAYS)
    if outcome in ("no_answer", "call_back"):
        return workdays_after(today, 1)
    if outcome == "not_now":
        return on_business_day(today + timedelta(days=NOT_NOW_DAYS))
    if outcome == NOT_INTERESTED:
        return on_business_day(today + timedelta(days=NOT_INTERESTED_DAYS))
    return None


def resolve_callback(
    outcome: str, requested: Optional[date], today: date, *, never: bool = False
) -> Optional[date]:
    if outcome == NOT_INTERESTED and never:
        return None
    if outcome not in (*RETURNING_STATES, NOT_INTERESTED):
        return None
    if requested is None:
        return default_callback(outcome, today)
    if requested < today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=PAST_DATE_DETAIL
        )
    return requested


def lead_due_on(created_at: datetime) -> date:
    """Kiedy szansa z etapu „Lead” bez wyniku z kolejki wraca do dzwonienia."""

    return add_business_days(created_at, OFFER_CALLBACK_WORKDAYS)


# ── Kolejka ───────────────────────────────────────────────────────────────


def _contact_phone(contact: Optional[SalesContact]) -> Optional[str]:
    if contact is None:
        return None
    return contact.mobile_phone or contact.phone


def _stage_join(query: Any) -> Any:
    return query.join(
        SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
    ).join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)


def _without_objection() -> list[Any]:
    """Osoba albo firma ze sprzeciwem nie wchodzi do kolejki, skądkolwiek sprzeciw przyszedł.

    Zapytanie musi mieć ``SalesCompany`` i dołączony zewnętrznie ``SalesContact``.
    """

    return [
        SalesCompany.status != schema.CompanyStatus.do_not_contact.value,
        or_(SalesContact.id.is_(None), SalesContact.do_not_contact_at.is_(None)),
    ]


def _open_own_opportunity(user_id: int, stage_key: str) -> list[Any]:
    return [
        SalesOpportunity.owner_user_id == user_id,
        SalesOpportunity.status == "open",
        SalesOpportunity.archived_at.is_(None),
        SalesPipeline.key == QUEUE_PIPELINE_KEY,
        SalesPipelineStage.key == stage_key,
        SalesCompany.archived_at.is_(None),
        *_without_objection(),
    ]


def _opportunity_record(alias: Any = SalesCallRecord) -> Any:
    """Rekord bez kampanii należący do szansy (jeden na szansę)."""

    return and_(
        alias.opportunity_id == SalesOpportunity.id, alias.campaign_id.is_(None)
    )


def _not_interested_returning() -> Any:
    """„Nie zainteresowany” z datą powrotu wraca do kolejki w swoim dniu."""

    return and_(
        SalesCallRecord.state == NOT_INTERESTED,
        SalesCallRecord.callback_on.is_not(None),
    )


def _own_campaign_records(query: Any, user_id: int) -> Any:
    """Otwarte rekordy kampanii tej osoby: wspólne złączenia listy i liczników."""

    return (
        query.select_from(SalesCallRecord)
        .join(SalesCompany, SalesCompany.id == SalesCallRecord.company_id)
        .join(SalesCallCampaign, SalesCallCampaign.id == SalesCallRecord.campaign_id)
        .outerjoin(SalesContact, SalesContact.id == SalesCallRecord.contact_id)
        .where(
            SalesCallRecord.assigned_user_id == user_id,
            or_(SalesCallRecord.state.in_(OPEN_STATES), _not_interested_returning()),
            SalesCallCampaign.archived_at.is_(None),
            SalesCompany.archived_at.is_(None),
            *_without_objection(),
        )
    )


@dataclass(frozen=True)
class _CampaignRecords:
    due: list[Any]
    new: list[Any]
    due_total: int
    new_total: int
    later: int
    campaigns: list[tuple[int, str]]


async def _campaign_records(
    db: AsyncSession, user_id: int, campaign_id: Optional[int], today: date
) -> _CampaignRecords:
    """Rekordy kampanii do listy i ich liczniki.

    Lista jest przycięta w bazie: jedna kampania to bywa 2000 rekordów, a kolejka
    odświeża się po każdym zapisie w Sprzedaży.
    """

    # „Nie zainteresowany” liczy się tylko w dniu powrotu: w „wróci w swoim dniu”
    # zasłoniłby pół roku setkami osób.
    waiting = SalesCallRecord.state.in_(RETURNING_STATES)
    returning = or_(waiting, _not_interested_returning())
    due = or_(
        SalesCallRecord.callback_on.is_(None), SalesCallRecord.callback_on <= today
    )
    counted = (
        await db.execute(
            _own_campaign_records(
                select(
                    SalesCallRecord.campaign_id,
                    SalesCallCampaign.name,
                    func.count().filter(SalesCallRecord.state == NEW),
                    func.count().filter(returning, due),
                    func.count().filter(waiting, ~due),
                ),
                user_id,
            ).group_by(SalesCallRecord.campaign_id, SalesCallCampaign.name)
        )
    ).all()
    shown = [row for row in counted if campaign_id in (None, row[0])]
    listed = _own_campaign_records(
        select(SalesCallRecord, SalesCompany.name, SalesCallCampaign.name), user_id
    )
    if campaign_id is not None:
        listed = listed.where(SalesCallRecord.campaign_id == campaign_id)
    due_rows = await db.execute(
        listed.where(returning, due)
        .order_by(SalesCallRecord.callback_on.asc().nulls_first(), SalesCallRecord.id)
        .limit(SECTION_LIMIT)
    )
    new_rows = await db.execute(
        listed.where(SalesCallRecord.state == NEW)
        .order_by(SalesCallRecord.campaign_id, SalesCallRecord.id)
        .limit(NEW_LIMIT)
    )
    return _CampaignRecords(
        due=list(due_rows.all()),
        new=list(new_rows.all()),
        new_total=sum(int(row[2]) for row in shown),
        due_total=sum(int(row[3]) for row in shown),
        later=sum(int(row[4]) for row in shown),
        # Filtr kampanii pokazuje wszystkie kampanie osoby, także przy wybranej jednej.
        campaigns=sorted(
            ((row[0], row[1]) for row in counted), key=lambda pair: pair[1].lower()
        ),
    )


async def _lead_opportunities(db: AsyncSession, user_id: int) -> list[Any]:
    """Szanse z etapu „Lead” z rekordem kolejki albo jeszcze bez niego."""

    query = _stage_join(
        select(SalesOpportunity, SalesCompany.name, SalesCallRecord, SalesContact)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .outerjoin(SalesCallRecord, _opportunity_record())
        .outerjoin(SalesContact, SalesContact.id == SalesOpportunity.primary_contact_id)
    ).where(*_open_own_opportunity(user_id, LEAD_STAGE_KEY))
    return list((await db.execute(query.order_by(SalesOpportunity.created_at))).all())


async def _meetings_without_date(
    db: AsyncSession, user_id: int, today: date
) -> list[Any]:
    meeting = (
        select(SalesActivity.id)
        .where(
            SalesActivity.kind == "meeting",
            *not_cancelled(),
            or_(
                SalesActivity.opportunity_id == SalesOpportunity.id,
                SalesActivity.company_id == SalesOpportunity.company_id,
            ),
            func.coalesce(SalesActivity.occurred_at, SalesActivity.due_at)
            >= func.date_trunc("day", SalesOpportunity.created_at),
        )
        .correlate(SalesOpportunity)
    )
    query = _stage_join(
        select(SalesOpportunity, SalesCompany.name, SalesCallRecord, SalesContact)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .outerjoin(SalesCallRecord, _opportunity_record())
        .outerjoin(SalesContact, SalesContact.id == SalesOpportunity.primary_contact_id)
    ).where(
        *_open_own_opportunity(user_id, MEETING_STAGE_KEY),
        ~exists(meeting),
        # „Oddzwonić w czwartek” chowa pozycję do czwartku, sprzeciw na stałe.
        or_(
            SalesCallRecord.id.is_(None),
            and_(
                SalesCallRecord.state != DO_NOT_CONTACT,
                or_(
                    SalesCallRecord.callback_on.is_(None),
                    SalesCallRecord.callback_on <= today,
                ),
            ),
        ),
    )
    return list(
        (
            await db.execute(
                query.order_by(SalesOpportunity.created_at).limit(SECTION_LIMIT)
            )
        ).all()
    )


def _record_item(
    record: SalesCallRecord,
    company_name: str,
    campaign_name: Optional[str],
    section: Section,
) -> QueueItem:
    return QueueItem(
        key=f"r:{record.id}",
        section=section,
        record_id=record.id,
        opportunity_id=record.opportunity_id,
        opportunity_title=None,
        company_id=record.company_id,
        company_name=company_name,
        campaign_id=record.campaign_id,
        campaign_name=campaign_name,
        person_name=record.person_name,
        person_title=record.person_title,
        phone=record.phone,
        state=record.state,
        due_on=record.callback_on,
        attempts=record.attempts,
        last_outcome_at=record.last_outcome_at,
        since=record.created_at,
    )


def _opportunity_item(
    opp: SalesOpportunity,
    company_name: str,
    record: Optional[SalesCallRecord],
    contact: Optional[SalesContact],
    section: Section,
    due_on: Optional[date],
) -> QueueItem:
    return QueueItem(
        key=f"o:{opp.id}",
        section=section,
        record_id=record.id if record else None,
        opportunity_id=opp.id,
        opportunity_title=opp.title,
        company_id=opp.company_id,
        company_name=company_name,
        campaign_id=None,
        campaign_name=None,
        person_name=contact.full_name if contact else None,
        person_title=contact.title if contact else None,
        phone=_contact_phone(contact),
        state=record.state if record else NEW,
        due_on=due_on,
        attempts=record.attempts if record else 0,
        last_outcome_at=record.last_outcome_at if record else None,
        since=opp.created_at,
    )


async def load_queue(
    db: AsyncSession, user_id: int, *, campaign_id: Optional[int] = None
) -> Queue:
    """Kolejka zalogowanej osoby; z ``campaign_id`` same rekordy tej kampanii."""

    today = business_today()
    records = await _campaign_records(db, user_id, campaign_id, today)
    callbacks = [
        _record_item(record, company_name, campaign_name, "callbacks")
        for record, company_name, campaign_name in records.due
    ]
    new = [
        _record_item(record, company_name, campaign_name, "new")
        for record, company_name, campaign_name in records.new
    ]
    callbacks_total = records.due_total
    later = records.later

    meetings: list[QueueItem] = []
    untouched: list[QueueItem] = []
    if campaign_id is None:
        for opp, company_name, record, contact in await _lead_opportunities(
            db, user_id
        ):
            if record is not None and (
                record.state in (DO_NOT_CONTACT, BAD_CONTACT)
                or (record.state == NOT_INTERESTED and record.callback_on is None)
            ):
                continue
            if record is None or record.state == NEW:
                due_on = lead_due_on(opp.created_at)
            else:
                # Także po „Umówionym spotkaniu”, gdy szansa wróciła na etap „Lead”:
                # rekord bez daty jest do zrobienia od razu.
                due_on = record.callback_on
            if due_on is not None and due_on > today:
                if record is None or record.state != NOT_INTERESTED:
                    later += 1
                continue
            item = _opportunity_item(
                opp, company_name, record, contact, "callbacks", due_on
            )
            (untouched if item.state == NEW else callbacks).append(item)
            callbacks_total += 1
        meetings = [
            _opportunity_item(opp, company_name, record, contact, "meetings", None)
            for opp, company_name, record, contact in await _meetings_without_date(
                db, user_id, today
            )
        ]

    # Najpierw oddzwonienia z ustaloną datą, od najstarszego terminu. Szanse z etapu
    # „Lead” bez żadnej rozmowy z kolejki idą po nich od najnowszej: świeża oferta
    # ogólna jest więcej warta niż wpis z importu sprzed miesięcy.
    callbacks.sort(key=lambda item: (item.due_on or date.min, item.since))
    untouched.sort(key=lambda item: item.since, reverse=True)
    callbacks += untouched
    return Queue(
        today=today,
        callbacks=callbacks[:SECTION_LIMIT],
        callbacks_total=callbacks_total,
        meetings=meetings,
        new=new,
        new_total=records.new_total,
        later=later,
        campaigns=records.campaigns,
        today_counts=await day_counts(db, user_id, today),
        yesterday=previous_business_day(today),
        yesterday_counts=await day_counts(db, user_id, previous_business_day(today)),
    )


def previous_business_day(day: date) -> date:
    current = day - timedelta(days=1)
    while not is_business_day(_noon(current)):
        current -= timedelta(days=1)
    return current


async def day_counts(db: AsyncSession, user_id: int, day: date) -> DayCounts:
    """Telefony osoby w danym dniu firmy: te same reguły co „Skuteczność”.

    Rozmowa to wynik inny niż „Nie odebrał” i „Zły numer”; umówione spotkanie liczy się raz na
    szansę, bo rekord szansy zostaje w kolejce i wynik może paść dwa razy.
    """

    booked = SalesActivity.outcome == MEETING_BOOKED
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(
                    SalesActivity.outcome.not_in(("no_answer", BAD_CONTACT))
                ),
                func.count().filter(SalesActivity.outcome == "offer_sent"),
                func.count(func.distinct(SalesActivity.opportunity_id)).filter(booked),
                func.count().filter(booked, SalesActivity.opportunity_id.is_(None)),
            ).where(
                SalesActivity.kind == "call",
                SalesActivity.outcome.is_not(None),
                SalesActivity.created_by_user_id == user_id,
                SalesActivity.occurred_at >= local_day_start_utc(day),
                SalesActivity.occurred_at
                < local_day_start_utc(day + timedelta(days=1)),
            )
        )
    ).one()
    return DayCounts(
        calls=int(row[0]),
        talks=int(row[1]),
        offers=int(row[2]),
        meetings=int(row[3]) + int(row[4]),
    )


# ── Tabela: wszystkie rekordy osoby ───────────────────────────────────────

TABLE_LIMIT = 200
#: Stany, które pokazuje filtr tabeli (sprzeciw nie wchodzi: numer nie może wyjść z API).
TABLE_STATES: tuple[str, ...] = tuple(
    state for state in schema.CALL_RECORD_STATES if state != DO_NOT_CONTACT
)


@dataclass(frozen=True)
class RecordTable:
    items: list[QueueItem]
    total: int
    counts: dict[str, int]


def _own_records(query: Any, user_id: int) -> Any:
    """Rekordy osoby (kampanii i szans) bez sprzeciwu: wspólne złączenia tabeli."""

    return (
        query.select_from(SalesCallRecord)
        .join(SalesCompany, SalesCompany.id == SalesCallRecord.company_id)
        .outerjoin(
            SalesCallCampaign, SalesCallCampaign.id == SalesCallRecord.campaign_id
        )
        .outerjoin(SalesContact, SalesContact.id == SalesCallRecord.contact_id)
        .where(
            SalesCallRecord.assigned_user_id == user_id,
            SalesCallRecord.state.in_(TABLE_STATES),
            SalesCompany.archived_at.is_(None),
            SalesCallCampaign.archived_at.is_(None),
            *_without_objection(),
        )
    )


async def list_records(
    db: AsyncSession,
    user_id: int,
    *,
    state: Optional[str] = None,
    campaign_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = TABLE_LIMIT,
    offset: int = 0,
) -> RecordTable:
    """Widok „Tabela”: ta sama lista co kolejka, ale cała i z filtrem po wyniku.

    Liczniki filtrów nie zależą od wybranego stanu, żeby chipy pokazywały całość.
    """

    def narrowed(query: Any) -> Any:
        if campaign_id is not None:
            query = query.where(SalesCallRecord.campaign_id == campaign_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    SalesCompany.name.ilike(pattern),
                    SalesCallRecord.person_name.ilike(pattern),
                    SalesCallRecord.phone.ilike(pattern),
                )
            )
        return query

    counted = (
        await db.execute(
            narrowed(
                _own_records(
                    select(SalesCallRecord.state, func.count()), user_id
                ).group_by(SalesCallRecord.state)
            )
        )
    ).all()
    counts = {row[0]: int(row[1]) for row in counted}
    listed = narrowed(
        _own_records(
            select(SalesCallRecord, SalesCompany.name, SalesCallCampaign.name), user_id
        )
    )
    if state is not None:
        listed = listed.where(SalesCallRecord.state == state)
    rows = (
        await db.execute(
            listed.order_by(
                SalesCallRecord.callback_on.asc().nulls_last(),
                func.lower(SalesCompany.name),
                SalesCallRecord.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return RecordTable(
        items=[
            _record_item(record, company_name, campaign_name, "callbacks")
            for record, company_name, campaign_name in rows
        ],
        total=counts.get(state, 0) if state is not None else sum(counts.values()),
        counts=counts,
    )


# ── Karta rekordu ─────────────────────────────────────────────────────────


async def _history(db: AsyncSession, company_id: int) -> list[HistoryEntry]:
    happened = func.coalesce(
        SalesActivity.occurred_at, SalesActivity.done_at, SalesActivity.created_at
    )
    rows = (
        await db.execute(
            select(
                SalesActivity.kind,
                SalesActivity.direction,
                SalesActivity.outcome,
                func.left(
                    func.coalesce(SalesActivity.subject, SalesActivity.body),
                    HISTORY_SUBJECT_CHARS,
                ),
                happened,
            )
            .where(
                SalesActivity.company_id == company_id,
                # Otwarte zadanie i zaplanowany telefon to zamiar, nie historia.
                or_(
                    SalesActivity.kind.in_(("email", "note", "meeting")),
                    SalesActivity.done_at.is_not(None),
                ),
                happened <= func.now(),
                not_system_entry(),
            )
            .order_by(happened.desc(), SalesActivity.id.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    return [HistoryEntry(*row) for row in rows]


async def _client_refusal(db: AsyncSession, company: SalesCompany) -> Optional[str]:
    if company.normalized_name == client_gate.OWN_COMPANY_KEY:
        return client_gate.OWN_COMPANY_REFUSAL
    matches = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=company.id,
                client_id=company.client_id,
                normalized_name=company.normalized_name,
            )
        ],
    )
    match = matches.get(company.id)
    return match.refusal if match else None


def _objected(company: SalesCompany, contact: Optional[SalesContact]) -> bool:
    return company.status == schema.CompanyStatus.do_not_contact.value or (
        contact is not None and contact.do_not_contact_at is not None
    )


async def _card(
    db: AsyncSession,
    *,
    company: SalesCompany,
    contact: Optional[SalesContact],
    record: Optional[SalesCallRecord],
    campaign: Optional[SalesCallCampaign],
    can_save: bool,
    opportunity_note: Optional[str] = None,
) -> Card:
    return Card(
        company_id=company.id,
        company_name=company.name,
        domain=company.domain,
        contact_id=contact.id if contact else None,
        email=(record.email if record else None)
        or (contact.email if contact else None),
        contact_source=record.contact_source if record else None,
        note=(record.note if record else None) or opportunity_note,
        service=campaign.service if campaign else None,
        script=campaign.script if campaign else None,
        linkedin_url=contact.linkedin_url if contact else None,
        do_not_contact=_objected(company, contact)
        or (record is not None and record.state == DO_NOT_CONTACT),
        client_refusal=await _client_refusal(db, company),
        can_save=can_save,
        history=await _history(db, company.id),
    )


async def record_card(
    db: AsyncSession, record_id: int, *, user_id: int, admin: bool
) -> Card:
    record = await db.get(SalesCallRecord, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)
    company = await db.get(SalesCompany, record.company_id)
    contact = (
        await db.get(SalesContact, record.contact_id) if record.contact_id else None
    )
    campaign = (
        await db.get(SalesCallCampaign, record.campaign_id)
        if record.campaign_id
        else None
    )
    opp = (
        await db.get(SalesOpportunity, record.opportunity_id)
        if record.campaign_id is None and record.opportunity_id
        else None
    )
    return await _card(
        db,
        company=company,
        contact=contact,
        record=record,
        campaign=campaign,
        can_save=admin or _owner_id(record, opp) == user_id,
    )


async def opportunity_card(
    db: AsyncSession, opportunity_id: int, *, user_id: int, admin: bool
) -> Card:
    opp = await db.get(SalesOpportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=OPPORTUNITY_NOT_FOUND)
    company = await db.get(SalesCompany, opp.company_id)
    contact = (
        await db.get(SalesContact, opp.primary_contact_id)
        if opp.primary_contact_id
        else None
    )
    record = await db.scalar(
        select(SalesCallRecord).where(
            SalesCallRecord.opportunity_id == opp.id,
            SalesCallRecord.campaign_id.is_(None),
        )
    )
    # Szansa z umówionego spotkania pamięta kampanię przez rekord, który ją założył.
    campaign = await db.scalar(
        select(SalesCallCampaign)
        .join(SalesCallRecord, SalesCallRecord.campaign_id == SalesCallCampaign.id)
        .where(SalesCallRecord.opportunity_id == opp.id)
        .order_by(SalesCallRecord.id)
        .limit(1)
    )
    return await _card(
        db,
        company=company,
        contact=contact,
        record=record,
        campaign=campaign,
        can_save=admin or opp.owner_user_id == user_id,
        # Przy szansach założonych po telefonie osoba i numer bywają tylko w opisie.
        opportunity_note=(opp.description or "").strip()[:NOTE_CHARS] or None,
    )


# ── Wynik rozmowy ─────────────────────────────────────────────────────────


def _owner_id(
    record: SalesCallRecord, opp: Optional[SalesOpportunity]
) -> Optional[int]:
    """Czyja to pozycja: rekord kampanii osoby przypisanej, rekord szansy jej opiekuna."""

    if record.campaign_id is None and opp is not None:
        return opp.owner_user_id
    return record.assigned_user_id


async def _queue_stage_key(db: AsyncSession, opp: SalesOpportunity) -> Optional[str]:
    return await db.scalar(
        select(SalesPipelineStage.key)
        .join(SalesPipeline, SalesPipeline.id == SalesPipelineStage.pipeline_id)
        .where(
            SalesPipelineStage.id == opp.stage_id,
            SalesPipeline.key == QUEUE_PIPELINE_KEY,
            SalesPipelineStage.key.in_((LEAD_STAGE_KEY, MEETING_STAGE_KEY)),
        )
    )


async def _move_to_meeting_stage(
    db: AsyncSession, opp: SalesOpportunity, *, user_id: int, now: datetime
) -> None:
    stages = list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == opp.pipeline_id)
                .order_by(SalesPipelineStage.position, SalesPipelineStage.id)
            )
        ).scalars()
    )
    target = next((s for s in stages if s.key == MEETING_STAGE_KEY), None)
    if target is None or target.id == opp.stage_id:
        return
    before = history.snapshot(opp)
    apply_stage(opp, target, stages, now=now)
    history.record_changes(db, opp, before, user_id=user_id)


async def _link_meeting_opportunity(
    db: AsyncSession, record: SalesCallRecord, opportunity_id: Optional[int]
) -> SalesOpportunity:
    if opportunity_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=MEETING_NEEDS_OPPORTUNITY
        )
    opp = await db.get(SalesOpportunity, opportunity_id)
    if opp is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OPPORTUNITY_NOT_FOUND
        )
    if opp.company_id != record.company_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OTHER_COMPANY_OPPORTUNITY
        )
    if opp.status != "open" or opp.archived_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CLOSED_OPPORTUNITY
        )
    return opp


async def apply_outcome(
    db: AsyncSession,
    record: SalesCallRecord,
    payload: OutcomeRequest,
    *,
    user_id: int,
    admin: bool,
    now: datetime,
) -> OutcomeResult:
    """Zapisuje wynik na rekordzie i telefon w dzienniku; bez commita."""

    outcome = payload.outcome
    own_opportunity = (
        await db.get(SalesOpportunity, record.opportunity_id)
        if record.campaign_id is None and record.opportunity_id
        else None
    )
    if not admin and _owner_id(record, own_opportunity) != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=NOT_YOURS_DETAIL)
    # Rekord kampanii kończy się spotkaniem; rekord szansy żyje dalej, bo po
    # „Umówionym spotkaniu” dzwoniący ustala jeszcze termin.
    if record.state == DO_NOT_CONTACT or (
        record.state == MEETING_BOOKED and record.campaign_id is not None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=CLOSED_DETAIL)
    company = await db.get(SalesCompany, record.company_id)
    contact = (
        await db.get(SalesContact, record.contact_id) if record.contact_id else None
    )
    objecting = outcome == DO_NOT_CONTACT
    if _objected(company, contact) and not objecting:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OBJECTION_DETAIL)
    callback_on = resolve_callback(
        outcome, payload.callback_on, business_date(now), never=payload.never
    )

    opportunity = own_opportunity
    if outcome == MEETING_BOOKED:
        refusal = await _client_refusal(db, company)
        if refusal is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=refusal)
        if own_opportunity is not None:
            await _move_to_meeting_stage(db, own_opportunity, user_id=user_id, now=now)
        else:
            opportunity = await _link_meeting_opportunity(
                db, record, payload.opportunity_id
            )
            record.opportunity_id = opportunity.id

    record.state = outcome
    record.callback_on = callback_on
    record.attempts += 1
    record.last_outcome_at = now

    label = OUTCOME_LABELS[outcome]
    person = record.person_name or (contact.full_name if contact else None)
    db.add(
        SalesActivity(
            kind="call",
            outcome=outcome,
            subject=f"{label}: {person}" if person else label,
            body=(payload.note or "").strip() or None,
            direction="out",
            company_id=record.company_id,
            opportunity_id=opportunity.id if opportunity is not None else None,
            contact_id=contact.id if contact is not None else None,
            created_by_user_id=user_id,
            occurred_at=now,
            done_at=now,
            external_source=CALL_SOURCE,
            external_id=f"{record.id}:{record.attempts}",
        )
    )
    if opportunity is not None and (
        opportunity.last_activity_at is None or opportunity.last_activity_at < now
    ):
        opportunity.last_activity_at = now
    if objecting and contact is not None and contact.do_not_contact_at is None:
        contact.do_not_contact_at = now
        contact.do_not_contact_by_user_id = user_id
    if objecting and opportunity is not None:
        history.record(
            db,
            opportunity_id=opportunity.id,
            user_id=user_id,
            kind=OpportunityEventKind.updated,
            field="do_not_contact",
            new_value=person,
        )
    await db.flush()
    return OutcomeResult(
        record_id=record.id,
        state=record.state,
        callback_on=record.callback_on,
        opportunity_id=record.opportunity_id,
    )


async def locked_record(db: AsyncSession, record_id: int) -> SalesCallRecord:
    record = await db.scalar(
        select(SalesCallRecord).where(SalesCallRecord.id == record_id).with_for_update()
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)
    return record


async def record_for_opportunity(
    db: AsyncSession, opportunity_id: int, *, user_id: int
) -> SalesCallRecord:
    """Rekord kolejki istniejącej szansy; pierwszy wynik go zakłada.

    Blokada wiersza szansy szereguje dwa równoległe kliknięcia, więc drugi rekord
    tej samej szansy nie powstaje (pilnuje też ``ux_sales_call_records_opportunity``).
    """

    opp = await db.scalar(
        select(SalesOpportunity)
        .where(SalesOpportunity.id == opportunity_id)
        .with_for_update()
    )
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=OPPORTUNITY_NOT_FOUND)
    if (
        opp.status != "open"
        or opp.archived_at is not None
        or await _queue_stage_key(db, opp) is None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_IN_QUEUE_DETAIL)
    record = await db.scalar(
        select(SalesCallRecord)
        .where(
            SalesCallRecord.opportunity_id == opp.id,
            SalesCallRecord.campaign_id.is_(None),
        )
        .with_for_update()
    )
    contact = (
        await db.get(SalesContact, opp.primary_contact_id)
        if opp.primary_contact_id
        else None
    )
    if record is None:
        record = SalesCallRecord(
            campaign_id=None,
            opportunity_id=opp.id,
            state=NEW,
            attempts=0,
            created_by_user_id=user_id,
        )
        db.add(record)
    # Kolejka i karta pokazują bieżący kontakt szansy, więc wynik (także sprzeciw)
    # ma trafić do tej samej osoby, a nie do tej z pierwszej rozmowy.
    record.company_id = opp.company_id
    record.contact_id = contact.id if contact else None
    record.person_name = contact.full_name if contact else None
    record.person_title = contact.title if contact else None
    record.phone = _contact_phone(contact)
    record.email = contact.email if contact else None
    record.assigned_user_id = opp.owner_user_id or user_id
    await db.flush()
    return record


# ── Kampanie ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CampaignRow:
    campaign: SalesCallCampaign
    counts: dict[str, int]


async def list_campaigns(db: AsyncSession) -> list[CampaignRow]:
    campaigns = list(
        (
            await db.execute(
                select(SalesCallCampaign)
                .where(SalesCallCampaign.archived_at.is_(None))
                .order_by(func.lower(SalesCallCampaign.name), SalesCallCampaign.id)
            )
        ).scalars()
    )
    counted = (
        await db.execute(
            select(
                SalesCallRecord.campaign_id,
                SalesCallRecord.state,
                func.count(SalesCallRecord.id),
            )
            .where(SalesCallRecord.campaign_id.is_not(None))
            .group_by(SalesCallRecord.campaign_id, SalesCallRecord.state)
        )
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for campaign_id, state, number in counted:
        counts.setdefault(campaign_id, {})[state] = int(number)
    return [
        CampaignRow(campaign=campaign, counts=counts.get(campaign.id, {}))
        for campaign in campaigns
    ]
