"""Klienci w API integracyjnym v1 (scope ``clients:read``).

Tylko klienci widoczni w aplikacji (bez ukrytych, zarchiwizowanych,
scalonych i usuniętych — ``visible_client_predicates``). Klient scalony
z innym zwraca 404, a lista podaje wyłącznie rekord docelowy.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_v1.common import (
    ClientsRead,
    IdPath,
    IntegrationRoute,
    Page,
    PageQuery,
    PageSizeQuery,
    page_of,
    principal_rate_key,
    read_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client import Client
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.services.client_identity import client_display_name, visible_client_predicates

router = APIRouter(route_class=IntegrationRoute)


class DeliveryLeadOut(BaseModel):
    user_id: int
    name: Optional[str]
    email: Optional[str]
    is_head: bool


class ClientOut(BaseModel):
    id: int
    name: str
    legal_name: Optional[str]
    nip: Optional[str]
    regon: Optional[str]
    status: Optional[str]
    delivery_leads: list[DeliveryLeadOut]
    updated_at: datetime


async def _delivery_leads(
    db: AsyncSession, client_ids: list[int]
) -> dict[int, list[DeliveryLeadOut]]:
    if not client_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.is_head,
                User.id,
                User.name,
                User.email,
            )
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(DeliveryLeadClientAssignment.client_id.in_(client_ids))
            .order_by(DeliveryLeadClientAssignment.is_head.desc(), User.name)
        )
    ).all()
    out: dict[int, list[DeliveryLeadOut]] = {}
    for client_id, is_head, user_id, name, email in rows:
        out.setdefault(client_id, []).append(
            DeliveryLeadOut(user_id=user_id, name=name, email=email, is_head=is_head)
        )
    return out


def _client_out(client: Client, leads: list[DeliveryLeadOut]) -> ClientOut:
    return ClientOut(
        id=client.id,
        name=client_display_name(client),
        legal_name=client.legal_name,
        nip=client.nip,
        regon=client.regon,
        status=client.status.value if client.status else None,
        delivery_leads=leads,
        updated_at=client.updated_at,
    )


@router.get("/clients", response_model=Page[ClientOut], summary="Lista klientów")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_clients(
    request: Request,
    _caller: ClientsRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    q: Optional[str] = Query(
        None, max_length=200, description="Fragment nazwy albo NIP."
    ),
    updated_since: Optional[datetime] = Query(
        None, description="Tylko klienci zmienieni od tej chwili (ISO 8601)."
    ),
) -> dict:
    """Klienci widoczni w NEXUSIE, sortowani po id (stabilne stronicowanie)."""
    query = select(Client).where(*visible_client_predicates())
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(
            or_(
                Client.name.ilike(needle),
                Client.display_name.ilike(needle),
                Client.legal_name.ilike(needle),
                Client.nip.ilike(needle),
            )
        )
    if updated_since is not None:
        query = query.where(Client.updated_at >= updated_since)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    clients = (
        (
            await db.execute(
                query.order_by(Client.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    leads = await _delivery_leads(db, [c.id for c in clients])
    items = [_client_out(c, leads.get(c.id, [])) for c in clients]
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get("/clients/{client_id}", response_model=ClientOut, summary="Klient")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_client(
    request: Request,
    client_id: IdPath,
    _caller: ClientsRead,
    db: AsyncSession = Depends(get_db),
) -> ClientOut:
    client = await db.scalar(
        select(Client).where(Client.id == client_id, *visible_client_predicates())
    )
    if client is None:
        raise HTTPException(404, detail="Klient nie istnieje albo nie jest widoczny.")
    leads = await _delivery_leads(db, [client.id])
    return _client_out(client, leads.get(client.id, []))
