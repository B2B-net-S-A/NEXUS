"""Sprzedaż → Lejki i szanse (Atlas → NEXUS).

Prefiksy ``/api/sales/pipelines`` i ``/api/sales/opportunities`` (wpięte
w ``app/main.py``). Odczyt: „Sprzedaż: podgląd”, zapis: „Sprzedaż: edycja”;
zmianę opiekuna robi obecny opiekun albo admin. Ruch szansy po etapach idzie
wyłącznie przez ``POST /{id}/move`` — reguły cyklu życia są w
``services/sales/lifecycle.py``.
"""

from __future__ import annotations

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
from app.models.sales import (
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import company_dates
from app.services.sales.lifecycle import apply_stage, deal_value

pipelines_router = APIRouter()
router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiej szansy."
COMPANY_MISSING_DETAIL = "Wybierz firmę z kartoteki sprzedaży."
STAGE_MISMATCH_DETAIL = "Ten etap nie należy do lejka tej szansy."

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
    keep_open_until: Optional[date]
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class OpportunityDetail(OpportunityOut):
    contacts: list[OpportunityContactOut]


class OpportunityList(BaseModel):
    items: list[OpportunityOut]
    total: int


def _weighted(opportunity: SalesOpportunity) -> Optional[Decimal]:
    if opportunity.value is None:
        return None
    return (opportunity.value * opportunity.probability / 100).quantize(Decimal("0.01"))


def _out(row: Any) -> OpportunityOut:
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
        keep_open_until=opp.keep_open_until,
        archived_at=opp.archived_at,
        created_at=opp.created_at,
        updated_at=opp.updated_at,
    )


def _base_query():
    owner = aliased(User)
    return (
        select(
            SalesOpportunity,
            SalesPipelineStage,
            SalesCompany.name.label("company_name"),
            owner.name.label("owner_name"),
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


async def _detail(db: AsyncSession, opportunity_id: int) -> OpportunityDetail:
    row = (
        await db.execute(_base_query().where(SalesOpportunity.id == opportunity_id))
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
    return OpportunityDetail(
        **_out(row).model_dump(),
        contacts=[
            OpportunityContactOut(
                id=contact.id,
                full_name=contact.full_name,
                title=contact.title,
                email=contact.email,
                phone=contact.phone or contact.mobile_phone,
                role=role,
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


@router.get("", response_model=OpportunityList)
async def list_opportunities(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    pipeline_id: Optional[int] = None,
    company_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    opportunity_status: Optional[StatusValue] = Query(default=None, alias="status"),
    q: Optional[str] = Query(default=None, max_length=200),
    archived: bool = False,
    # Atlas ma ~1,5 tys. szans — tablica wczytuje cały lejek naraz.
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> OpportunityList:
    query = _base_query().where(
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
    text = (q or "").strip()
    if text:
        query = query.where(
            or_(
                polish_folded_ilike(SalesOpportunity.title, text),
                polish_folded_ilike(SalesCompany.name, text),
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(
                SalesOpportunity.updated_at.desc(), SalesOpportunity.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return OpportunityList(items=[_out(row) for row in rows], total=int(total or 0))


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
    _apply(opp, fields)
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
    if stage.id != opp.stage_id:
        apply_stage(opp, stage, stages, now=datetime.now(timezone.utc))
    if stage.outcome == "lost":
        reason = (payload.lost_reason or "").strip()
        if reason:
            opp.lost_reason = reason
    else:
        opp.lost_reason = None
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
        await db.commit()
    return await _detail(db, opportunity_id)


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
