"""Sprzedaż → Dzwonienie: kolejka, wynik rozmowy, kampanie i import listy.

Prefiks ``/api/sales/calling`` (wpięty w ``app/main.py``). Odczyt: „Sprzedaż: podgląd”,
zapis: „Sprzedaż: edycja”. Kolejka jest zawsze zalogowanej osoby: przełącznika osoby,
celu dziennego i paska postępu nie ma z założenia (decyzje Artura 10.11.2026,
``docs/claude/sprzedaz/dzwonienie-kampanie-i-import-listy.md``).

Bez ``from __future__ import annotations``: trasy importu mają ``@limiter.limit``,
a moduł z limiterem i PEP 563 zamienia parametry ``Annotated`` w parametry query.
"""

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.models.sales import SalesCallCampaign
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales import calling, calling_excel, calling_import, calling_stats
from app.services.sales.calling_file import (
    MAX_FILE_BYTES,
    TOO_BIG_DETAIL,
    ListFile,
    ListFileError,
    parse_list_file,
)

router = APIRouter()

CAMPAIGN_NOT_FOUND = "Nie ma takiej kampanii."
SOURCE_REQUIRED = "Wpisz, skąd masz kontakty z tej listy."
STATE_DETAIL = "Nieznany wynik w filtrze tabeli."
ASSIGNEE_DETAIL = "Dzwonić może aktywna osoba z uprawnieniem „Sprzedaż: edycja”."
MIN_SOURCE_CHARS = 3
MAX_SOURCE_CHARS = 255


class Ref(BaseModel):
    id: int
    name: str


class QueueItemOut(BaseModel):
    key: str
    section: str
    record_id: Optional[int]
    opportunity_id: Optional[int]
    opportunity_title: Optional[str]
    company: Ref
    campaign: Optional[Ref]
    person_name: Optional[str]
    person_title: Optional[str]
    phone: Optional[str]
    state: str
    due_on: Optional[date]
    attempts: int
    last_outcome_at: Optional[datetime]
    since: datetime
    #: Kto dzwoni; wypełnione w Tabeli (przy „Wszyscy” widać cudze rekordy).
    assignee: Optional[Ref] = None
    #: Ostatnia zmiana rekordu (kolumna „Ostatnia modyfikacja” w Tabeli).
    modified_at: Optional[datetime] = None


class QueueCounts(BaseModel):
    callbacks: int
    #: „Nie odebrane”: osobna zakładka bez względu na datę (13.11.2026).
    no_answer: int
    meetings: int
    new: int
    #: Rekordy z datą powrotu w przyszłości: wrócą same w swoim dniu.
    later: int


class DayCountsOut(BaseModel):
    calls: int
    talks: int
    offers: int
    meetings: int


class QueueOut(BaseModel):
    today: date
    counts: QueueCounts
    callbacks: list[QueueItemOut]
    no_answer: list[QueueItemOut]
    meetings: list[QueueItemOut]
    new: list[QueueItemOut]
    campaigns: list[Ref]
    #: Licznik dnia bez celu (decyzja Artura 11.11.2026): zastępuje ręczne
    #: „Podsumowanie” z Excela; wczoraj = poprzedni dzień roboczy.
    today_counts: DayCountsOut
    yesterday: date
    yesterday_counts: DayCountsOut
    #: Osoby z otwartymi rekordami kampanii: wybór osoby nad kolejką (13.11.2026).
    callers: list[Ref] = []


class RecordTableOut(BaseModel):
    items: list[QueueItemOut]
    total: int
    counts: dict[str, int]
    #: Osoby z rekordami w wybranym zakresie, do filtra „Kto dzwoni”.
    callers: list[Ref] = []


class CompanyCallRecordOut(BaseModel):
    """Linia „Na liście dzwonienia” na karcie firmy: bez numeru telefonu."""

    record_id: int
    campaign: Optional[Ref]
    assignee: Optional[Ref]
    person_name: Optional[str]
    state: str
    callback_on: Optional[date]
    last_outcome_at: Optional[datetime]


