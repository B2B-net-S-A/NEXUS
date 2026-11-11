"""Sprzedaż → Dzwonienie: kolejka, wynik rozmowy, kampanie i import listy.

Prefiks ``/api/sales/calling`` (wpięty w ``app/main.py``). Odczyt: „Sprzedaż: podgląd”,
zapis: „Sprzedaż: edycja”. Kolejka jest zawsze zalogowanej osoby: przełącznika osoby,
celu dziennego i paska postępu nie ma z założenia (decyzje Artura 10.11.2026,
``docs/claude/sprzedaz/dzwonienie-kampanie-i-import-listy.md``).

Bez ``from __future__ import annotations``: trasy importu mają ``@limiter.limit``,
a moduł z limiterem i PEP 563 zamienia parametry ``Annotated`` w parametry query.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Optional

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
from app.core.rate_limit import limiter
from app.models.sales import SalesCallCampaign
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales import calling, calling_import
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


class QueueCounts(BaseModel):
    callbacks: int
    meetings: int
    new: int
    #: Rekordy z datą powrotu w przyszłości: wrócą same w swoim dniu.
    later: int


class QueueOut(BaseModel):
    today: date
    counts: QueueCounts
    callbacks: list[QueueItemOut]
    meetings: list[QueueItemOut]
    new: list[QueueItemOut]
    campaigns: list[Ref]


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


@router.get("/queue", response_model=QueueOut)
async def call_queue(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    campaign_id: Optional[int] = Query(default=None, ge=1),
) -> QueueOut:
    """Kolejka zalogowanej osoby w stałej kolejności sekcji."""

    queue = await calling.load_queue(db, current_user.id, campaign_id=campaign_id)
    return QueueOut(
        today=queue.today,
        counts=QueueCounts(
            callbacks=queue.callbacks_total,
            meetings=len(queue.meetings),
            new=queue.new_total,
            later=queue.later,
        ),
        callbacks=[_item(item) for item in queue.callbacks],
        meetings=[_item(item) for item in queue.meetings],
        new=[_item(item) for item in queue.new],
        campaigns=[Ref(id=id_, name=name) for id_, name in queue.campaigns],
    )


@router.get("/records/{record_id}", response_model=CardOut)
async def record_card(
    record_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    return _card(
        await calling.record_card(
            db, record_id, user_id=current_user.id, admin=is_admin(current_user)
        )
    )


@router.get("/opportunities/{opportunity_id}", response_model=CardOut)
async def opportunity_card(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    return _card(
        await calling.opportunity_card(
            db, opportunity_id, user_id=current_user.id, admin=is_admin(current_user)
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
        admin=is_admin(current_user),
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return _outcome(result)


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
        admin=is_admin(current_user),
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


def _plan_rows(plan: calling_import.ImportPlan) -> list[ImportRowOut]:
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
        )
        for item in plan.rows
    ]


@router.post("/campaigns/{campaign_id}/import/preview", response_model=ImportPreviewOut)
# Odczyt arkusza i dopasowanie firm kosztują procesor: limit chroni proces web.
@limiter.limit("20/minute")
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
    plan = await calling_import.plan_import(
        db, campaign, listing, assignee_id=assignee_id
    )
    rows = _plan_rows(plan)
    return ImportPreviewOut(
        total=len(rows),
        addable=plan.addable,
        to_decide=sum(1 for row in rows if row.to_decide),
        without_company=plan.without_company,
        counts=plan.counts,
        rows=rows,
    )


@router.post("/campaigns/{campaign_id}/import", response_model=ImportResultOut)
@limiter.limit("10/minute")
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
    plan, added = await calling_import.apply_import(
        db,
        campaign_id,
        listing,
        contact_source=source,
        assignee_id=assignee_id,
        user_id=current_user.id,
    )
    await db.commit()
    return ImportResultOut(
        added=added,
        total=len(plan.rows),
        without_company=plan.without_company,
        counts=plan.counts,
    )
