"""Sprzedaż → Oferty: sekcje „W toku” i „Do decyzji” oraz „Przejmij”.

Prefiks ``/api/sales`` (wpięte w ``app/main.py``): ``GET /offers`` za „Sprzedaż: podgląd”,
``POST /opportunities/{id}/take-over`` za „Sprzedaż: edycja”. Zasady sekcji są w
``services/sales/offers.py``. „Odłóż do…” to zwykły ``PATCH`` szansy z ``keep_open_until``,
a „Zamknij z powodem” to ``POST /opportunities/{id}/move`` na etap przegranej.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesOpportunity
from app.services.sales import offers

router = APIRouter()


class Ref(BaseModel):
    id: int
    name: str


class StageRef(BaseModel):
    id: int
    key: str
    name: str


class OfferStepOut(BaseModel):
    #: Zadanie albo telefon do odhaczenia; spotkanie z kalendarza go nie ma.
    activity_id: Optional[int]
    kind: str
    at: datetime
    subject: Optional[str]
    overdue: bool


class OfferRowOut(BaseModel):
    id: int
    title: str
    company: Ref
    pipeline_id: int
    pipeline_name: str
    stage: StageRef
    #: Fałsz: szansa z innego etapu, która jest tu tylko dlatego, że nie ma opiekuna.
    is_offer: bool
    owner: Optional[Ref]
    owner_in_sales: bool
    mrr_value: Optional[Decimal]
    currency: str
    idle_since: datetime
    idle_days: int
    expected_close_date: Optional[date]
    close_overdue: bool
    keep_open_until: Optional[date]
    postponed: bool
    section: offers.Section
    reason: Optional[offers.Reason]
    step: Optional[OfferStepOut]


class SectionTotalsOut(BaseModel):
    count: int
    mrr: Decimal


class ScopeTotalsOut(BaseModel):
    in_progress: SectionTotalsOut
    to_decide: SectionTotalsOut


class OffersOut(BaseModel):
    #: Zakres, który serwer zastosował (bez parametru wybiera go sam).
    scope: offers.Scope
    items: list[OfferRowOut]
    totals: dict[offers.Scope, ScopeTotalsOut]


class TakeOverOut(BaseModel):
    id: int
    owner: Ref


def _row_out(row: offers.OfferRow) -> OfferRowOut:
    opp = row.opportunity
    return OfferRowOut(
        id=opp.id,
        title=opp.title,
        company=Ref(id=opp.company_id, name=row.company_name),
        pipeline_id=opp.pipeline_id,
        pipeline_name=row.pipeline_name,
        stage=StageRef(id=row.stage.id, key=row.stage.key, name=row.stage.name),
        is_offer=row.is_offer,
        owner=(
            Ref(id=opp.owner_user_id, name=row.owner_name or "")
            if opp.owner_user_id is not None
            else None
        ),
        owner_in_sales=row.owner_in_sales,
        mrr_value=opp.mrr_value,
        currency=opp.currency,
        idle_since=row.idle_since,
        idle_days=row.idle_days,
        expected_close_date=opp.expected_close_date,
        close_overdue=row.close_overdue,
        keep_open_until=opp.keep_open_until,
        postponed=row.postponed,
        section=row.section,
        reason=row.reason,
        step=(
            OfferStepOut(
                activity_id=row.step.activity_id,
                kind=row.step.kind,
                at=row.step.at,
                subject=row.step.subject,
                overdue=row.step_overdue,
            )
            if row.step is not None
            else None
        ),
    )


@router.get("/offers", response_model=OffersOut)
async def list_offers(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Optional[offers.Scope] = None,
    q: Optional[str] = Query(default=None, max_length=200),
) -> OffersOut:
    result = await offers.load_offers(
        db, current_user, scope=scope, q=q, now=datetime.now(timezone.utc)
    )
    return OffersOut(
        scope=result.scope,
        items=[_row_out(row) for row in result.rows],
        totals={
            name: ScopeTotalsOut(
                in_progress=SectionTotalsOut(
                    count=sections["in_progress"].count, mrr=sections["in_progress"].mrr
                ),
                to_decide=SectionTotalsOut(
                    count=sections["to_decide"].count, mrr=sections["to_decide"].mrr
                ),
            )
            for name, sections in result.totals.items()
        },
    )


@router.post("/opportunities/{opportunity_id}/take-over", response_model=TakeOverOut)
async def take_over_opportunity(
    opportunity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> TakeOverOut:
    """„Przejmij”: klikający zostaje opiekunem szansy, której nikt ze Sprzedaży nie prowadzi."""

    # Blokada wiersza: dwie osoby klikające naraz nie przejmą tej samej szansy.
    opp = await db.scalar(
        select(SalesOpportunity)
        .where(SalesOpportunity.id == opportunity_id)
        .with_for_update()
    )
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie ma takiej szansy.")
    try:
        await offers.take_over(db, opp, current_user)
    except offers.TakeOverRefused as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=refused.detail) from None
    await db.commit()
    return TakeOverOut(id=opp.id, owner=Ref(id=current_user.id, name=current_user.name))
