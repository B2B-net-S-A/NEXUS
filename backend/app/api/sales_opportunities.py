"""Sprzedaż → Lejki i szanse (Atlas → NEXUS).

Prefiksy ``/api/sales/pipelines``, ``/api/sales/opportunities`` i
``/api/sales/summary`` (wpięte w ``app/main.py``). Odczyt: „Sprzedaż: podgląd”, zapis: „Sprzedaż: edycja”;
zmianę opiekuna robi obecny opiekun albo admin. Ruch szansy po etapach idzie
wyłącznie przez ``POST /{id}/move`` — reguły cyklu życia są w
``services/sales/lifecycle.py``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.sales_gates import SalesEditUser, SalesViewUser, ensure_owner_or_admin
from app.core.database import get_db
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services import sales_schema as schema
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import (
    calls,
    client_gate,
    company_dates,
    decision_map,
    history,
    meeting_decisions,
    offer_steps,
)
from app.services.sales.lifecycle import apply_stage, deal_value
from app.services.sales.motion import build_atlas_motion, entry_keys
from app.services.sales.next_step import Step, StepSignals, load_signals
from app.services.sales.offers import OFFER_STAGE_KEYS
from app.services.sales.summary import Period, build_summary
from app.services.sales.touch import last_touch_at
from app.services.sales_schema import OpportunityEventKind

pipelines_router = APIRouter()
router = APIRouter()
summary_router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiej szansy."
COMPANY_MISSING_DETAIL = "Wybierz firmę z kartoteki sprzedaży."
STAGE_MISMATCH_DETAIL = "Ten etap nie należy do lejka tej szansy."
DECISION_PERSON_STALE = (
    "Ktoś właśnie zmienił tę osobę na mapie. Zamknij okno i otwórz ją ponownie."
)

ServiceLine = Literal[schema.SERVICE_LINES]  # type: ignore[valid-type]
StatusValue = Literal[schema.OPPORTUNITY_STATUSES]  # type: ignore[valid-type]
ContactRole = Literal[schema.CONTACT_ROLES]  # type: ignore[valid-type]


# ── Lejki ────────────────────────────────────────────────────────────────


class SalesStageOut(BaseModel):
    id: int
    key: str
    name: str
    position: int
    probability: int
    outcome: str
    qualifies: bool
    color: Optional[str]


class PipelineOut(BaseModel):
    id: int
    key: str
    name: str
    is_default: bool
    stages: list[SalesStageOut]


async def _stages(db: AsyncSession, pipeline_id: int) -> list[SalesPipelineStage]:
    return list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == pipeline_id)
                .order_by(SalesPipelineStage.position, SalesPipelineStage.id)
            )
        ).scalars()
    )


@pipelines_router.get("", response_model=list[PipelineOut])
async def list_pipelines(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[PipelineOut]:
    pipelines = (
        await db.execute(
            select(SalesPipeline)
            .where(SalesPipeline.archived_at.is_(None))
            .order_by(SalesPipeline.position, SalesPipeline.id)
        )
    ).scalars()
    result = []
    for pipeline in pipelines:
        stages = await _stages(db, pipeline.id)
        result.append(
            PipelineOut(
                id=pipeline.id,
                key=pipeline.key,
                name=pipeline.name,
                is_default=pipeline.is_default,
                stages=[
                    SalesStageOut.model_validate(s, from_attributes=True)
                    for s in stages
                ],
            )
        )
    return result


# ── Szanse ───────────────────────────────────────────────────────────────


class RoleItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    count: int = Field(default=1, ge=1, le=500)
    seniority: Optional[str] = Field(default=None, max_length=60)
    skills: list[str] = Field(default_factory=list, max_length=30)


class OpportunityFields(BaseModel):
    description: Optional[str] = Field(default=None, max_length=20_000)
    service_line: Optional[ServiceLine] = None
    value: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    mrr_value: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    one_off_value: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    margin_pct: Optional[Decimal] = Field(
        default=None, ge=-100, le=100, max_digits=5, decimal_places=2
    )
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    contract_months: Optional[int] = Field(default=None, ge=1, le=120)
    expected_close_date: Optional[date] = None
    primary_contact_id: Optional[int] = None
    roles: Optional[list[RoleItem]] = Field(default=None, max_length=50)
    source: Optional[str] = Field(default=None, max_length=60)
    campaign: Optional[str] = Field(default=None, max_length=120)
    tags: Optional[list[str]] = Field(default=None, max_length=30)
    owner_user_id: Optional[int] = None
    keep_open_until: Optional[date] = None


class OpportunityCreate(OpportunityFields):
    company_id: int
    title: str = Field(min_length=1, max_length=255)
    pipeline_id: Optional[int] = None
    stage_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj nazwę szansy.")
        return value


class OpportunityFromMeeting(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    service_line: ServiceLine
    contact_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj nazwę szansy.")
        return value


class OpportunityUpdate(OpportunityFields):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)


class MoveRequest(BaseModel):
    stage_id: int
    lost_reason: Optional[str] = Field(default=None, max_length=500)


class ContactLink(BaseModel):
    role: Optional[ContactRole] = None


class Ref(BaseModel):
    id: int
    name: str


class OpportunityContactOut(BaseModel):
    id: int
    full_name: str
    title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    role: Optional[str]
    #: Osoba nie życzy sobie kontaktu: numer i mail przestają być klikalne.
    do_not_contact_at: Optional[datetime] = None


class NextStepOut(BaseModel):
    kind: str
    at: datetime
    subject: Optional[str]


class LastContactOut(BaseModel):
    kind: str
    direction: Optional[str]
    at: datetime


class OpportunityOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    company: Ref
    pipeline_id: int
    stage: SalesStageOut
    status: str
    service_line: Optional[str]
    value: Optional[Decimal]
    mrr_value: Optional[Decimal]
    one_off_value: Optional[Decimal]
    margin_pct: Optional[Decimal]
    currency: str
    contract_months: Optional[int]
    probability: int
    weighted_value: Optional[Decimal]
    expected_close_date: Optional[date]
    qualified_at: Optional[datetime]
    won_at: Optional[datetime]
    lost_at: Optional[datetime]
    lost_reason: Optional[str]
    primary_contact_id: Optional[int]
    roles: list[Any]
    source: Optional[str]
    campaign: Optional[str]
    tags: list[Any]
    owner: Optional[Ref]
    last_activity_at: Optional[datetime]
    #: Ostatni dotyk (``services/sales/touch.py``); jest zawsze, dolna granica to założenie.
    last_touch_at: datetime
    #: Definicje: ``services/sales/next_step.py``.
    next_step: Optional[NextStepOut]
    overdue_step: Optional[NextStepOut]
    last_contact: Optional[LastContactOut]
    #: Klient napisał ostatni, a kroku nie ma.
    waiting_for_reply: bool
    #: Brak kroku na szansie założonej albo ruszonej po wdrożeniu zasad.
    step_alarm: bool
    keep_open_until: Optional[date]
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class AtlasMotion(BaseModel):
    """„Sales Motion” z Atlasa (Fabryki IT, MEDDIC, produkty); mapę da się poprawiać."""

    it_factory: Optional[dict[str, Any]]
    meddic: Optional[dict[str, Any]]
    products: list[str]
    subscription_items: list[dict[str, Any]]


class OpportunityDetail(OpportunityOut):
    contacts: list[OpportunityContactOut]
    atlas_motion: Optional[AtlasMotion] = None
    #: Lejek Fabryki IT albo szansa, która ma już mapę: można dodawać osoby.
    decision_map_enabled: bool = False


class OpportunityList(BaseModel):
    items: list[OpportunityOut]
    total: int


def _weighted(opportunity: SalesOpportunity) -> Optional[Decimal]:
    if opportunity.value is None:
        return None
    return (opportunity.value * opportunity.probability / 100).quantize(Decimal("0.01"))


def _step_out(step: Optional[Step]) -> Optional[NextStepOut]:
    if step is None:
        return None
    return NextStepOut(kind=step.kind, at=step.at, subject=step.subject)


def _out(row: Any, signals: StepSignals) -> OpportunityOut:
    opp: SalesOpportunity = row.SalesOpportunity
    stage: SalesPipelineStage = row.SalesPipelineStage
    return OpportunityOut(
        id=opp.id,
        title=opp.title,
        description=opp.description,
        company=Ref(id=opp.company_id, name=row.company_name),
        pipeline_id=opp.pipeline_id,
        stage=SalesStageOut.model_validate(stage, from_attributes=True),
        status=opp.status,
        service_line=opp.service_line,
        value=opp.value,
        mrr_value=opp.mrr_value,
        one_off_value=opp.one_off_value,
        margin_pct=opp.margin_pct,
        currency=opp.currency,
        contract_months=opp.contract_months,
        probability=opp.probability,
        weighted_value=_weighted(opp),
        expected_close_date=opp.expected_close_date,
        qualified_at=opp.qualified_at,
        won_at=opp.won_at,
        lost_at=opp.lost_at,
        lost_reason=opp.lost_reason,
        primary_contact_id=opp.primary_contact_id,
        roles=list(opp.roles or []),
        source=opp.source,
        campaign=opp.campaign,
        tags=list(opp.tags or []),
        owner=(
            Ref(id=opp.owner_user_id, name=row.owner_name or "")
            if opp.owner_user_id is not None
            else None
        ),
        last_activity_at=opp.last_activity_at,
        last_touch_at=row.last_touch_at,
        next_step=_step_out(signals.next_step),
        overdue_step=_step_out(signals.overdue_step),
        last_contact=(
            LastContactOut(
                kind=signals.last_contact.kind,
                direction=signals.last_contact.direction,
                at=signals.last_contact.at,
            )
            if signals.last_contact is not None
            else None
        ),
        waiting_for_reply=signals.waiting_for_reply,
        step_alarm=signals.step_alarm,
        keep_open_until=opp.keep_open_until,
        archived_at=opp.archived_at,
        created_at=opp.created_at,
        updated_at=opp.updated_at,
    )


def _base_query(now: datetime):
    owner = aliased(User)
    return (
        select(
            SalesOpportunity,
            SalesPipelineStage,
            SalesCompany.name.label("company_name"),
            owner.name.label("owner_name"),
            last_touch_at(now).label("last_touch_at"),
        )
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .outerjoin(owner, owner.id == SalesOpportunity.owner_user_id)
    )


async def _get(db: AsyncSession, opportunity_id: int) -> SalesOpportunity:
    opp = await db.get(SalesOpportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return opp


async def _decision_map_enabled(db: AsyncSession, opp: SalesOpportunity) -> bool:
    if decision_map.decision_entries(opp.custom_fields):
        return True
    key = await db.scalar(
        select(SalesPipeline.key).where(SalesPipeline.id == opp.pipeline_id)
    )
    return key == decision_map.IT_FACTORIES_PIPELINE_KEY


async def _detail(db: AsyncSession, opportunity_id: int) -> OpportunityDetail:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(_base_query(now).where(SalesOpportunity.id == opportunity_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    contacts = (
        await db.execute(
            select(SalesContact, SalesOpportunityContact.role)
            .join(
                SalesOpportunityContact,
                SalesOpportunityContact.contact_id == SalesContact.id,
            )
            .where(SalesOpportunityContact.opportunity_id == opportunity_id)
            .order_by(SalesContact.full_name)
        )
    ).all()
    opp: SalesOpportunity = row.SalesOpportunity
    motion = await build_atlas_motion(
        db, company_id=opp.company_id, custom_fields=opp.custom_fields
    )
    signals = await load_signals(db, [opp], now=now)
    return OpportunityDetail(
        **_out(row, signals[opp.id]).model_dump(),
        atlas_motion=AtlasMotion(**motion) if motion is not None else None,
        decision_map_enabled=await _decision_map_enabled(db, opp),
        contacts=[
            OpportunityContactOut(
                id=contact.id,
                full_name=contact.full_name,
                title=contact.title,
                email=contact.email,
                phone=contact.phone or contact.mobile_phone,
                role=role,
                do_not_contact_at=contact.do_not_contact_at,
            )
            for contact, role in contacts
        ],
    )


async def _default_pipeline(db: AsyncSession) -> SalesPipeline:
    pipeline = (
        await db.execute(
            select(SalesPipeline)
            .where(SalesPipeline.archived_at.is_(None))
            .order_by(SalesPipeline.is_default.desc(), SalesPipeline.position)
            .limit(1)
        )
    ).scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Nie ma żadnego lejka sprzedaży."
        )
    return pipeline


async def _check_links(db: AsyncSession, fields: dict[str, Any]) -> None:
    contact_id = fields.get("primary_contact_id")
    if contact_id is not None and await db.get(SalesContact, contact_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiego kontaktu."
        )
    owner_id = fields.get("owner_user_id")
    if owner_id is not None:
        owner = await db.get(User, owner_id)
        if owner is None or not owner.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Opiekun musi być aktywnym kontem w NEXUSIE.",
            )


def _apply(opp: SalesOpportunity, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if key in ("roles", "tags"):
            value = value or []
        elif key == "currency" and value:
            value = value.upper()
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(opp, key, value)
    # Wartość przeliczamy z rozbicia tylko, gdy rozbicie jest — szansa z samym
    # ``value`` (Atlas sprzed MRR/jednorazowej) nie traci go przy edycji.
    if fields.get("value") is not None:
        opp.value = fields["value"]
    elif {"mrr_value", "one_off_value"} & fields.keys() and (
        opp.mrr_value is not None or opp.one_off_value is not None
    ):
        opp.value = deal_value(opp.mrr_value, opp.one_off_value, None)


_SORTS = {
    "updated": (SalesOpportunity.updated_at.desc(),),
    "value": (SalesOpportunity.value.desc().nulls_last(),),
    "close": (SalesOpportunity.expected_close_date.asc().nulls_last(),),
    "created": (SalesOpportunity.created_at.desc(),),
}


@router.get("", response_model=OpportunityList)
async def list_opportunities(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    pipeline_id: Optional[int] = None,
    company_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    opportunity_status: Optional[StatusValue] = Query(default=None, alias="status"),
    q: Optional[str] = Query(default=None, max_length=200),
    service_line: Optional[ServiceLine] = None,
    created_from: Optional[date] = None,
    created_to: Optional[date] = None,
    offers_only: bool = False,
    archived: bool = False,
    sort: Literal["updated", "value", "close", "activity", "created"] = "updated",
    # Atlas ma ~1,5 tys. szans — tablica wczytuje cały lejek naraz.
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> OpportunityList:
    now = datetime.now(timezone.utc)
    query = _base_query(now).where(
        SalesOpportunity.archived_at.is_not(None)
        if archived
        else SalesOpportunity.archived_at.is_(None)
    )
    if pipeline_id is not None:
        query = query.where(SalesOpportunity.pipeline_id == pipeline_id)
    if company_id is not None:
        query = query.where(SalesOpportunity.company_id == company_id)
    if owner_id is not None:
        query = query.where(SalesOpportunity.owner_user_id == owner_id)
    if opportunity_status:
        query = query.where(SalesOpportunity.status == opportunity_status)
    if service_line:
        query = query.where(SalesOpportunity.service_line == service_line)
    if offers_only:
        query = query.where(SalesPipelineStage.key.in_(OFFER_STAGE_KEYS))
    # Daty w kalendarzu firmy, obie granice włącznie (jak filtr w Atlasie).
    created_day = func.date(func.timezone(DEFAULT_TZ, SalesOpportunity.created_at))
    if created_from is not None:
        query = query.where(created_day >= created_from)
    if created_to is not None:
        query = query.where(created_day <= created_to)
    text = (q or "").strip()
    if text:
        conditions = [
            polish_folded_ilike(SalesOpportunity.title, text),
            polish_folded_ilike(SalesCompany.name, text),
        ]
        # NIP tylko dla frazy z samych cyfr: „10CLOUDS” nie może szukać po „10”.
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 3 and re.fullmatch(r"[\d\s-]+", text):
            nip = func.replace(func.replace(SalesCompany.nip, "-", ""), " ", "")
            conditions.append(nip.like(f"%{digits}%"))
        query = query.where(or_(*conditions))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    # „Ostatni kontakt” sortuje po tym samym dotyku, który widać na kafelku.
    ordering = (last_touch_at(now).desc(),) if sort == "activity" else _SORTS[sort]
    rows = (
        await db.execute(
            query.order_by(*ordering, SalesOpportunity.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    signals = await load_signals(db, [row.SalesOpportunity for row in rows], now=now)
    return OpportunityList(
        items=[_out(row, signals[row.SalesOpportunity.id]) for row in rows],
        total=int(total or 0),
    )


@router.post("", response_model=OpportunityDetail, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    payload: OpportunityCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    company = await db.get(SalesCompany, payload.company_id)
    if company is None or company.archived_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=COMPANY_MISSING_DETAIL
        )
    if payload.pipeline_id is not None:
        pipeline = await db.get(SalesPipeline, payload.pipeline_id)
        if pipeline is None or pipeline.archived_at is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiego lejka."
            )
    else:
        pipeline = await _default_pipeline(db)
    stages = await _stages(db, pipeline.id)
    if not stages:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Ten lejek nie ma jeszcze etapów."
        )
    if payload.stage_id is not None:
        stage = next((s for s in stages if s.id == payload.stage_id), None)
        if stage is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=STAGE_MISMATCH_DETAIL
            )
    else:
        stage = next((s for s in stages if s.outcome == "open"), stages[0])

    fields = payload.model_dump(
        exclude={"company_id", "title", "pipeline_id", "stage_id"}, exclude_none=True
    )
    await _check_links(db, fields)
    opp = SalesOpportunity(
        company_id=company.id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        title=payload.title,
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    _apply(opp, fields)
    now = datetime.now(timezone.utc)
    apply_stage(opp, stage, stages, now=now)
    db.add(opp)
    await db.flush()
    history.record_created(db, opp, user_id=current_user.id)
    await offer_steps.schedule_on_entry(
        db, opp, stage.key, user_id=current_user.id, now=now
    )
    if opp.primary_contact_id is not None:
        db.add(
            SalesOpportunityContact(
                opportunity_id=opp.id, contact_id=opp.primary_contact_id
            )
        )
    await db.commit()
    # D3: szansa w firmie to moment, w którym „kto tam pracuje” zaczyna się
    # liczyć — uzupełniamy daty osób z tej firmy w tle (raz na 30 dni).
    if company_dates.needs_run(company.dates_backfill, now=now):
        company_dates.schedule_company_dates(company.id)
    return await _detail(db, opp.id)


@router.get("/owner-candidates", response_model=list[Ref])
async def list_owner_candidates(
    _user: SalesEditUser, db: AsyncSession = Depends(get_db)
) -> list[Ref]:
    """Komu można przekazać szansę: aktywne konta z „Sprzedaż: edycja”."""

    active = list(
        (
            await db.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        ).scalars()
    )
    await resolve_effective_access(db, active)
    return [
        Ref(id=user.id, name=user.name)
        for user in active
        if has_permission(user, ProductAction.sales_edit)
    ]


@router.post(
    "/from-activity/{activity_id}",
    response_model=OpportunityDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_opportunity_from_meeting(
    activity_id: int,
    payload: OpportunityFromMeeting,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    """Szansa ze spotkania z Outlooka; spotkanie od razu przypina się do niej."""

    activity = await meeting_decisions.lock_activity(db, activity_id)
    if activity is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Nie ma takiego spotkania."
        )
    if activity.kind != "meeting" or not meeting_decisions.is_outlook(activity):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Szansę da się założyć tylko ze spotkania z Outlooka.",
        )
    if activity.opportunity_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="To spotkanie jest już przy szansie."
        )
    company = (
        await db.get(SalesCompany, activity.company_id)
        if activity.company_id is not None
        else None
    )
    if company is None or company.archived_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=COMPANY_MISSING_DETAIL
        )
    if company.normalized_name == client_gate.OWN_COMPANY_KEY:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=client_gate.OWN_COMPANY_REFUSAL
        )
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=company.id,
                client_id=company.client_id,
                normalized_name=company.normalized_name,
            )
        ],
    )
    if company.id in clients:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=clients[company.id].refusal
        )
    contact_ids = list(dict.fromkeys(payload.contact_ids))
    allowed = {p.id for p in await meeting_decisions.company_people(db, company.id)}
    if set(contact_ids) - allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kontakt nie należy do tej firmy.",
        )
    pipeline = await _default_pipeline(db)
    stages = await _stages(db, pipeline.id)
    if not stages:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Ten lejek nie ma jeszcze etapów."
        )
    stage = next((s for s in stages if s.outcome == "open"), stages[0])
    now = datetime.now(timezone.utc)
    opp = SalesOpportunity(
        company_id=company.id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        title=payload.title,
        service_line=payload.service_line,
        source=meeting_decisions.OPPORTUNITY_SOURCE,
        primary_contact_id=contact_ids[0] if contact_ids else None,
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    apply_stage(opp, stage, stages, now=now)
    db.add(opp)
    await db.flush()
    history.record_created(db, opp, user_id=current_user.id)
    db.add_all(
        SalesOpportunityContact(opportunity_id=opp.id, contact_id=contact_id)
        for contact_id in contact_ids
    )
    meeting_decisions.attach(db, activity, opp, user_id=current_user.id, now=now)
    await db.commit()
    if company_dates.needs_run(company.dates_backfill, now=now):
        company_dates.schedule_company_dates(company.id)
    return await _detail(db, opp.id)


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
async def get_opportunity(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    return await _detail(db, opportunity_id)


@router.patch("/{opportunity_id}", response_model=OpportunityDetail)
async def update_opportunity(
    opportunity_id: int,
    payload: OpportunityUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get(db, opportunity_id)
    fields = payload.model_dump(exclude_unset=True)
    if "title" in fields and not (fields["title"] or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Podaj nazwę szansy."
        )
    if "owner_user_id" in fields and fields["owner_user_id"] != opp.owner_user_id:
        ensure_owner_or_admin(current_user, opp.owner_user_id)
    if fields.get("currency", "") is None:
        fields.pop("currency")
    await _check_links(db, fields)
    before = history.snapshot(opp)
    _apply(opp, fields)
    history.record_changes(db, opp, before, user_id=current_user.id)
    await db.commit()
    return await _detail(db, opportunity_id)


@router.post("/{opportunity_id}/move", response_model=OpportunityDetail)
async def move_opportunity(
    opportunity_id: int,
    payload: MoveRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get(db, opportunity_id)
    stages = await _stages(db, opp.pipeline_id)
    stage = next((s for s in stages if s.id == payload.stage_id), None)
    if stage is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=STAGE_MISMATCH_DETAIL
        )
    before = history.snapshot(opp)
    if stage.id != opp.stage_id:
        now = datetime.now(timezone.utc)
        apply_stage(opp, stage, stages, now=now)
        await offer_steps.schedule_on_entry(
            db, opp, stage.key, user_id=current_user.id, now=now
        )
    if stage.outcome == "lost":
        reason = (payload.lost_reason or "").strip()
        if reason:
            opp.lost_reason = reason
    else:
        opp.lost_reason = None
    history.record_changes(db, opp, before, user_id=current_user.id)
    await db.commit()
    return await _detail(db, opportunity_id)


@router.post("/{opportunity_id}/archive", response_model=OpportunityDetail)
async def archive_opportunity(
    opportunity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get(db, opportunity_id)
    if opp.archived_at is None:
        opp.archived_at = datetime.now(timezone.utc)
        opp.archived_reason = "manual"
        history.record(
            db,
            opportunity_id=opp.id,
            user_id=current_user.id,
            kind=OpportunityEventKind.archived,
        )
        await db.commit()
    return await _detail(db, opportunity_id)


@router.post("/{opportunity_id}/restore", response_model=OpportunityDetail)
async def restore_opportunity(
    opportunity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get(db, opportunity_id)
    if opp.archived_at is not None:
        opp.archived_at = None
        opp.archived_reason = None
        history.record(
            db,
            opportunity_id=opp.id,
            user_id=current_user.id,
            kind=OpportunityEventKind.restored,
        )
        await db.commit()
    return await _detail(db, opportunity_id)


class HistoryEventOut(BaseModel):
    id: int
    kind: str
    field: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    #: Nazwa etapu, opiekuna albo firmy dla pól z identyfikatorem.
    old_label: Optional[str]
    new_label: Optional[str]
    user: Optional[Ref]
    created_at: datetime


#: Pole z identyfikatorem → (model, kolumna z nazwą) do podpisu w historii.
_LABELLED = {
    "stage_id": (SalesPipelineStage, SalesPipelineStage.name),
    "owner_user_id": (User, User.name),
    "company_id": (SalesCompany, SalesCompany.name),
    # Temat czytany z wiersza: oznaczony jako prywatny znika też z historii.
    meeting_decisions.OUTLOOK_FIELD: (
        SalesActivity,
        func.coalesce(SalesActivity.subject, meeting_decisions.NO_SUBJECT),
    ),
}


@router.get("/{opportunity_id}/history", response_model=list[HistoryEventOut])
async def opportunity_history(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[HistoryEventOut]:
    """„Historia zmian” szansy — najnowsze na górze."""

    await _get(db, opportunity_id)
    events = list(
        (
            await db.execute(
                select(SalesOpportunityEvent)
                .where(SalesOpportunityEvent.opportunity_id == opportunity_id)
                .order_by(
                    SalesOpportunityEvent.created_at.desc(),
                    SalesOpportunityEvent.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
    )
    labels: dict[str, dict[str, str]] = {}
    for field, (model, name) in _LABELLED.items():
        ids = {
            int(value)
            for event in events
            if event.field == field
            for value in (event.old_value, event.new_value)
            if value is not None and value.isdigit()
        }
        if ids:
            rows = await db.execute(select(model.id, name).where(model.id.in_(ids)))
            labels[field] = {str(row_id): label for row_id, label in rows.all()}
    user_ids = {event.user_id for event in events if event.user_id is not None}
    users = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        )
        if user_ids
        else {}
    )

    def _label(field: Optional[str], value: Optional[str]) -> Optional[str]:
        if field is None or value is None:
            return None
        return labels.get(field, {}).get(value)

    return [
        HistoryEventOut(
            id=event.id,
            kind=event.kind,
            field=event.field,
            old_value=event.old_value,
            new_value=event.new_value,
            old_label=_label(event.field, event.old_value),
            new_label=_label(event.field, event.new_value),
            user=(
                Ref(id=event.user_id, name=users.get(event.user_id) or "")
                if event.user_id is not None
                else None
            ),
            created_at=event.created_at,
        )
        for event in events
    ]


@router.put("/{opportunity_id}/contacts/{contact_id}", response_model=OpportunityDetail)
async def link_contact(
    opportunity_id: int,
    contact_id: int,
    payload: ContactLink,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    await _get(db, opportunity_id)
    if await db.get(SalesContact, contact_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiego kontaktu."
        )
    link = await db.get(SalesOpportunityContact, (opportunity_id, contact_id))
    if link is None:
        db.add(
            SalesOpportunityContact(
                opportunity_id=opportunity_id, contact_id=contact_id, role=payload.role
            )
        )
    else:
        link.role = payload.role
    await db.commit()
    return await _detail(db, opportunity_id)


@router.delete(
    "/{opportunity_id}/contacts/{contact_id}", response_model=OpportunityDetail
)
async def unlink_contact(
    opportunity_id: int,
    contact_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get(db, opportunity_id)
    link = await db.get(SalesOpportunityContact, (opportunity_id, contact_id))
    if link is not None:
        await db.delete(link)
        if opp.primary_contact_id == contact_id:
            opp.primary_contact_id = None
        await db.commit()
    return await _detail(db, opportunity_id)


# ── Mapa decyzyjna ────────────────────────────────────────────────────────


async def _get_locked(db: AsyncSession, opportunity_id: int) -> SalesOpportunity:
    """Zapis to odczyt listy z JSON-a, zmiana i nadpisanie: bez blokady wiersza
    jeden z dwóch równoległych zapisów by przepadł."""

    opp = await db.scalar(
        select(SalesOpportunity)
        .where(SalesOpportunity.id == opportunity_id)
        .with_for_update()
    )
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return opp


def _person_index(entries: list[dict[str, Any]], key: str) -> int:
    keys = entry_keys(entries)
    if key not in keys:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=DECISION_PERSON_STALE)
    return keys.index(key)


def _record_decision_map(
    db: AsyncSession,
    opportunity_id: int,
    user_id: int,
    *,
    field: str = "decision_map",
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    history.record(
        db,
        opportunity_id=opportunity_id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=field,
        old_value=old_value,
        new_value=new_value,
    )


async def _fill_person_contact(
    db: AsyncSession,
    opp: SalesOpportunity,
    entry: dict[str, Any],
    fields: list[str],
    user_id: int,
) -> None:
    filled = await decision_map.fill_contact(db, opp.company_id, entry, fields)
    if filled:
        _record_decision_map(
            db,
            opp.id,
            user_id,
            field="decision_map_contact",
            new_value=f"{entry.get('name')}: {', '.join(filled)}",
        )


@router.post(
    "/{opportunity_id}/decision-map",
    response_model=OpportunityDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_decision_person(
    opportunity_id: int,
    payload: decision_map.DecisionPersonCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get_locked(db, opportunity_id)
    if not await _decision_map_enabled(db, opp):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Mapa decyzyjna jest tylko w lejku Fabryki IT.",
        )
    entry = payload.model_dump(mode="json")
    entries = [*decision_map.decision_entries(opp.custom_fields), entry]
    opp.custom_fields = decision_map.with_entries(
        opp.custom_fields,
        entries,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    _record_decision_map(
        db,
        opp.id,
        current_user.id,
        new_value=decision_map.describe_person(entry),
    )
    await _fill_person_contact(db, opp, entry, list(entry), current_user.id)
    await db.commit()
    return await _detail(db, opportunity_id)


@router.patch(
    "/{opportunity_id}/decision-map/{person_key}", response_model=OpportunityDetail
)
async def update_decision_person(
    opportunity_id: int,
    person_key: str,
    payload: decision_map.DecisionPersonUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get_locked(db, opportunity_id)
    entries = decision_map.decision_entries(opp.custom_fields)
    index = _person_index(entries, person_key)
    before = entries[index]
    fields = payload.model_dump(mode="json", exclude_unset=True)
    changed = [field for field, value in fields.items() if before.get(field) != value]
    if changed:
        # Klucze spoza formularza (``contact_id`` z Atlasa) zostają we wpisie.
        after = {**before, **fields}
        entries[index] = after
        opp.custom_fields = decision_map.with_entries(
            opp.custom_fields,
            entries,
            user_id=current_user.id,
            now=datetime.now(timezone.utc),
        )
        old_value, new_value = decision_map.describe_change(before, after, changed)
        _record_decision_map(
            db, opp.id, current_user.id, old_value=old_value, new_value=new_value
        )
        await _fill_person_contact(db, opp, after, changed, current_user.id)
        await db.commit()
    return await _detail(db, opportunity_id)


@router.delete(
    "/{opportunity_id}/decision-map/{person_key}", response_model=OpportunityDetail
)
async def remove_decision_person(
    opportunity_id: int,
    person_key: str,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    opp = await _get_locked(db, opportunity_id)
    entries = decision_map.decision_entries(opp.custom_fields)
    removed = entries.pop(_person_index(entries, person_key))
    opp.custom_fields = decision_map.with_entries(
        opp.custom_fields,
        entries,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    _record_decision_map(
        db,
        opp.id,
        current_user.id,
        old_value=decision_map.describe_person(removed),
    )
    await db.commit()
    return await _detail(db, opportunity_id)


# ── Zapis rozmowy ─────────────────────────────────────────────────────────


@router.post(
    "/{opportunity_id}/calls",
    response_model=OpportunityDetail,
    status_code=status.HTTP_201_CREATED,
)
async def log_call(
    opportunity_id: int,
    payload: calls.CallLogRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OpportunityDetail:
    """Wynik rozmowy jednym kliknięciem; krok zakłada osobno okno „Co dalej i kiedy”."""

    opp = await _get_locked(db, opportunity_id)
    await calls.log_call(
        db, opp, payload, user_id=current_user.id, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return await _detail(db, opportunity_id)


# ── Podsumowanie lejka ───────────────────────────────────────────────────


class SummaryStageRef(BaseModel):
    id: int
    name: str
    position: int


class SummaryOwnerOut(BaseModel):
    owner: Optional[Ref]
    open: int
    value: Decimal
    weighted: Decimal
    mrr: Decimal
    stale: int
    no_close: int


class SummaryStageOut(BaseModel):
    stage: SummaryStageRef
    count: int
    value: Decimal


class SummaryOut(BaseModel):
    pipeline: Ref
    open_count: int
    value: Decimal
    weighted: Decimal
    mrr: Decimal
    stale_count: int
    by_owner: list[SummaryOwnerOut]
    by_stage: list[SummaryStageOut]


@summary_router.get("", response_model=SummaryOut)
async def sales_summary(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    pipeline_id: Optional[int] = None,
    period: Period = "all",
) -> SummaryOut:
    """Otwarte szanse lejka w okresie zamknięcia: liczby per opiekun i etap."""

    if pipeline_id is not None:
        pipeline = await db.get(SalesPipeline, pipeline_id)
        if pipeline is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Nie ma takiego lejka."
            )
    else:
        pipeline = await _default_pipeline(db)
    summary = await build_summary(
        db,
        pipeline,
        period=period,
        today=business_today(),
        now=datetime.now(timezone.utc),
    )
    return SummaryOut(
        pipeline=Ref(id=summary.pipeline_id, name=summary.pipeline_name),
        open_count=summary.open_count,
        value=summary.value,
        weighted=summary.weighted,
        mrr=summary.mrr,
        stale_count=summary.stale_count,
        by_owner=[
            SummaryOwnerOut(
                owner=(
                    Ref(id=o.owner_id, name=o.owner_name or "")
                    if o.owner_id is not None
                    else None
                ),
                open=o.open,
                value=o.value,
                weighted=o.weighted,
                mrr=o.mrr,
                stale=o.stale,
                no_close=o.no_close,
            )
            for o in summary.by_owner
        ],
        by_stage=[
            SummaryStageOut(
                stage=SummaryStageRef(id=s.stage_id, name=s.name, position=s.position),
                count=s.count,
                value=s.value,
            )
            for s in summary.by_stage
        ],
    )
