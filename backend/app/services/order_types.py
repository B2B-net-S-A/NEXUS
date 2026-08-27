"""Typy nowych zamówień i podpowiedź z historii klienta."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.order_type import OrderType


def effective_group_order_type(group: ClientOrderGroup) -> OrderType:
    """Typ grupy bez przepisywania rekordów historycznych.

    Nowa grupa ma ``order_type``. Dla legacy koszt rozpoznaje istniejąca flaga,
    a pozostała grupa jest dawnym wariantem MD z budżetem na liniach. To jest
    wyłącznie interpretacja odczytowa — nie zapis ani backfill.
    """

    if group.order_type is not None:
        return OrderType(group.order_type)
    if group.is_cost_based:
        return OrderType.cost
    return OrderType.md


async def suggested_order_type(db: AsyncSession, client_id: int) -> OrderType:
    """Zwróć typ ostatnio utworzonego zamówienia klienta.

    Samodzielny ``ClientOrder`` jest zamówieniem okresowym albo jeszcze
    nieuzupełnionym, jawnym szkicem kosztowym/MD. Linie grup są pomijane, bo
    inaczej każde zamówienie kosztowe/MD głosowałoby drugi raz jako osobny
    order. Historia bez żadnego rekordu daje ``periodic``.
    """

    latest_order = await db.scalar(
        select(ClientOrder)
        .where(
            ClientOrder.client_id == client_id,
            ClientOrder.order_group_id.is_(None),
        )
        .order_by(ClientOrder.created_at.desc(), ClientOrder.id.desc())
        .limit(1)
    )
    latest_group = await db.scalar(
        select(ClientOrderGroup)
        .where(ClientOrderGroup.client_id == client_id)
        .order_by(ClientOrderGroup.created_at.desc(), ClientOrderGroup.id.desc())
        .limit(1)
    )

    if latest_order is None and latest_group is None:
        return OrderType.periodic
    if latest_group is None:
        return OrderType(latest_order.order_type or OrderType.periodic.value)
    if latest_order is None:
        return effective_group_order_type(latest_group)

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    order_created = latest_order.created_at or epoch
    group_created = latest_group.created_at or epoch
    if group_created >= order_created:
        return effective_group_order_type(latest_group)
    return OrderType(latest_order.order_type or OrderType.periodic.value)
