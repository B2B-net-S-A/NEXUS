"""Currency-safe aggregation of ClientOrder revenue for finance surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Collection, NamedTuple, Optional, Sequence

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrderStatus
from app.services.fx_service import rates_to_pln


def fold_order_revenue_rows_pln(
    rows: Sequence[Any],
    fx_rates: dict[str, Optional[Decimal]],
) -> tuple[dict[int, dict[str, Decimal]], set[int]]:
    """Fold grouped ``client/status/currency/sum_val`` rows into PLN.

    A client with any unavailable required rate is marked incomplete. Callers
    must expose its totals as unavailable rather than publishing a partial sum.
    """

    totals: dict[int, dict[str, Decimal]] = {}
    incomplete: set[int] = set()
    for row in rows:
        status = getattr(row.status, "value", row.status)
        if status == ClientOrderStatus.cancelled.value:
            continue
        client_id = int(row.client_id)
        raw_value = Decimal(row.sum_val or 0)
        if raw_value == 0:
            totals.setdefault(
                client_id,
                {
                    "total": Decimal("0"),
                    "active": Decimal("0"),
                    "completed": Decimal("0"),
                },
            )
            continue
        currency = (row.currency or "PLN").strip().upper()
        fx = fx_rates.get(currency)
        if fx is None:
            incomplete.add(client_id)
            continue
        value = raw_value * fx
        slot = totals.setdefault(
            client_id,
            {
                "total": Decimal("0"),
                "active": Decimal("0"),
                "completed": Decimal("0"),
            },
        )
        slot["total"] += value
        if status == ClientOrderStatus.active.value:
            slot["active"] += value
        elif status == ClientOrderStatus.completed.value:
            slot["completed"] += value
    return totals, incomplete


async def order_revenue_rows_to_pln(
    db: AsyncSession,
    rows: Sequence[Any],
    on: date,
) -> tuple[dict[int, dict[str, Decimal]], set[int]]:
    currencies = {
        (row.currency or "PLN").strip().upper()
        for row in rows
        if Decimal(row.sum_val or 0) != 0
    }
    fx_rates = await rates_to_pln(db, currencies, on)
    return fold_order_revenue_rows_pln(rows, fx_rates)


# ── Wartość zamówień klienta: samodzielne + zamówienia MD/kosztowe ─────────
#
# Audyt 24.09.2026 (W1): Analityka klienta sumowała ``ClientOrder.total_value``
# po WSZYSTKICH wierszach ``client_orders``. Linie zamówień MD/kosztowych tej
# kolumny nie mają (budżet kosztowy żyje na grupie, MD — w ``md_*`` linii),
# więc u BIK/Polkomtela/BNP/CeZ kafel pokazywał 0 zł albo ułamek, a liczba
# „zamówień aktywnych” liczyła osoby (jedna grupa z dziesięcioma osobami =
# „10 zamówień”). Do tego wchodziły szkice.
#
# Jedna reguła dla Analityki, listy „Moi klienci” i przeglądu admina:
#   * zamówienie samodzielne (``order_group_id IS NULL``) — ``total_value``,
#     bez szkiców i anulowanych, jedno zamówienie = jeden wiersz;
#   * zamówienie MD/kosztowe = JEDNO zamówienie (grupa), bez szkiców
#     i anulowanych; wartość: kosztowe — kwota zamówienia (+ korekta), MD
#     per osoba — suma pozycji × stawka przychodowa jak „Wartość umowy” na
#     karcie zamówienia (``client_order_groups._serialize_group``), wspólna
#     pula MD — brak wartości (karta też jej nie liczy).

_GROUP_STATUS_BUCKET = {
    "active": ClientOrderStatus.active.value,
    "scheduled": "scheduled",
    "completed": ClientOrderStatus.completed.value,
    "exhausted": ClientOrderStatus.completed.value,
}


class OrderValueRow(NamedTuple):
    """Wiersz o kształcie oczekiwanym przez ``fold_order_revenue_rows_pln``."""

    client_id: int
    status: str
    currency: Optional[str]
    sum_val: Decimal
    cnt: int


@dataclass(frozen=True)
class MdLineValueInput:
    """Minimum danych linii MD potrzebne do wartości zamówienia."""

    id: int
    status: str
    md_total: Optional[Decimal]
    md_optional_total: Optional[Decimal]
    md_rate_revenue: Optional[Decimal]
    predecessor_order_id: Optional[int]
    md_used: Decimal


def md_group_contract_value(
    lines: Sequence[MdLineValueInput],
    *,
    swapped_or_taken_over_ids: set[int],
) -> Decimal:
    """Wartość zamówienia MD z budżetem per osoba (PLN).

    Lustro sumy „Wartość umowy” z ``client_order_groups._serialize_group``:
    linia z budżetem wnosi (podstawa + opcja) × stawka; linia zastąpiona
    (``predecessor_order_id`` innej, nieanulowanej linii) wnosi tylko swoje
    zużycie po zamianie/przejęciu i nic po zastępstwie (następca ma własną
    pozycję); anulowana linia i szkic zaplanowanego następcy nie wnoszą nic,
    a poprzednik zaplanowanego następcy wnosi cały budżet (jeszcze pracuje).
    """
    cancelled = ClientOrderStatus.cancelled.value
    draft = ClientOrderStatus.draft.value
    # Najnowszy nieanulowany następca per poprzednik — jak na karcie.
    successor: dict[int, MdLineValueInput] = {}
    for line in lines:
        if line.status == cancelled or line.predecessor_order_id is None:
            continue
        current = successor.get(line.predecessor_order_id)
        if current is None or line.id > current.id:
            successor[line.predecessor_order_id] = line
    scheduled_ids = {line.id for line in successor.values() if line.status == draft}
    value = Decimal("0")
    for line in lines:
        if line.md_total is None:
            continue
        if line.status == cancelled or line.id in scheduled_ids:
            continue
        rate = Decimal(str(line.md_rate_revenue or 0))
        nxt = successor.get(line.id)
        if nxt is None or nxt.status == draft:
            budget = Decimal(str(line.md_total or 0)) + Decimal(
                str(line.md_optional_total or 0)
            )
            value += budget * rate
        elif line.id in swapped_or_taken_over_ids:
            value += line.md_used * rate
        # Zastępstwo przez ``replaces_order_id``: pozycję niesie następca.
    return value


async def client_order_value_rows(
    db: AsyncSession,
    client_ids: Optional[Collection[int]] = None,
    *,
    with_values: bool = True,
) -> list[OrderValueRow]:
    """Wiersze ``(klient, status, waluta, wartość, liczba zamówień)``.

    ``with_values=False`` liczy wyłącznie zamówienia (operacyjne liczniki dla
    ról bez prawa do kwot) — kwoty nie są wtedy nawet czytane z bazy.
    """
    # Importy leniwe: moduły zamówień importują pośrednio ten plik.
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
    from app.models.md_consumption import ClientOrderMdConsumption
    from app.services.multi_consultant_orders import (
        EVENT_CONSULTANT_ADDED,
        EVENT_CONSULTANT_SWAPPED,
    )
    from app.services.order_line_takeover import ASSIGNMENT_TAKEOVER
    from app.services.shared_md_orders import uses_shared_md_pool

    ids: list[int] = []
    if client_ids is not None:
        ids = sorted(set(client_ids))
        if not ids:
            return []

    standalone = (
        select(
            ClientOrder.client_id,
            ClientOrder.status,
            ClientOrder.currency,
            (
                func.coalesce(func.sum(ClientOrder.total_value), 0)
                if with_values
                else literal(0)
            ).label("sum_val"),
            func.count().label("cnt"),
        )
        .where(
            ClientOrder.order_group_id.is_(None),
            ClientOrder.status.notin_(
                (ClientOrderStatus.draft, ClientOrderStatus.cancelled)
            ),
        )
        .group_by(ClientOrder.client_id, ClientOrder.status, ClientOrder.currency)
    )
    if client_ids is not None:
        standalone = standalone.where(ClientOrder.client_id.in_(ids))
    rows: list[OrderValueRow] = []
    for row in await db.execute(standalone):
        rows.append(
            OrderValueRow(
                int(row.client_id),
                str(getattr(row.status, "value", row.status)),
                row.currency,
                Decimal(row.sum_val or 0) if with_values else Decimal("0"),
                int(row.cnt or 0),
            )
        )

    group_stmt = select(ClientOrderGroup).where(
        ClientOrderGroup.status.notin_(("draft", "cancelled"))
    )
    if client_ids is not None:
        group_stmt = group_stmt.where(ClientOrderGroup.client_id.in_(ids))
    groups = list((await db.execute(group_stmt)).scalars())
    if not groups:
        return rows

    values: dict[int, Decimal] = {}
    if with_values:
        md_group_ids = [
            g.id for g in groups if not g.is_cost_based and not uses_shared_md_pool(g)
        ]
        lines_by_group: dict[int, list[MdLineValueInput]] = {}
        swapped: set[int] = set()
        if md_group_ids:
            used_sq = (
                select(
                    ClientOrderMdConsumption.order_id.label("order_id"),
                    func.sum(ClientOrderMdConsumption.md_reported).label("used"),
                )
                .group_by(ClientOrderMdConsumption.order_id)
                .subquery()
            )
            line_rows = await db.execute(
                select(
                    ClientOrder.id,
                    ClientOrder.order_group_id,
                    ClientOrder.status,
                    ClientOrder.md_total,
                    ClientOrder.md_optional_total,
                    ClientOrder.md_rate_revenue,
                    ClientOrder.predecessor_order_id,
                    func.coalesce(used_sq.c.used, 0).label("used"),
                )
                .outerjoin(used_sq, used_sq.c.order_id == ClientOrder.id)
                .where(ClientOrder.order_group_id.in_(md_group_ids))
            )
            for r in line_rows:
                lines_by_group.setdefault(int(r.order_group_id), []).append(
                    MdLineValueInput(
                        id=int(r.id),
                        status=str(getattr(r.status, "value", r.status)),
                        md_total=r.md_total,
                        md_optional_total=r.md_optional_total,
                        md_rate_revenue=r.md_rate_revenue,
                        predecessor_order_id=r.predecessor_order_id,
                        md_used=Decimal(str(r.used or 0)),
                    )
                )
            event_rows = await db.execute(
                select(
                    ClientOrderGroupEvent.event_type, ClientOrderGroupEvent.payload
                ).where(
                    ClientOrderGroupEvent.group_id.in_(md_group_ids),
                    ClientOrderGroupEvent.event_type.in_(
                        (EVENT_CONSULTANT_SWAPPED, EVENT_CONSULTANT_ADDED)
                    ),
                )
            )
            for event_type, payload in event_rows:
                payload = payload or {}
                if event_type == EVENT_CONSULTANT_SWAPPED:
                    old_id = payload.get("old_order_id")
                elif payload.get("assignment") == ASSIGNMENT_TAKEOVER:
                    old_id = payload.get("takeover_from_order_id")
                else:
                    continue
                if isinstance(old_id, int):
                    swapped.add(old_id)
        for group in groups:
            if group.is_cost_based:
                values[group.id] = Decimal(str(group.budget_amount or 0)) + Decimal(
                    str(group.budget_manual_adjustment or 0)
                )
            elif group.id in lines_by_group:
                values[group.id] = md_group_contract_value(
                    lines_by_group[group.id], swapped_or_taken_over_ids=swapped
                )

    buckets: dict[tuple[int, str], tuple[Decimal, int]] = {}
    for group in groups:
        bucket = _GROUP_STATUS_BUCKET.get(group.status, str(group.status))
        value, count = buckets.get((group.client_id, bucket), (Decimal("0"), 0))
        buckets[(group.client_id, bucket)] = (
            value + values.get(group.id, Decimal("0")),
            count + 1,
        )
    for (client_id, bucket), (value, count) in buckets.items():
        # Stawki MD i kwoty zamówień kosztowych są w PLN.
        rows.append(OrderValueRow(client_id, bucket, "PLN", value, count))
    return rows


def order_counts_by_status(rows: Sequence[Any]) -> dict[int, dict[str, int]]:
    """``{klient: {status: liczba zamówień}}`` z ``client_order_value_rows``."""
    counts: dict[int, dict[str, int]] = {}
    for row in rows:
        status = str(getattr(row.status, "value", row.status))
        slot = counts.setdefault(int(row.client_id), {})
        slot[status] = slot.get(status, 0) + int(row.cnt or 0)
    return counts