class HistoryOut(BaseModel):
    kind: str
    direction: Optional[str]
    outcome: Optional[str]
    subject: Optional[str]
    at: datetime


class CardOut(BaseModel):
    company: Ref
    domain: Optional[str]
    contact_id: Optional[int]
    email: Optional[str]
    contact_source: Optional[str]
    note: Optional[str]
    service: Optional[str]
    script: Optional[str]
    linkedin_url: Optional[str]
    do_not_contact: bool
    #: Firma jest klientem NEXUSA: komu przekazać temat zamiast umawiać spotkanie.
    client_refusal: Optional[str]
    can_save: bool
    history: list[HistoryOut]


class OutcomeOut(BaseModel):
    record_id: int
    state: str
    callback_on: Optional[date]
    opportunity_id: Optional[int]


class CampaignFields(BaseModel):
    service: Optional[str] = Field(default=None, max_length=120)
    script: Optional[str] = Field(default=None, max_length=20_000)


class CampaignCreate(CampaignFields):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj nazwę kampanii.")
        return value


class CampaignUpdate(CampaignFields):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Podaj nazwę kampanii.")
        return value.strip() if value is not None else None


class CampaignOut(BaseModel):
    id: int
    name: str
    service: Optional[str]
    script: Optional[str]
    total: int
    counts: dict[str, int]


class ImportRowOut(BaseModel):
    line: int
    company: str
    person: Optional[str]
    title: Optional[str]
    phone: Optional[str]
    fate: str
    detail: str
    to_decide: bool
    #: Komu trafi rekord (kolumna podziału albo osoba z okna).
    assignee: Optional[Ref] = None


class ImportPreviewOut(BaseModel):
    total: int
    addable: int
    to_decide: int
    without_company: int
    counts: dict[str, int]
    rows: list[ImportRowOut]


class ImportResultOut(BaseModel):
    added: int
    total: int
    without_company: int
    counts: dict[str, int]


def _item(item: calling.QueueItem) -> QueueItemOut:
    return QueueItemOut(
        key=item.key,
        section=item.section,
        record_id=item.record_id,
        opportunity_id=item.opportunity_id,
        opportunity_title=item.opportunity_title,
        company=Ref(id=item.company_id, name=item.company_name),
        campaign=(
            Ref(id=item.campaign_id, name=item.campaign_name or "")
            if item.campaign_id is not None
            else None
        ),
        person_name=item.person_name,
        person_title=item.person_title,
        phone=item.phone,
        state=item.state,
        due_on=item.due_on,
        attempts=item.attempts,
        last_outcome_at=item.last_outcome_at,
        since=item.since,
        assignee=(
            Ref(id=item.assignee_id, name=item.assignee_name or "")
            if item.assignee_id is not None and item.assignee_name is not None
            else None
        ),
        modified_at=item.modified_at,
    )


def _card(card: calling.Card) -> CardOut:
    return CardOut(
        company=Ref(id=card.company_id, name=card.company_name),
        domain=card.domain,
        contact_id=card.contact_id,
        email=card.email,
        contact_source=card.contact_source,
        note=card.note,
        service=card.service,
        script=card.script,
        linkedin_url=card.linkedin_url,
        do_not_contact=card.do_not_contact,
        client_refusal=card.client_refusal,
        can_save=card.can_save,
        history=[
            HistoryOut(
                kind=entry.kind,
                direction=entry.direction,
                outcome=entry.outcome,
                subject=entry.subject,
                at=entry.at,
            )
            for entry in card.history
        ],
    )


def _outcome(result: calling.OutcomeResult) -> OutcomeOut:
    return OutcomeOut(
        record_id=result.record_id,
        state=result.state,
        callback_on=result.callback_on,
        opportunity_id=result.opportunity_id,
    )


