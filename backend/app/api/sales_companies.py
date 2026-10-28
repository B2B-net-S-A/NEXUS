"""Sprzedaż → Firmy: kartoteka firm sprzedaży (Atlas → NEXUS).

Prefiks ``/api/sales/companies`` (wpięty w ``app/main.py``). Odczyt wymaga
„Sprzedaż: podgląd”, każdy zapis „Sprzedaż: edycja” — bez osobnej sekcji
produktu, jak moduł „Ludzie” (decyzja Artura 26.10.2026: uprawnienia zamiast
roli „Handlowiec”). Edycja jest otwarta dla każdego z uprawnieniem, jak
w Atlasie; właściciel firmy to opiekun, nie blokada.

Po imporcie z Atlasa: opiekun bez konta w NEXUSIE zostaje etykietą
(``owner_label``), którą admin przypisuje do konta (``/owner-labels/assign``);
duplikaty (ten sam NIP albo nazwa kanoniczna) scala ``/{id}/merge`` — źródłowa
firma trafia do archiwum, nigdy nie jest kasowana.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.sales_gates import (
    SalesEditUser,
    SalesViewUser,
    ensure_owner_or_admin,
    is_admin,
)
from app.core.database import get_db
from app.models.client import Client
from app.models.sales import SalesCompany, SalesOpportunity
from app.models.user import User
from app.services import sales_schema as schema
from app.services.b2b_contract_generator.registry_lookup import lookup_company
from app.services.company_names import normalize_company_name
from app.services.sales import companies as service
from app.services.sales.atlas_import import ATLAS_REVIEW_TAG
from app.services.sales.merge import merge_companies

router = APIRouter()


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

    @field_validator("website_url", "linkedin_url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        return service.http_url(value)


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
    #: Opiekun z Atlasa bez konta w NEXUSIE — do przypisania na konto.
    owner_label: Optional[str]
    #: Tag „atlas: do przejrzenia” — firma przeszła import warunkowo.
    needs_review: bool
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


class DuplicateGroupCompany(BaseModel):
    id: int
    name: str
    nip: Optional[str]
    open_opportunities: int


class DuplicateGroupOut(BaseModel):
    key: str
    reason: Literal["nip", "name"]
    companies: list[DuplicateGroupCompany]


class OwnerLabelOut(BaseModel):
    label: str
    companies: int


class OwnerLabelAssign(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    owner_user_id: int


class OwnerLabelAssigned(BaseModel):
    companies: int
    opportunities: int


class MergeRequest(BaseModel):
    source_id: int


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
        owner_label=company.owner_label,
        needs_review=ATLAS_REVIEW_TAG in (company.tags or []),
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
    if fields.get("owner_user_id") is not None:
        # Opiekun z konta zastępuje etykietę opiekuna z Atlasa.
        company.owner_label = None
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
    owner_label: Optional[str] = Query(default=None, max_length=120),
    review: bool = False,
    tag: Optional[str] = Query(default=None, max_length=120),
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
    if owner_label:
        query = query.where(SalesCompany.owner_label == owner_label)
    if review:
        query = query.where(SalesCompany.tags.contains([ATLAS_REVIEW_TAG]))
    if tag:
        query = query.where(SalesCompany.tags.contains([tag]))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(SalesCompany.name, SalesCompany.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CompanyList(items=[_out(row) for row in rows], total=int(total or 0))


class RegistryOut(BaseModel):
    name: Optional[str]
    nip: Optional[str]
    regon: Optional[str]
    krs: Optional[str]
    address: Optional[str]
    hq_city: Optional[str]
    source: Optional[str]


_POSTAL_CITY = re.compile(r"\b\d{2}-\d{3}\s+(.+)$")


def city_from_address(address: Optional[str]) -> Optional[str]:
    """„ul. Prosta 18, 00-850 Warszawa” → „Warszawa” (miasto po kodzie pocztowym)."""

    match = _POSTAL_CITY.search((address or "").strip())
    return match.group(1).strip().title() if match else None


@router.get("/registry", response_model=RegistryOut)
async def registry_lookup(
    current_user: SalesEditUser,
    nip: str = Query(min_length=10, max_length=20),
) -> RegistryOut:
    """„Pobierz z rejestru” w formularzu firmy — ten sam łańcuch co Generator umów
    (biznes.gov.pl / CEIDG, Biała Lista MF, KRS), zamiast kopii z Atlasa."""

    digits = service.nip_digits(nip) or ""
    if len(digits) != 10:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="NIP ma 10 cyfr."
        )
    found = await lookup_company(nip=digits)
    if not found or not found.get("name"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Nie znaleźliśmy tego NIP-u w rejestrach — wpisz dane ręcznie.",
        )
    address = found.get("address")
    return RegistryOut(
        name=found.get("name"),
        nip=digits,
        regon=found.get("regon"),
        krs=found.get("krs"),
        address=address,
        hq_city=city_from_address(address),
        source=found.get("source"),
    )


@router.get(
    "/duplicates",
    response_model=Union[list[DuplicateOut], list[DuplicateGroupOut]],
)
async def company_duplicates(
    current_user: SalesViewUser,
    name: Optional[str] = Query(default=None, min_length=1, max_length=500),
    nip: Optional[str] = Query(default=None, max_length=20),
    exclude_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> Union[list[DuplicateOut], list[DuplicateGroupOut]]:
    """Z ``name``: podpowiedź w formularzu, czy taka firma już jest (przed zapisem).

    Bez ``name``: grupy niezarchiwizowanych firm o tym samym NIP-ie albo nazwie
    kanonicznej — lista do scalania po imporcie z Atlasa (do 100 grup).
    """

    if name is not None:
        found = await service.find_duplicates(
            db, name=name, nip=nip, exclude_id=exclude_id
        )
        return [DuplicateOut(id=c.id, name=c.name, nip=c.nip) for c in found]
    return await _duplicate_groups(db)


async def _duplicate_groups(db: AsyncSession) -> list[DuplicateGroupOut]:
    pipeline = service.open_pipeline_subquery()
    active = SalesCompany.archived_at.is_(None)
    groups: list[DuplicateGroupOut] = []
    seen: set[frozenset[int]] = set()
    for reason, column in (
        ("nip", SalesCompany.nip),
        ("name", SalesCompany.normalized_name),
    ):
        keys = (
            select(column)
            .where(active, column.is_not(None), column != "")
            .group_by(column)
            .having(func.count() > 1)
            .order_by(column)
            .limit(100)
        )
        rows = (
            await db.execute(
                select(
                    column.label("key"),
                    SalesCompany.id,
                    SalesCompany.name,
                    SalesCompany.nip,
                    pipeline.c.open_count,
                )
                .outerjoin(pipeline, pipeline.c.company_id == SalesCompany.id)
                .where(active, column.in_(keys))
                .order_by(column, SalesCompany.id)
            )
        ).all()
        by_key: dict[str, list[DuplicateGroupCompany]] = {}
        for row in rows:
            by_key.setdefault(row.key, []).append(
                DuplicateGroupCompany(
                    id=row.id,
                    name=row.name,
                    nip=row.nip,
                    open_opportunities=int(row.open_count or 0),
                )
            )
        for key, companies in by_key.items():
            ids = frozenset(c.id for c in companies)
            if ids in seen:
                # Ten sam NIP i ta sama nazwa — jedna grupa wystarczy.
                continue
            seen.add(ids)
            groups.append(
                DuplicateGroupOut(key=key, reason=reason, companies=companies)
            )
    return groups[:100]


@router.get("/owner-labels", response_model=list[OwnerLabelOut])
async def owner_labels(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[OwnerLabelOut]:
    """Opiekunowie z Atlasa bez konta w NEXUSIE i liczba ich firm bez opiekuna."""

    count = func.count(SalesCompany.id)
    rows = (
        await db.execute(
            select(SalesCompany.owner_label, count)
            .where(
                SalesCompany.owner_user_id.is_(None),
                SalesCompany.owner_label.is_not(None),
            )
            .group_by(SalesCompany.owner_label)
            .order_by(count.desc(), SalesCompany.owner_label)
        )
    ).all()
    return [OwnerLabelOut(label=label, companies=int(n)) for label, n in rows]


@router.post("/owner-labels/assign", response_model=OwnerLabelAssigned)
async def assign_owner_label(
    payload: OwnerLabelAssign,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> OwnerLabelAssigned:
    """Admin przypisuje opiekuna z Atlasa do konta: jego firmy i ich szanse bez opiekuna."""

    if not is_admin(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Opiekunów z Atlasa przypisuje do kont administrator.",
        )
    owner = await db.get(User, payload.owner_user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Opiekun musi być aktywnym kontem w NEXUSIE.",
        )
    company_ids = list(
        (
            await db.execute(
                update(SalesCompany)
                .where(
                    SalesCompany.owner_label == payload.label,
                    SalesCompany.owner_user_id.is_(None),
                )
                .values(owner_user_id=owner.id, owner_label=None)
                .returning(SalesCompany.id)
            )
        ).scalars()
    )
    opportunities = 0
    if company_ids:
        opportunities = len(
            (
                await db.execute(
                    update(SalesOpportunity)
                    .where(
                        SalesOpportunity.company_id.in_(company_ids),
                        SalesOpportunity.owner_user_id.is_(None),
                    )
                    .values(owner_user_id=owner.id)
                    .returning(SalesOpportunity.id)
                )
            ).all()
        )
    await db.commit()
    return OwnerLabelAssigned(companies=len(company_ids), opportunities=opportunities)


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
    if "owner_user_id" in fields and fields["owner_user_id"] != company.owner_user_id:
        ensure_owner_or_admin(current_user, company.owner_user_id)
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


@router.post("/{company_id}/merge", response_model=CompanyOut)
async def merge_company(
    company_id: int,
    payload: MergeRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    """Scal duplikat (``source_id``) w tę firmę; źródłowa trafia do archiwum."""

    if payload.source_id == company_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wybierz inną firmę do scalenia.",
        )
    target = await db.get(SalesCompany, company_id)
    source = await db.get(SalesCompany, payload.source_id)
    if target is None or source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if target.archived_at is not None or source.archived_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Scalać można tylko firmy, które nie są w archiwum.",
        )
    # Scalenie zmienia opiekuna rekordów źródłowej — jak zmiana opiekuna.
    ensure_owner_or_admin(current_user, target.owner_user_id)
    ensure_owner_or_admin(current_user, source.owner_user_id)
    await merge_companies(
        db, target=target, source=source, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return await _load(db, company_id)
