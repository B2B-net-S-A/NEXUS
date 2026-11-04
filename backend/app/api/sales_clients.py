"""Sprzedaż ↔ Klienci: powiązanie firmy sprzedaży z klientem NEXUSA (decyzja 27.10.2026).

Po wygranej handlowiec wskazuje klienta NEXUSA, z którym firma sprzedaży jest
tą samą firmą — bez zakładania klienta, przypisywania DL i rekrutacji (to
zostaje w Delivery, jak dziś). Prefiks ``/api/sales/clients``:

* ``GET /options?q=`` — klienci do wyboru: tylko id i nazwa (handlowiec nie
  ma „Klienci, kontrakty i zamówienia: podgląd”, więc nic ponad nazwę),
* ``PUT /link/{company_id}`` — ustaw albo zdejmij powiązanie (jeden klient =
  jedna firma sprzedaży, ``ux_sales_companies_client``),
* ``GET /{client_id}/summary`` — zakładka „Sprzedaż” w karcie klienta.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.models.client import Client
from app.models.sales import SalesCompany, SalesOpportunity, SalesPipelineStage
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.company_names import normalize_company_name
from app.services.polish_ilike import polish_folded_ilike

router = APIRouter()


class ClientOption(BaseModel):
    id: int
    name: str


class LinkRequest(BaseModel):
    client_id: Optional[int] = None


class SummaryOpportunity(BaseModel):
    id: int
    title: str
    stage: str
    status: str
    value: Optional[Decimal]
    currency: str
    won_at: Optional[datetime]
    updated_at: datetime


class ClientSalesSummary(BaseModel):
    company: Optional[ClientOption]
    opportunities: list[SummaryOpportunity]


@router.get("/options", response_model=list[ClientOption])
async def client_options(
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(min_length=2, max_length=200),
) -> list[ClientOption]:
    display = client_display_name_expression()
    # Nazwa w Sprzedaży często ma formę prawną („mBank S.A.”), a klient w NEXUSIE
    # nie („mBank”) — szukamy też po nazwie kanonicznej, bez formy prawnej.
    term = q.strip()
    canonical = normalize_company_name(term)
    matches = [polish_folded_ilike(display, term)]
    if canonical and canonical != term.lower():
        matches.append(polish_folded_ilike(display, canonical))
    rows = (
        await db.execute(
            select(Client.id, display.label("display"))
            .where(*visible_client_predicates(), or_(*matches))
            .order_by(display)
            .limit(20)
        )
    ).all()
    return [ClientOption(id=row.id, name=row.display) for row in rows]


@router.put("/link/{company_id}", response_model=ClientOption | None)
async def link_client(
    company_id: int,
    payload: LinkRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> Optional[ClientOption]:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Nie ma takiej firmy w kartotece sprzedaży.",
        )
    if payload.client_id is None:
        company.client_id = None
        await db.commit()
        return None
    client = (
        await db.execute(
            select(Client.id, client_display_name_expression().label("display")).where(
                Client.id == payload.client_id, *visible_client_predicates()
            )
        )
    ).first()
    if client is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nie ma takiego klienta w NEXUSIE.",
        )
    taken = (
        await db.execute(
            select(SalesCompany.name).where(
                SalesCompany.client_id == client.id, SalesCompany.id != company_id
            )
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Ten klient jest już powiązany z firmą „{taken}” w kartotece sprzedaży.",
        )
    company.client_id = client.id
    if company.lifecycle_stage in ("lead", "prospect", "opportunity"):
        company.lifecycle_stage = "customer"
    await db.commit()
    return ClientOption(id=client.id, name=client.display)


@router.get("/{client_id}/summary", response_model=ClientSalesSummary)
async def client_sales_summary(
    client_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> ClientSalesSummary:
    company = (
        await db.execute(
            select(SalesCompany).where(SalesCompany.client_id == client_id)
        )
    ).scalar_one_or_none()
    if company is None:
        return ClientSalesSummary(company=None, opportunities=[])
    rows = (
        await db.execute(
            select(SalesOpportunity, SalesPipelineStage.name)
            .join(
                SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
            )
            .where(
                SalesOpportunity.company_id == company.id,
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.updated_at.desc())
        )
    ).all()
    return ClientSalesSummary(
        company=ClientOption(id=company.id, name=company.name),
        opportunities=[
            SummaryOpportunity(
                id=opp.id,
                title=opp.title,
                stage=stage,
                status=opp.status,
                value=opp.value,
                currency=opp.currency,
                won_at=opp.won_at,
                updated_at=opp.updated_at,
            )
            for opp, stage in rows
        ],
    )
