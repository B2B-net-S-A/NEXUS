"""Typy nowych zamówień i podpowiedź z historii klienta."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.order_type import OrderType

# Kanoniczne rekordy produkcyjne wskazane w ticketcie korekty z 29.08.2026.
# Bramka jest po ID, nie po nazwie: rodzina BNP zawiera kilka niezależnych
# klientów, a nazwy są synchronizowane z Traffita. Cyfrowy Polsat świadomie
# nie należy do tej listy — zachowuje trzy typy zamówień.
_PINNED_ALLOWED_ORDER_TYPES: dict[int, tuple[OrderType, ...]] = {
    12: (OrderType.md,),
    18: (OrderType.md,),
    15: (OrderType.md, OrderType.cost),
    155: (OrderType.md, OrderType.cost),
}


def allowed_order_types(client_id: int) -> tuple[OrderType, ...]:
    """Zwróć typy, które wolno utworzyć dla konkretnego klienta.

    BNP i BIK mają wyłącznie MD, Polkomtel i Wedel MD + kosztowe.
    Pozostali klienci zachowują dotychczasowy jawny wybór wszystkich trzech
    typów. Cztery wyjątki z ticketu są jedynym zawężeniem tej polityki.
    """

    pinned = _PINNED_ALLOWED_ORDER_TYPES.get(client_id)
    if pinned is not None:
        return pinned

    return (OrderType.periodic, OrderType.cost, OrderType.md)


def assert_order_type_allowed(client_id: int, order_type: OrderType | str) -> None:
    """Odrzuć zapis typu spoza klientowej polityki."""

    resolved = OrderType(order_type)
    if resolved not in allowed_order_types(client_id):
        raise ValueError(
            f"Typ zamówienia {resolved.value} nie jest dostępny dla tego klienta"
        )


def should_process_active_standalone_order(
    client_id: int,
    order_type: OrderType | str,
    *,
    was_active: bool,
) -> bool:
    """Enforce new activation policy without freezing live cleanup targets.

    A draft or paused order entering ``active`` must use an allowed type.
    An already-active row with a now-forbidden explicit type remains editable
    until the separately approved data cleanup, but callers must skip any
    materialization or other type-specific activation work for that row.
    """

    resolved = OrderType(order_type)
    if resolved in allowed_order_types(client_id):
        return True
    if not was_active:
        assert_order_type_allowed(client_id, resolved)
    return False


def effective_standalone_order_type(
    client_id: int, order_type: OrderType | str | None
) -> OrderType:
    """Interpretuj legacy ``NULL`` zgodnie z polityką konkretnego klienta.

    Przed dodaniem jawnego typu samodzielne zamówienia miały ``NULL``. Dla
    klienta, który nadal dopuszcza okresowe, jest to historyczne ``periodic``.
    Gdy okresowe są wyłączone, ``NULL`` oznacza pierwszy dozwolony typ (MD dla
    czterech klientów z korekty), a nie zamówienie okresowe do pokazania lub
    usunięcia.
    """

    if order_type is not None:
        return OrderType(order_type)
    allowed = allowed_order_types(client_id)
    if OrderType.periodic in allowed:
        return OrderType.periodic
    if not allowed:
        raise ValueError("Klient nie ma skonfigurowanego żadnego typu zamówienia")
    return allowed[0]


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
    order. Historia bez żadnego rekordu daje pierwszy typ dozwolony polityką
    klienta (zwykle ``periodic``, a dla BNP/BIK/Polkomtela/Wedla ``md``).
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

    allowed = allowed_order_types(client_id)
    if not allowed:
        raise ValueError("Klient nie ma skonfigurowanego żadnego typu zamówienia")

    if latest_order is None and latest_group is None:
        return allowed[0]
    if latest_group is None:
        suggested = effective_standalone_order_type(client_id, latest_order.order_type)
        return suggested if suggested in allowed else allowed[0]
    if latest_order is None:
        suggested = effective_group_order_type(latest_group)
        return suggested if suggested in allowed else allowed[0]

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    order_created = latest_order.created_at or epoch
    group_created = latest_group.created_at or epoch
    if group_created >= order_created:
        suggested = effective_group_order_type(latest_group)
    else:
        suggested = effective_standalone_order_type(client_id, latest_order.order_type)
    return suggested if suggested in allowed else allowed[0]
