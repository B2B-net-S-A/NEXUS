"""Sprzedaż → Leady: skrzynka sygnałów (makieta M4).

Prefiks ``/api/sales/leads`` (wpięty w ``app/main.py``). Odczyt: „Sprzedaż:
podgląd”, zapis: „Sprzedaż: edycja”. Lead zamienia się w szansę przy firmie
z kartoteki sprzedaży (istniejącej po nazwie kanonicznej albo nowej).
Lead z firmy, która jest już klientem NEXUSA, nie powstaje — popyt
u klientów idzie do DL (decyzja Artura 22.10.2026).
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
from app.services import sales_schema as schema
from app.services.company_names import normalize_company_name
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import company_dates
from app.services.sales import leads as service
from app.services.sales.companies import http_url

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiego leada."

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


class LeadList(BaseModel):
    items: list[LeadOut]
    total: int
    counts: dict[str, int]


def _out(lead: SalesLead) -> LeadOut:
    return LeadOut.model_validate(lead, from_attributes=True)


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
    limit: int = Query(default=100, ge=1, le=500),
) -> LeadList:
    query = select(SalesLead)
    if source:
        query = query.where(SalesLead.source == source)
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
    if lead_status:
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
        items=[_out(lead) for lead in rows],
        total=int(total or 0),
        counts={key: int(counts.get(key, 0)) for key in schema.LEAD_STATUSES},
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
        return _out(existing)
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
    return _out(lead)


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
    return _out(lead)


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
    return _out(await _get(db, lead_id))
