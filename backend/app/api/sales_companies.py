"""Sprzedaż → Firmy: kartoteka firm sprzedaży (Atlas → NEXUS).

Prefiks ``/api/sales/companies`` (wpięty w ``app/main.py``). Odczyt wymaga
„Sprzedaż: podgląd”, każdy zapis „Sprzedaż: edycja” — bez osobnej sekcji
produktu, jak moduł „Ludzie” (decyzja Artura 26.10.2026: uprawnienia zamiast
roli „Handlowiec”). Edycja jest otwarta dla każdego z uprawnieniem, jak
w Atlasie; właściciel firmy to opiekun, nie blokada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.client import Client
from app.models.sales import SalesCompany
from app.models.user import User
from app.services import sales_schema as schema
from app.services.action_permissions import ProductAction
from app.services.company_names import normalize_company_name
from app.services.sales import companies as service

router = APIRouter()

SalesViewUser = Annotated[User, Depends(require_permission(ProductAction.sales_view))]
SalesEditUser = Annotated[User, Depends(require_permission(ProductAction.sales_edit))]

NOT_FOUND_DETAIL = "Nie ma takiej firmy w kartotece sprzedaży."
DUPLICATE_DETAIL = (
    "Ta firma jest już w kartotece sprzedaży (ten sam NIP albo nazwa). "
    "Otwórz istniejącą albo zapisz mimo to."
)

Lifecycle = Literal[schema.COMPANY_LIFECYCLES]  # type: ignore[valid-type]
CompanyStatusValue = Literal[schema.COMPANY_STATUSES]  # type: ignore[valid-type]
Tier = Literal[schema.COMPANY_TIERS]  # type: ignore[valid-type]


class PersonRef(BaseModel):
    id: int
    name: str


class CompanyRef(BaseModel):
    id: int
    name: str


class CompanyFields(BaseModel):
    legal_name: Optional[str] = Field(default=None, max_length=500)
    nip: Optional[str] = Field(default=None, max_length=20)
    krs: Optional[str] = Field(default=None, max_length=20)
    regon: Optional[str] = Field(default=None, max_length=14)
    domain: Optional[str] = Field(default=None, max_length=255)
    website_url: Optional[str] = Field(default=None, max_length=500)
    linkedin_url: Optional[str] = Field(default=None, max_length=500)
    industry: Optional[str] = Field(default=None, max_length=255)
    size_range: Optional[str] = Field(default=None, max_length=40)
    hq_city: Optional[str] = Field(default=None, max_length=120)
    hq_country: Optional[str] = Field(default=None, min_length=2, max_length=2)
    description: Optional[str] = Field(default=None, max_length=10_000)
    lifecycle_stage: Optional[Lifecycle] = None
    tier: Optional[Tier] = None
    status: Optional[CompanyStatusValue] = None
    tags: Optional[list[str]] = Field(default=None, max_length=30)
    source: Optional[str] = Field(default=None, max_length=60)
    parent_company_id: Optional[int] = None
    owner_user_id: Optional[int] = None


class CompanyCreate(CompanyFields):
    name: str = Field(min_length=1, max_length=500)
    #: Zapisz mimo ostrzeżenia o duplikacie (dwie spółki o tej samej nazwie).
    allow_duplicate: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj nazwę firmy.")
        return value


class CompanyUpdate(CompanyFields):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)


class CompanyOut(BaseModel):
    id: int
    name: str
    legal_name: Optional[str]
    nip: Optional[str]
    krs: Optional[str]
    regon: Optional[str]
    domain: Optional[str]
    website_url: Optional[str]
    linkedin_url: Optional[str]
    industry: Optional[str]
    size_range: Optional[str]
    hq_city: Optional[str]
    hq_country: Optional[str]
    description: Optional[str]
    lifecycle_stage: str
    tier: Optional[str]
    status: str
    tags: list[Any]
    source: Optional[str]
    parent: Optional[CompanyRef]
    client: Optional[CompanyRef]
    owner: Optional[PersonRef]
    open_opportunities: int
    open_value: Decimal
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class CompanyList(BaseModel):
    items: list[CompanyOut]
    total: int


class DuplicateOut(BaseModel):
    id: int
    name: str
    nip: Optional[str]


def _ref(id_: Optional[int], name: Optional[str]) -> Optional[CompanyRef]:
    return CompanyRef(id=id_, name=name or "") if id_ is not None else None


def _person(id_: Optional[int], name: Optional[str]) -> Optional[PersonRef]:
    return PersonRef(id=id_, name=name or "") if id_ is not None else None


def _out(row: Any) -> CompanyOut:
    company: SalesCompany = row.SalesCompany
    return CompanyOut(
        id=company.id,
        name=company.name,
        legal_name=company.legal_name,
        nip=company.nip,
        krs=company.krs,
        regon=company.regon,
        domain=company.domain,
        website_url=company.website_url,
        linkedin_url=company.linkedin_url,
        industry=company.industry,
        size_range=company.size_range,
        hq_city=company.hq_city,
        hq_country=company.hq_country,
        description=company.description,
        lifecycle_stage=company.lifecycle_stage,
        tier=company.tier,
        status=company.status,
        tags=list(company.tags or []),
        source=company.source,
        parent=_ref(company.parent_company_id, row.parent_name),
        client=_ref(company.client_id, row.client_name),
        owner=_person(company.owner_user_id, row.owner_name),
        open_opportunities=int(row.open_count or 0),
        open_value=Decimal(row.open_value or 0),
        archived_at=company.archived_at,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


def _base_query():
    parent = aliased(SalesCompany)
    owner = aliased(User)
    pipeline = service.open_pipeline_subquery()
    return (
        select(
            SalesCompany,
            parent.name.label("parent_name"),
            func.coalesce(Client.display_name, Client.name).label("client_name"),
            owner.name.label("owner_name"),
            pipeline.c.open_count,
            pipeline.c.open_value,
        )
        .outerjoin(parent, parent.id == SalesCompany.parent_company_id)
        .outerjoin(Client, Client.id == SalesCompany.client_id)
        .outerjoin(owner, owner.id == SalesCompany.owner_user_id)
        .outerjoin(pipeline, pipeline.c.company_id == SalesCompany.id)
    )


async def _load(db: AsyncSession, company_id: int) -> CompanyOut:
    row = (await db.execute(_base_query().where(SalesCompany.id == company_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return _out(row)


async def _check_links(
    db: AsyncSession, *, company_id: Optional[int], fields: dict[str, Any]
) -> None:
    parent_id = fields.get("parent_company_id")
    if parent_id is not None:
        if parent_id == company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Firma nie może być własną firmą matką.",
            )
        if await db.get(SalesCompany, parent_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nie ma takiej firmy matki w kartotece sprzedaży.",
            )
    owner_id = fields.get("owner_user_id")
    if owner_id is not None:
        owner = await db.get(User, owner_id)
        if owner is None or not owner.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Opiekun musi być aktywnym kontem w NEXUSIE.",
            )


def _apply(company: SalesCompany, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if key == "nip":
            value = service.nip_digits(value)
        elif key == "tags":
            value = value or []
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(company, key, value)
    if "name" in fields:
        company.normalized_name = normalize_company_name(company.name) or company.name


@router.get("", response_model=CompanyList)
async def list_companies(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, max_length=200),
    lifecycle: Optional[Lifecycle] = None,
    company_status: Optional[CompanyStatusValue] = Query(default=None, alias="status"),
    owner_id: Optional[int] = None,
    archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CompanyList:
    query = service.apply_search(_base_query(), q)
    query = query.where(
        SalesCompany.archived_at.is_not(None)
        if archived
        else SalesCompany.archived_at.is_(None)
    )
    if lifecycle:
        query = query.where(SalesCompany.lifecycle_stage == lifecycle)
    if company_status:
        query = query.where(SalesCompany.status == company_status)
    if owner_id is not None:
        query = query.where(SalesCompany.owner_user_id == owner_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(SalesCompany.name, SalesCompany.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CompanyList(items=[_out(row) for row in rows], total=int(total or 0))


@router.get("/duplicates", response_model=list[DuplicateOut])
async def company_duplicates(
    current_user: SalesViewUser,
    name: str = Query(min_length=1, max_length=500),
    nip: Optional[str] = Query(default=None, max_length=20),
    exclude_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> list[DuplicateOut]:
    """Podpowiedź w formularzu: czy taka firma już jest (przed zapisem)."""

    found = await service.find_duplicates(db, name=name, nip=nip, exclude_id=exclude_id)
    return [DuplicateOut(id=c.id, name=c.name, nip=c.nip) for c in found]


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    fields = payload.model_dump(exclude={"allow_duplicate"}, exclude_none=True)
    await _check_links(db, company_id=None, fields=fields)
    if not payload.allow_duplicate:
        found = await service.find_duplicates(db, name=payload.name, nip=payload.nip)
        if found:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "sales_company_duplicate",
                    "message": DUPLICATE_DETAIL,
                    "duplicates": [
                        DuplicateOut(id=c.id, name=c.name, nip=c.nip).model_dump()
                        for c in found
                    ],
                },
            )
    company = SalesCompany(
        name=payload.name,
        normalized_name="",
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    _apply(company, fields)
    db.add(company)
    await db.commit()
    return await _load(db, company.id)


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    return await _load(db, company_id)


@router.patch("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: int,
    payload: CompanyUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and not (fields["name"] or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Podaj nazwę firmy."
        )
    for required in ("lifecycle_stage", "status"):
        if required in fields and fields[required] is None:
            fields.pop(required)
    await _check_links(db, company_id=company_id, fields=fields)
    _apply(company, fields)
    await db.commit()
    return await _load(db, company_id)


@router.post("/{company_id}/archive", response_model=CompanyOut)
async def archive_company(
    company_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if company.archived_at is None:
        company.archived_at = datetime.now(timezone.utc)
        await db.commit()
    return await _load(db, company_id)


@router.post("/{company_id}/restore", response_model=CompanyOut)
async def restore_company(
    company_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if company.archived_at is not None:
        company.archived_at = None
        await db.commit()
    return await _load(db, company_id)
