"""Typy nowych zamówień i podpowiedź z historii klienta."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.order_type import OrderType

ALL_ORDER_TYPES: tuple[OrderType, ...] = (
    OrderType.periodic,
    OrderType.cost,
    OrderType.md,
)

# Jak czytać historyczne samodzielne zamówienia BEZ jawnego typu (``NULL``).
#
# Do 09.2026 ta mapa była SZTYWNĄ polityką zapisu: BNP i BIK mogły tworzyć
# wyłącznie MD, Polkomtel i Wedel MD + kosztowe. Ticket „jedno okno Nowe
# zamówienie" znosi tę blokadę — każdy klient ma wszystkie trzy typy, a
# formularz jedynie PODPOWIADA najczęstszy (``most_common_order_type``).
#
# Mapa zostaje wyłącznie jako INTERPRETACJA ODCZYTU: legacy ``NULL`` u tych
# czterech klientów był od zawsze zamówieniem MD. Zdjęcie jej razem z blokadą
# przeklasyfikowałoby ich historyczne karty na „Okresowe" — zmiana widoczna
# w rejestrze, niezwiązana z tym, co ticket naprawia.
_LEGACY_NULL_ORDER_TYPES: dict[int, OrderType] = {
    12: OrderType.md,
    18: OrderType.md,
    15: OrderType.md,
    155: OrderType.md,
}


def allowed_order_types(client_id: int) -> tuple[OrderType, ...]:
    """Zwróć typy, które wolno utworzyć dla konkretnego klienta.

    Od 09.2026 wszystkie trzy typy są dostępne dla każdego klienta — bez
    blokady per klient. Funkcja zostaje jako jeden punkt polityki, bo wołają
    ją walidatory zapisu (``assert_order_type_allowed``) i audyt korekty
    danych z sierpnia (``nexus_data_correction``), który przez nią wykrywa, że
    jego założenia przestały obowiązywać.
    """

    del client_id  # polityka jest jednakowa dla wszystkich klientów
    return ALL_ORDER_TYPES


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


def legacy_null_order_type(client_id: int | None) -> OrderType:
    """Jak interpretować historyczne samodzielne zamówienie bez typu."""

    if client_id is None:
        return OrderType.periodic
    return _LEGACY_NULL_ORDER_TYPES.get(client_id, OrderType.periodic)


def effective_standalone_order_type(
    client_id: int, order_type: OrderType | str | None
) -> OrderType:
    """Interpretuj legacy ``NULL`` zgodnie z historią konkretnego klienta.

    Przed dodaniem jawnego typu samodzielne zamówienia miały ``NULL``. Dla
    zwykłego klienta jest to historyczne ``periodic``, a dla czterech klientów
    rozliczanych w MD (BNP, BIK, Polkomtel, Wedel) — ``md``.
    """

    if order_type is not None:
        return OrderType(order_type)
    return legacy_null_order_type(client_id)


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
    order. Historia bez żadnego rekordu daje typ, którym klient rozlicza się
    historycznie (``legacy_null_order_type``).

    Ostatni typ podpowiadają automaty (szkic po zatrudnieniu, poczta
    zamówień). Formularz „Nowe zamówienie" podpowiada NAJCZĘSTSZY typ —
    patrz ``most_common_order_type``.
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
        return legacy_null_order_type(client_id)
    if latest_group is None:
        return effective_standalone_order_type(client_id, latest_order.order_type)
    if latest_order is None:
        return effective_group_order_type(latest_group)

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    order_created = latest_order.created_at or epoch
    group_created = latest_group.created_at or epoch
    if group_created >= order_created:
        return effective_group_order_type(latest_group)
    return effective_standalone_order_type(client_id, latest_order.order_type)


async def most_common_order_type(db: AsyncSession, client_id: int) -> OrderType:
    """Typ najczęściej występujący w historii zamówień klienta.

    Podpowiedź domyślnego typu w oknie „Nowe zamówienie" (np. BIK → MD).
    Liczone są grupy (kosztowe/MD) i samodzielne zamówienia bez anulowanych —
    linie grup nie głosują drugi raz. Remis rozstrzyga typ ostatnio
    utworzonego zamówienia, a brak historii — typ historyczny klienta.
    Podpowiedź niczego nie blokuje: użytkownik zawsze może wybrać inny typ.
    """

    counts: Counter[OrderType] = Counter()
    group_rows = await db.execute(
        select(
            ClientOrderGroup.order_type,
            ClientOrderGroup.is_cost_based,
            func.count(ClientOrderGroup.id),
        )
        .where(ClientOrderGroup.client_id == client_id)
        .group_by(ClientOrderGroup.order_type, ClientOrderGroup.is_cost_based)
    )
    for order_type, is_cost_based, count in group_rows.all():
        if order_type is not None:
            resolved = OrderType(order_type)
        else:
            resolved = OrderType.cost if is_cost_based else OrderType.md
        counts[resolved] += int(count)

    order_rows = await db.execute(
        select(ClientOrder.order_type, func.count(ClientOrder.id))
        .where(
            ClientOrder.client_id == client_id,
            ClientOrder.order_group_id.is_(None),
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
        .group_by(ClientOrder.order_type)
    )
    for order_type, count in order_rows.all():
        counts[effective_standalone_order_type(client_id, order_type)] += int(count)

    if not counts:
        return legacy_null_order_type(client_id)
    top = max(counts.values())
    leaders = {order_type for order_type, count in counts.items() if count == top}
    if len(leaders) == 1:
        return next(iter(leaders))
    latest = await suggested_order_type(db, client_id)
    if latest in leaders:
        return latest
    # Ostatni typ nie należy do remisu (np. anulowane zamówienie) — kolejność
    # stała, żeby odpowiedź nie zależała od kolejności słownika.
    return next(order_type for order_type in ALL_ORDER_TYPES if order_type in leaders)
