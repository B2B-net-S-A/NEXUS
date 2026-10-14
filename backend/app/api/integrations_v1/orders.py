"""Zamówienia w API integracyjnym v1 (scope ``orders:read``, MD: ``md:read``).

Jedno zamówienie = wiersz ``client_orders``: samodzielne zamówienie okresowe
albo LINIA zamówienia MD/kosztowego (``order_group_id``). Numer, typ, okres
efektywny (``COALESCE(linia, grupa)``, koniec udziału osoby) i stawki liczy
``services/order_facts`` — ta sama reguła co Finanse → Zmiany w zamówieniach
i Braki, więc API i ekran Finansów nie rozjadą się.

Kwoty według poziomu klucza (``common.amount_level``): stawka do klienta
(``rate_revenue``) i kwota zamówienia kosztowego (``budget_amount``,
``budget_remaining``) ze ``sales_amounts:read``, stawka konsultanta
(``rate_cost``) dopiero z ``amounts:read``. Liczby MD (budżet, saldo,
zejścia) są operacyjne — jak na ekranie, widzi je każdy z dostępem do
zamówień. PDF-y zamówień: ``/finance/order-pdfs`` (scope ``finance:read``).

Odczyt NIE wykonuje efektów ubocznych ekranu (``GET /order-groups`` ekranu
materializuje zamówienia „zaplanowane” i domyka wyczerpane). Status grupy
jest więc stanem zapisanym — ``scheduled`` przechodzi w ``active`` przy
najbliższym przebiegu skanera albo otwarciu karty klienta.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.integrations_v1.common import (
    AmountLevel,
    IdPath,
    IntegrationRoute,
    MdRead,
    Money,
    OrdersRead,
    Page,
    PageQuery,
    PageSizeQuery,
    amount_level,
    page_of,
    principal_rate_key,
    read_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.services.client_identity import client_display_name
from app.services.client_order_lines import consumption_rows
from app.services.order_facts import (
    effective_start_expr,
    fact_from_row,
    order_facts_select,
    participation_end_expr,
)

router = APIRouter(route_class=IntegrationRoute)

_MAX_INT4 = 2_147_483_647


class OrderPersonOut(BaseModel):
    candidate_id: Optional[int]
    name: str


class OrderOut(BaseModel):
    id: int
    number: str
    order_type: str
    status: str
    order_group_id: Optional[int]
    contract_id: int
    person: OrderPersonOut
    client_id: int
    client_name: str
    start_date: Optional[date]
    end_date: Optional[date]
    rate_unit: Optional[str]
    currency: Optional[str]
    amounts_redacted: bool
    costs_redacted: bool
    rate_cost: Money
    rate_revenue: Money
    md_total: Optional[Decimal]
    md_remaining: Optional[Decimal]
    has_file: bool
    created_at: datetime
    updated_at: datetime


def _order_out(row, *, level: AmountLevel) -> OrderOut:
    fact = fact_from_row(row)
    return OrderOut(
        id=fact.order_id,
        number=fact.number,
        order_type=fact.order_type,
        status=fact.status,
        order_group_id=fact.order_group_id,
        contract_id=fact.contract_id,
        person=OrderPersonOut(
            candidate_id=fact.candidate_id, name=fact.consultant_name
        ),
        client_id=fact.client_id,
        client_name=fact.client_name,
        start_date=fact.start,
        end_date=fact.end,
        rate_unit=fact.rate_unit,
        currency=fact.currency,
        amounts_redacted=level is AmountLevel.none,
        costs_redacted=level is not AmountLevel.all,
        rate_cost=fact.rate_cost if level is AmountLevel.all else None,
        rate_revenue=fact.rate_revenue if level >= AmountLevel.sales else None,
        md_total=fact.md_total,
        md_remaining=fact.md_remaining,
        has_file=bool(row.filename),
        created_at=fact.created_at,
        updated_at=row.updated_at,
    )


def _orders_select():
    return order_facts_select().add_columns(
        ClientOrder.updated_at, ClientOrder.filename
    )


@router.get("/orders", response_model=Page[OrderOut], summary="Lista zamówień")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_orders(
    request: Request,
    caller: OrdersRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    client_id: Optional[int] = Query(None, ge=1, le=_MAX_INT4),
    contract_id: Optional[int] = Query(None, ge=1, le=_MAX_INT4),
    order_group_id: Optional[int] = Query(None, ge=1, le=_MAX_INT4),
    status: Optional[list[ClientOrderStatus]] = Query(None),
    active_on: Optional[date] = Query(
        None, description="Zamówienia obowiązujące tego dnia (okres efektywny)."
    ),
    updated_since: Optional[datetime] = Query(None),
) -> dict:
    """Zamówienia i linie zamówień MD sortowane po id."""
    level = amount_level(caller)
    conditions = []
    if client_id is not None:
        conditions.append(ClientOrder.client_id == client_id)
    if contract_id is not None:
        conditions.append(ClientOrder.contract_id == contract_id)
    if order_group_id is not None:
        conditions.append(ClientOrder.order_group_id == order_group_id)
    if status:
        conditions.append(ClientOrder.status.in_(status))
    if active_on is not None:
        start = effective_start_expr()
        end = participation_end_expr()
        conditions.append(
            and_(
                or_(start.is_(None), start <= active_on),
                or_(end.is_(None), end >= active_on),
            )
        )
    if updated_since is not None:
        conditions.append(ClientOrder.updated_at >= updated_since)
    query = _orders_select().where(*conditions)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(
            query.order_by(ClientOrder.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [_order_out(row, level=level) for row in rows]
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get("/orders/{order_id}", response_model=OrderOut, summary="Zamówienie")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_order(
    request: Request,
    order_id: IdPath,
    caller: OrdersRead,
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    row = (await db.execute(_orders_select().where(ClientOrder.id == order_id))).first()
    if row is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje.")
    return _order_out(row, level=amount_level(caller))


class MdConsumptionMonthOut(BaseModel):
    period_month: str
    md_reported: Decimal
    source: str


class OrderMdConsumptionsOut(BaseModel):
    order_id: int
    order_group_id: Optional[int]
    md_total: Optional[Decimal]
    md_remaining: Optional[Decimal]
    months: list[MdConsumptionMonthOut]


@router.get(
    "/orders/{order_id}/md-consumptions",
    response_model=OrderMdConsumptionsOut,
    summary="Zużycie MD linii zamówienia",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_md_consumptions(
    request: Request,
    order_id: IdPath,
    _caller: MdRead,
    db: AsyncSession = Depends(get_db),
) -> OrderMdConsumptionsOut:
    """Zejścia MD osoby miesiąc po miesiącu (``YYYY-MM``) i saldo linii."""
    order = await db.get(ClientOrder, order_id)
    if order is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje.")
    rows = await consumption_rows(db, order_id)
    return OrderMdConsumptionsOut(
        order_id=order.id,
        order_group_id=order.order_group_id,
        md_total=order.md_total,
        md_remaining=order.md_remaining,
        months=[
            MdConsumptionMonthOut(
                period_month=r.period_month,
                md_reported=Decimal(str(r.md_reported)),
                source=r.source,
            )
            for r in rows
        ],
    )


class OrderGroupOut(BaseModel):
    id: int
    order_number: str
    order_type: str
    status: str
    client_id: int
    client_name: Optional[str]
    start_date: date
    end_date: Optional[date]
    is_cost_based: bool
    is_md_budget_based: bool
    md_budget_total: Optional[Decimal]
    md_budget_remaining: Optional[Decimal]
    amounts_redacted: bool
    costs_redacted: bool
    budget_amount: Money
    budget_remaining: Money
    has_file: bool
    lines: list[OrderOut]
    updated_at: datetime


def _group_type(group: ClientOrderGroup) -> str:
    if group.order_type:
        return str(group.order_type)
    return "cost" if group.is_cost_based else "md"


async def _group_out(
    db: AsyncSession, groups: list[ClientOrderGroup], *, level: AmountLevel
) -> list[OrderGroupOut]:
    ids = [g.id for g in groups]
    lines: dict[int, list[OrderOut]] = {}
    if ids:
        rows = (
            await db.execute(
                _orders_select()
                .where(ClientOrder.order_group_id.in_(ids))
                .order_by(ClientOrder.id)
            )
        ).all()
        for row in rows:
            out = _order_out(row, level=level)
            lines.setdefault(out.order_group_id or 0, []).append(out)
    return [
        OrderGroupOut(
            id=g.id,
            order_number=g.order_number,
            order_type=_group_type(g),
            status=g.status,
            client_id=g.client_id,
            client_name=client_display_name(g.client) if g.client else None,
            start_date=g.start_date,
            end_date=g.end_date,
            is_cost_based=bool(g.is_cost_based),
            is_md_budget_based=bool(g.is_md_budget_based),
            md_budget_total=g.md_budget_total,
            md_budget_remaining=g.md_budget_remaining,
            amounts_redacted=level is AmountLevel.none,
            costs_redacted=level is not AmountLevel.all,
            budget_amount=g.budget_amount if level >= AmountLevel.sales else None,
            budget_remaining=(
                g.budget_remaining if level >= AmountLevel.sales else None
            ),
            has_file=bool(g.filename),
            lines=lines.get(g.id, []),
            updated_at=g.updated_at,
        )
        for g in groups
    ]


@router.get(
    "/order-groups",
    response_model=Page[OrderGroupOut],
    summary="Lista zamówień MD i kosztowych (z liniami)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_order_groups(
    request: Request,
    caller: OrdersRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: int = Query(100, ge=1, le=200),
    client_id: Optional[int] = Query(None, ge=1, le=_MAX_INT4),
    status: Optional[list[str]] = Query(
        None,
        description="draft | active | scheduled | completed | exhausted | cancelled",
    ),
    updated_since: Optional[datetime] = Query(None),
) -> dict:
    """Zamówienia wielo-konsultantowe (MD / kosztowe) z liniami osób."""
    level = amount_level(caller)
    query = select(ClientOrderGroup).options(selectinload(ClientOrderGroup.client))
    if client_id is not None:
        query = query.where(ClientOrderGroup.client_id == client_id)
    if status:
        query = query.where(ClientOrderGroup.status.in_(status))
    if updated_since is not None:
        query = query.where(ClientOrderGroup.updated_at >= updated_since)
    total = (
        await db.execute(
            select(func.count()).select_from(
                query.with_only_columns(ClientOrderGroup.id).subquery()
            )
        )
    ).scalar() or 0
    groups = (
        (
            await db.execute(
                query.order_by(ClientOrderGroup.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = await _group_out(db, list(groups), level=level)
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/order-groups/{group_id}",
    response_model=OrderGroupOut,
    summary="Zamówienie MD / kosztowe z liniami",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_order_group(
    request: Request,
    group_id: IdPath,
    caller: OrdersRead,
    db: AsyncSession = Depends(get_db),
) -> OrderGroupOut:
    group = await db.scalar(
        select(ClientOrderGroup)
        .options(selectinload(ClientOrderGroup.client))
        .where(ClientOrderGroup.id == group_id)
    )
    if group is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje.")
    return (await _group_out(db, [group], level=amount_level(caller)))[0]