def _campaign(row: calling.CampaignRow) -> CampaignOut:
    campaign = row.campaign
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        service=campaign.service,
        script=campaign.script,
        total=sum(row.counts.values()),
        counts=row.counts,
    )


# ── Kolejka i karta ───────────────────────────────────────────────────────


def _can_edit(user: User) -> bool:
    """Wynik zapisuje każdy z „Sprzedaż: edycja” (decyzja Artura 13.11.2026)."""

    return is_admin(user) or has_permission(user, ProductAction.sales_edit)


@router.get("/queue", response_model=QueueOut)
async def call_queue(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    campaign_id: Optional[int] = Query(default=None, ge=1),
    caller_id: Optional[int] = Query(default=None, ge=1),
) -> QueueOut:
    """Kolejka osoby w stałej kolejności sekcji; domyślnie zalogowanej.

    ``caller_id`` (decyzja Artura 13.11.2026): podział Bianca / Marcel i zastępstwa;
    wynik w cudzej kolejce zapisuje każdy z „Sprzedaż: edycja”.
    """

    queue = await calling.load_queue(
        db,
        caller_id or current_user.id,
        campaign_id=campaign_id,
        viewer_id=current_user.id,
    )
    return QueueOut(
        today=queue.today,
        counts=QueueCounts(
            callbacks=queue.callbacks_total,
            no_answer=queue.no_answer_total,
            meetings=len(queue.meetings),
            new=queue.new_total,
            later=queue.later,
        ),
        callbacks=[_item(item) for item in queue.callbacks],
        no_answer=[_item(item) for item in queue.no_answer],
        meetings=[_item(item) for item in queue.meetings],
        new=[_item(item) for item in queue.new],
        campaigns=[Ref(id=id_, name=name) for id_, name in queue.campaigns],
        today_counts=DayCountsOut(**queue.today_counts.__dict__),
        yesterday=queue.yesterday,
        yesterday_counts=DayCountsOut(**queue.yesterday_counts.__dict__),
        callers=[Ref(id=id_, name=name) for id_, name in queue.callers],
    )


