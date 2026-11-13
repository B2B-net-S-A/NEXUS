"""Sprzedaż → Leady: skrzynka sygnałów (makieta M4).

Prefiks ``/api/sales/leads`` (wpięty w ``app/main.py``). Odczyt: „Sprzedaż:
podgląd”, zapis: „Sprzedaż: edycja”. Lead zamienia się w szansę przy firmie
z kartoteki sprzedaży (istniejącej po nazwie kanonicznej albo nowej).
Lead z firmy, która jest już klientem NEXUSA, nie powstaje — popyt
u klientów idzie do DL (decyzja Artura 22.10.2026).

„Warto wrócić” (G-E, 12.11.2026): leady z bota z ``payload.origin = "winback"``
filtruje ``origin``; „Przejmij” (``/take-over``) daje lead zalogowanej osobie
tylko, gdy przypisanej osoby nie ma albo nie pracuje ona w Sprzedaży.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesCompany, SalesLead, SalesOpportunity
from app.models.user import User
from app.services import sales_schema as schema
from app.services.effective_access import resolve_effective_access
from app.services.company_names import normalize_company_name
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import company_dates
from app.services.sales import leads as service
from app.services.sales import bot_tasks, signals
from app.services.sales.lead_dossier import LeadDossier, dossiers
from app.services.sales.companies import http_url
from app.services.sales.offers import works_in_sales

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiego leada."
DECIDED_DETAIL = "Ten lead jest już rozpatrzony."
ASSIGNED_DETAIL = (
    "Ten lead ma osobę, która pracuje w Sprzedaży. Przejąć można tylko lead "
    "bez opiekuna albo po osobie spoza Sprzedaży."
)

Source = Literal[schema.LEAD_SOURCES]  # type: ignore[valid-type]
Status = Literal[schema.LEAD_STATUSES]  # type: ignore[valid-type]


class LeadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    company_name: str = Field(min_length=1, max_length=500)
    summary: Optional[str] = Field(default=None, max_length=10_000)
    url: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        return http_url(value)

    @field_validator("title", "company_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Pole nie może być puste.")
        return value


class LeadUpdate(BaseModel):
    status: Optional[Literal["new", "contacted", "dismissed"]] = None
    dismissed_reason: Optional[str] = Field(default=None, max_length=255)


class ConvertRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)


class Ref(BaseModel):
    id: int
    name: str


class LeadOut(BaseModel):
    id: int
    source: str
    status: str
    title: str
    summary: Optional[str]
    company_name: Optional[str]
    company_id: Optional[int]
    url: Optional[str]
    score: int
    signal_at: Optional[datetime]
    opportunity_id: Optional[int]
    dismissed_reason: Optional[str]
    created_at: datetime
    #: Surowe dane sygnału (z Atlasa: ogłoszenie, źródło, uzasadnienie wyniku).
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Osoba przypisana i czy pracuje w Sprzedaży (aktywna, z uprawnieniem Sprzedaży).
    assignee: Optional[Ref] = None
    assignee_in_sales: bool = False
    #: Teczka firmy leada (karta, kogo znamy, decydenci, punkty); brak danych = ``null``.
    dossier: Optional[LeadDossier] = None


class LeadList(BaseModel):
    items: list[LeadOut]
    total: int
    counts: dict[str, int]
    #: Kanał sygnałów z bota researchu włączony (``SALES_SIGNALS_ENABLED``).
    signals_enabled: bool = False
    #: Zadania bota poza sygnałami („Warto wrócić”, „Nowe centra IT”).
    bot_tasks_enabled: bool = False


async def _outs(db: AsyncSession, leads: list[SalesLead]) -> list[LeadOut]:
    """Leady z osobą przypisaną i teczką firmy; po jednym zapytaniu na całą listę."""

    ids = sorted({lead.assignee_user_id for lead in leads if lead.assignee_user_id})
    users: dict[int, User] = {}
    if ids:
        users = {
            user.id: user
            for user in (await db.scalars(select(User).where(User.id.in_(ids)))).all()
        }
        await resolve_effective_access(db, list(users.values()))
    files = await dossiers(db, (lead.company_id for lead in leads if lead.company_id))
    out = []
    for lead in leads:
        item = LeadOut.model_validate(lead, from_attributes=True)
        user = users.get(lead.assignee_user_id or 0)
        if user is not None:
            item.assignee = Ref(id=user.id, name=user.name or user.email)
            item.assignee_in_sales = works_in_sales(user)
        item.dossier = files.get(lead.company_id or 0)
        out.append(item)
    return out


async def _out(db: AsyncSession, lead: SalesLead) -> LeadOut:
    return (await _outs(db, [lead]))[0]


async def _get(db: AsyncSession, lead_id: int) -> SalesLead:
    lead = await db.get(SalesLead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return lead


@router.get("", response_model=LeadList)
async def list_leads(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    source: Optional[Source] = None,
    lead_status: Optional[Status] = Query(default="new", alias="status"),
    q: Optional[str] = Query(default=None, max_length=200),
    company_id: Optional[int] = Query(default=None, ge=1),
    #: Pochodzenie leada z bota (``payload.origin``): ``grok`` sygnały, ``winback``.
    origin: Optional[str] = Query(default=None, pattern=r"^[a-z_]{1,32}$"),
    #: Skrzynka sygnałów grupuje po stronie ekranu: wszystkie statusy naraz.
    all_statuses: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> LeadList:
    query = select(SalesLead)
    if source:
        query = query.where(SalesLead.source == source)
    if company_id is not None:
        query = query.where(SalesLead.company_id == company_id)
    if origin:
        query = query.where(SalesLead.payload["origin"].astext == origin)
    text = (q or "").strip()
    if text:
        query = query.where(
            polish_folded_ilike(func.coalesce(SalesLead.company_name, ""), text)
            | polish_folded_ilike(SalesLead.title, text)
        )
    counts = dict(
        (
            await db.execute(
                query.with_only_columns(SalesLead.status, func.count())
                .group_by(SalesLead.status)
                .order_by(None)
            )
        ).all()
    )
    if lead_status and not all_statuses:
        query = query.where(SalesLead.status == lead_status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(
                SalesLead.score.desc(),
                SalesLead.signal_at.desc().nulls_last(),
                SalesLead.id.desc(),
            ).limit(limit)
        )
    ).scalars()
    return LeadList(
        items=await _outs(db, list(rows)),
        total=int(total or 0),
        counts={key: int(counts.get(key, 0)) for key in schema.LEAD_STATUSES},
        signals_enabled=signals.enabled(),
        bot_tasks_enabled=bot_tasks.enabled(),
    )


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    if await service.is_existing_client(db, payload.company_name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Ta firma jest już klientem NEXUSA — potrzebę u klienta przekaż "
                "jego Delivery Leadowi, nie do sprzedaży."
            ),
        )
    fingerprint = (
        "manual|"
        + hashlib.sha256(
            f"{normalize_company_name(payload.company_name)}|{payload.title.lower()}".encode()
        ).hexdigest()[:48]
    )
    existing = (
        await db.execute(select(SalesLead).where(SalesLead.fingerprint == fingerprint))
    ).scalar_one_or_none()
    if existing is not None:
        return await _out(db, existing)
    lead = SalesLead(
        source="manual",
        title=payload.title,
        company_name=payload.company_name,
        summary=(payload.summary or "").strip() or None,
        url=(payload.url or "").strip() or None,
        signal_at=datetime.now(timezone.utc),
        fingerprint=fingerprint,
        assignee_user_id=current_user.id,
        company_id=await service.match_company(db, payload.company_name),
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return await _out(db, lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    lead = await _get(db, lead_id)
    if lead.status == "converted":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ten lead jest już szansą — zmieniaj szansę.",
        )
    if payload.status:
        lead.status = payload.status
        lead.dismissed_reason = (
            (payload.dismissed_reason or "").strip() or None
            if payload.status == "dismissed"
            else None
        )
    await db.commit()
    await db.refresh(lead)
    return await _out(db, lead)


@router.post("/{lead_id}/convert", response_model=dict[str, Any])
async def convert_lead(
    lead_id: int,
    payload: ConvertRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Utwórz szansę”: firma (istniejąca albo nowa) + szansa na pierwszym etapie."""

    lead = await _get(db, lead_id)
    if lead.status == "converted" and lead.opportunity_id:
        return {"opportunity_id": lead.opportunity_id, "company_id": lead.company_id}
    opportunity: SalesOpportunity = await service.convert(
        db, lead, owner_user_id=current_user.id, title=payload.title
    )
    await db.commit()
    # D3: pierwsza szansa w firmie odpala daty osób z tej firmy (jak przy
    # zakładaniu szansy z formularza).
    company = await db.get(SalesCompany, opportunity.company_id)
    if company is not None and company_dates.needs_run(
        company.dates_backfill, now=datetime.now(timezone.utc)
    ):
        company_dates.schedule_company_dates(company.id)
    return {"opportunity_id": opportunity.id, "company_id": opportunity.company_id}


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    return await _out(db, await _get(db, lead_id))


@router.post("/{lead_id}/take-over", response_model=LeadOut)
async def take_over_lead(
    lead_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    """„Przejmij”: lead bez osoby w Sprzedaży przechodzi na zalogowaną osobę."""

    lead = await db.get(SalesLead, lead_id, with_for_update=True)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if lead.status not in ("new", "contacted"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=DECIDED_DETAIL)
    previous_id = lead.assignee_user_id
    if previous_id is not None and previous_id != current_user.id:
        previous = await db.get(User, previous_id)
        if previous is not None:
            await resolve_effective_access(db, [previous])
            if works_in_sales(previous):
                raise HTTPException(status.HTTP_409_CONFLICT, detail=ASSIGNED_DETAIL)
    lead.assignee_user_id = current_user.id
    await db.commit()
    await db.refresh(lead)
    return await _out(db, lead)