@router.get("/records", response_model=RecordTableOut)
async def my_records(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["mine", "all"] = Query(default="mine"),
    caller_id: Optional[int] = Query(default=None, ge=1),
    state: Optional[str] = Query(default=None, max_length=20),
    campaign_id: Optional[int] = Query(default=None, ge=1),
    q: Optional[str] = Query(default=None, max_length=120),
    callback_from: Optional[date] = Query(default=None),
    callback_to: Optional[date] = Query(default=None),
    limit: int = Query(default=calling.TABLE_LIMIT, ge=1, le=calling.TABLE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> RecordTableOut:
    """Widok „Tabela”: rekordy zalogowanej osoby albo wszystkich, z filtrem po wyniku.

    „Wszyscy” (decyzja Artura 12.11.2026) widzi każdy z „Sprzedaż: podgląd”: handlowiec
    ma wiedzieć, do jakich firm i kto dzwoni. Wynik zapisuje każdy z „Sprzedaż: edycja” (13.11.2026).
    """

    if state is not None and state not in calling.TABLE_STATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=STATE_DETAIL)
    table = await calling.list_records(
        db,
        current_user.id if scope == "mine" else caller_id,
        state=state,
        campaign_id=campaign_id,
        search=(q or "").strip() or None,
        callback_from=callback_from,
        callback_to=callback_to,
        limit=limit,
        offset=offset,
    )
    return RecordTableOut(
        items=[_item(item) for item in table.items],
        total=table.total,
        counts=table.counts,
        callers=[Ref(id=id_, name=name) for id_, name in table.callers],
    )


@router.get(
    "/companies/{company_id}/records", response_model=list[CompanyCallRecordOut]
)
async def company_call_records(
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[CompanyCallRecordOut]:
    """Na czyjej liście dzwonienia jest firma: linia na karcie firmy (decyzja Artura 12.11.2026)."""

    return [
        CompanyCallRecordOut(
            record_id=row.record_id,
            campaign=(
                Ref(id=row.campaign_id, name=row.campaign_name or "")
                if row.campaign_id is not None
                else None
            ),
            assignee=(
                Ref(id=row.assignee_id, name=row.assignee_name or "")
                if row.assignee_id is not None
                else None
            ),
            person_name=row.person_name,
            state=row.state,
            callback_on=row.callback_on,
            last_outcome_at=row.last_outcome_at,
        )
        for row in await calling.company_records(db, company_id)
    ]


@router.get("/records/{record_id}", response_model=CardOut)
async def record_card(
    record_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    return _card(
        await calling.record_card(db, record_id, can_edit=_can_edit(current_user))
    )


@router.get("/opportunities/{opportunity_id}", response_model=CardOut)
async def opportunity_card(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    return _card(
        await calling.opportunity_card(
            db, opportunity_id, can_edit=_can_edit(current_user)
        )
    )


@router.post("/records/{record_id}/outcome", response_model=OutcomeOut)
async def save_record_outcome(
    record_id: int,
    payload: calling.OutcomeRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OutcomeOut:
    """Wynik rozmowy dla rekordu kolejki; zapisuje też telefon w dzienniku."""

    record = await calling.locked_record(db, record_id)
    result = await calling.apply_outcome(
        db,
        record,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return _outcome(result)


@router.patch("/records/{record_id}", response_model=CardOut)
async def edit_record(
    record_id: int,
    payload: calling.RecordEdit,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    """Dane kontaktowe z karty kolejki (lista dzwoniących 13.11.2026)."""

    record = await calling.locked_record(db, record_id)
    await calling.edit_record(db, record, payload)
    await db.commit()
    return _card(await calling.record_card(db, record_id, can_edit=True))


@router.post("/records/{record_id}/state", response_model=OutcomeOut)
async def change_record_state(
    record_id: int,
    payload: calling.StateChange,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OutcomeOut:
    """Zmiana statusu z Tabeli: poprawka zapisu bez telefonu w dzienniku."""

    record = await calling.locked_record(db, record_id)
    result = await calling.change_state(
        db,
        record,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return _outcome(result)


@router.get("/reminders", response_model=list[QueueItemOut])
async def call_reminders(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["mine", "all"] = Query(default="mine"),
    caller_id: Optional[int] = Query(default=None, ge=1),
    until: Optional[date] = Query(default=None),
) -> list[QueueItemOut]:
    """„Przypomnienia”: terminy powrotów (Oddzwonić, oferta z ponownym kontaktem)."""

    items = await calling.reminders(
        db, current_user.id if scope == "mine" else caller_id, until=until
    )
    return [_item(item) for item in items]


@router.post("/opportunities/{opportunity_id}/outcome", response_model=OutcomeOut)
async def save_opportunity_outcome(
    opportunity_id: int,
    payload: calling.OutcomeRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OutcomeOut:
    """Wynik rozmowy dla szansy z kolejki; pierwszy zakłada jej rekord."""

    record = await calling.record_for_opportunity(
        db, opportunity_id, user_id=current_user.id
    )
    result = await calling.apply_outcome(
        db,
        record,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return _outcome(result)


# ── Kampanie ──────────────────────────────────────────────────────────────


async def _campaign_out(db: AsyncSession, campaign_id: int) -> CampaignOut:
    for row in await calling.list_campaigns(db):
        if row.campaign.id == campaign_id:
            return _campaign(row)
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)


async def _get_campaign(db: AsyncSession, campaign_id: int) -> SalesCallCampaign:
    campaign = await calling_import.campaign_or_none(db, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)
    return campaign


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[CampaignOut]:
    return [_campaign(row) for row in await calling.list_campaigns(db)]


@router.post(
    "/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED
)
async def create_campaign(
    payload: CampaignCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    campaign = SalesCallCampaign(
        name=payload.name,
        service=(payload.service or "").strip() or None,
        script=(payload.script or "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(campaign)
    await db.commit()
    return await _campaign_out(db, campaign.id)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    campaign = await _get_campaign(db, campaign_id)
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("name"):
        campaign.name = fields["name"]
    for key in ("service", "script"):
        if key in fields:
            setattr(campaign, key, (fields[key] or "").strip() or None)
    await db.commit()
    return await _campaign_out(db, campaign_id)


# ── Import listy ──────────────────────────────────────────────────────────


async def _read_list(file: UploadFile) -> ListFile:
    """Plik czytany najwyżej do limitu + 1 bajt; parser biegnie poza pętlą zdarzeń."""

    payload = await file.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=TOO_BIG_DETAIL
        )
    try:
        return await asyncio.to_thread(parse_list_file, file.filename or "", payload)
    except ListFileError as exc:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.too_large
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(code, detail=exc.detail) from exc


def _source(value: str) -> str:
    text = " ".join((value or "").split())
    if len(text) < MIN_SOURCE_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=SOURCE_REQUIRED
        )
    return text[:MAX_SOURCE_CHARS]


async def _assignee(
    db: AsyncSession, current_user: User, assignee_user_id: Optional[int]
) -> int:
    if assignee_user_id is None or assignee_user_id == current_user.id:
        return current_user.id
    assignee = await db.get(User, assignee_user_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEE_DETAIL
        )
    await resolve_effective_access(db, [assignee])
    if not has_permission(assignee, ProductAction.sales_edit):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEE_DETAIL
        )
    return assignee.id


def _plan_rows(
    plan: calling_import.ImportPlan, names: Optional[dict[int, str]] = None
) -> list[ImportRowOut]:
    names = names or {}
    return [
        ImportRowOut(
            line=item.row.line,
            company=item.row.company,
            person=item.row.person,
            title=item.row.title,
            phone=item.row.phone,
            fate=item.fate,
            detail=item.detail,
            to_decide=item.fate in calling_import.TO_DECIDE,
            assignee=(
                Ref(id=item.assignee_id, name=names[item.assignee_id])
                if item.assignee_id in names
                else None
            ),
        )
        for item in plan.rows
    ]


@router.post("/campaigns/{campaign_id}/import/preview", response_model=ImportPreviewOut)
# Odczyt arkusza i dopasowanie firm kosztują procesor: limit chroni proces web.
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def preview_import(
    request: Request,  # wymagane przez slowapi
    campaign_id: int,
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    contact_source: str = Form(default=""),
    assignee_user_id: Optional[int] = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewOut:
    """Los każdego wiersza listy; niczego nie zapisuje."""

    campaign = await _get_campaign(db, campaign_id)
    assignee_id = await _assignee(db, current_user, assignee_user_id)
    listing = await _read_list(file)
    people = await calling_excel.sales_editors(db)
    plan = await calling_import.plan_import(
        db,
        campaign,
        listing,
        assignee_id=assignee_id,
        people=calling_import.caller_keys(people),
    )
    rows = _plan_rows(plan, dict(people))
    return ImportPreviewOut(
        total=len(rows),
        addable=plan.addable,
        to_decide=sum(1 for row in rows if row.to_decide),
        without_company=plan.without_company,
        counts=plan.counts,
        rows=rows,
    )


@router.post("/campaigns/{campaign_id}/import", response_model=ImportResultOut)
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def import_list(
    request: Request,  # wymagane przez slowapi
    campaign_id: int,
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    contact_source: str = Form(default=""),
    assignee_user_id: Optional[int] = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> ImportResultOut:
    """Dodaje do kolejki wiersze, które przeszły bramki; wymaga „Skąd kontakt”."""

    await _get_campaign(db, campaign_id)
    source = _source(contact_source)
    assignee_id = await _assignee(db, current_user, assignee_user_id)
    listing = await _read_list(file)
    people = await calling_excel.sales_editors(db)
    plan, added = await calling_import.apply_import(
        db,
        campaign_id,
        listing,
        contact_source=source,
        assignee_id=assignee_id,
        user_id=current_user.id,
        people=calling_import.caller_keys(people),
    )
    await db.commit()
    return ImportResultOut(
        added=added,
        total=len(plan.rows),
        without_company=plan.without_company,
        counts=plan.counts,
    )


# ── Skuteczność ───────────────────────────────────────────────────────────


class CallingFunnelOut(BaseModel):
    calls: int
    talks: int
    offers: int
    meetings: int
    dated: int
    held: int
    qualified: int


class CallingCampaignStatsOut(BaseModel):
    id: Optional[int]
    name: str
    service: Optional[str]
    on_list: Optional[int]
    left: Optional[int]
    days_left: Optional[int]
    calls: int
    talks: int
    offers: int
    meetings: int


class CallingSourceStatsOut(BaseModel):
    source: str
    records: int
    reached: int
    talks: int
    meetings: int
    objections: int


class CallingHourCellOut(BaseModel):
    weekday: int
    hour: int
    calls: int
    talks: int
    rate: Optional[float]


class CallingPersonStatsOut(BaseModel):
    user_id: int
    name: str
    days: int
    calls: int
    talks: int
    offers: int
    meetings: int
    dated: int
    qualified: int
    excel_days: int
    excel_meetings: int


class CallingExcelShareOut(BaseModel):
    days: int
    calls: int
    talks: int
    offers: int
    meetings: int


class CallingDayStatsOut(BaseModel):
    day: date
    calls: int
    talks: int
    offers: int
    meetings: int
    source: str


class CallingInsightOut(BaseModel):
    tone: str
    text: str


class CallingEffectivenessOut(BaseModel):
    start: date
    end: date
    workdays: int
    funnel: CallingFunnelOut
    outcomes: dict[str, int]
    campaigns: list[CallingCampaignStatsOut]
    sources: list[CallingSourceStatsOut]
    hours: list[CallingHourCellOut]
    offer_followup: dict[str, int]
    people: list[CallingPersonStatsOut]
    insights: list[CallingInsightOut]
    excel: CallingExcelShareOut
    daily: list[CallingDayStatsOut]
    campaign_options: list[Ref]


@router.get("/effectiveness", response_model=CallingEffectivenessOut)
async def effectiveness(
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
    period: calling_stats.Period = Query(default="week"),
    campaign_id: Optional[int] = Query(default=None, ge=1),
    mine: bool = Query(default=False),
) -> CallingEffectivenessOut:
    """Co daje dzwonienie: lejek, kampanie, listy, pory dnia i osoby (decyzje 11.11.2026).

    Tylko „Sprzedaż: edycja”; tabela osób jest pełna dla każdego z tym uprawnieniem.
    """

    result = await calling_stats.load_effectiveness(
        db,
        period=period,
        today=business_today(),
        user_id=current_user.id if mine else None,
        campaign_id=campaign_id,
    )
    return CallingEffectivenessOut(
        start=result.start,
        end=result.end,
        workdays=result.workdays,
        funnel=CallingFunnelOut(**result.funnel.__dict__),
        outcomes=result.outcomes,
        campaigns=[CallingCampaignStatsOut(**row.__dict__) for row in result.campaigns],
        sources=[CallingSourceStatsOut(**row.__dict__) for row in result.sources],
        hours=[CallingHourCellOut(**cell.__dict__) for cell in result.hours],
        offer_followup=result.offer_followup,
        people=[CallingPersonStatsOut(**row.__dict__) for row in result.people],
        insights=[CallingInsightOut(tone=i.tone, text=i.text) for i in result.insights],
        excel=CallingExcelShareOut(**result.excel.__dict__),
        daily=[CallingDayStatsOut(**row.__dict__) for row in result.daily],
        campaign_options=[Ref(id=i, name=n) for i, n in result.campaign_options],
    )


# ── Przeniesienie Excela dzwoniących (arkusz = osoba) ─────────────────────

SHEET_ASSIGNEE_DETAIL = "Wybierz osobę dla arkusza „{title}”."
ASSIGNEES_FORMAT_DETAIL = "Niepoprawne przypisanie arkuszy do osób."


class SheetPlanOut(BaseModel):
    title: str
    assignee_id: Optional[int]
    rows: int
    states: dict[str, int]
    review: int
    fates: dict[str, int]
    addable: int
    without_company: int
    moved: int
    days: int
    duplicate_days: int
    totals: dict[str, int]


class ExcelPreviewOut(BaseModel):
    sheets: list[SheetPlanOut]
    people: list[Ref]


class ExcelResultOut(BaseModel):
    added: int
    days: int


async def _read_workbook(file: UploadFile) -> list[calling_excel.Sheet]:
    payload = await file.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=TOO_BIG_DETAIL
        )
    try:
        return await asyncio.to_thread(
            calling_excel.parse_workbook,
            file.filename or "",
            payload,
            business_today(),
        )
    except ListFileError as exc:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.too_large
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(code, detail=exc.detail) from exc


def _assignees(raw: str, people: list[tuple[int, str]]) -> dict[str, int]:
    """Przypisanie z formularza: {nazwa arkusza: id osoby z „Sprzedaż: edycja”}."""

    try:
        value = json.loads(raw or "{}")
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEES_FORMAT_DETAIL
        ) from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and isinstance(user_id, int)
        and not isinstance(user_id, bool)
        for key, user_id in value.items()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEES_FORMAT_DETAIL
        )
    allowed = {user_id for user_id, _ in people}
    if any(user_id not in allowed for user_id in value.values()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEE_DETAIL
        )
    return value


@router.post("/campaigns/{campaign_id}/excel/preview", response_model=ExcelPreviewOut)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def preview_excel(
    request: Request,  # wymagane przez slowapi
    campaign_id: int,
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    assignees: str = Form(default="{}"),
    db: AsyncSession = Depends(get_db),
) -> ExcelPreviewOut:
    """Bieg na sucho: co stanie się z każdym arkuszem i wierszem; niczego nie zapisuje.

    Arkusze przechodzą przez zapis po kolei w savepoincie, który się cofa, więc
    podgląd liczy tak samo jak „Przenieś”.
    """

    campaign = await _get_campaign(db, campaign_id)
    people = await calling_excel.sales_editors(db)
    chosen = _assignees(assignees, people)
    sheets = await _read_workbook(file)
    plans = await calling_excel.plan_sheets(
        db, campaign, sheets, chosen, people, user_id=current_user.id
    )
    return ExcelPreviewOut(
        sheets=[SheetPlanOut(**plan.__dict__) for plan in plans],
        people=[Ref(id=user_id, name=name) for user_id, name in people],
    )


@router.post("/campaigns/{campaign_id}/excel", response_model=ExcelResultOut)
@limiter.limit("5/minute", key_func=user_or_ip_key)
async def transfer_excel(
    request: Request,  # wymagane przez slowapi
    campaign_id: int,
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    contact_source: str = Form(default=""),
    assignees: str = Form(default="{}"),
    db: AsyncSession = Depends(get_db),
) -> ExcelResultOut:
    """Jednorazowe przeniesienie Excela: każdy arkusz do kolejki wybranej osoby."""

    await _get_campaign(db, campaign_id)
    source = _source(contact_source)
    people = await calling_excel.sales_editors(db)
    chosen = _assignees(assignees, people)
    sheets = await _read_workbook(file)
    missing = next((sheet.title for sheet in sheets if sheet.title not in chosen), None)
    if missing is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=SHEET_ASSIGNEE_DETAIL.format(title=missing),
        )
    result = await calling_excel.apply_sheets(
        db,
        campaign_id,
        sheets,
        chosen,
        contact_source=source,
        user_id=current_user.id,
    )
    await db.commit()
    return ExcelResultOut(added=result.added, days=result.days)
