"""Stawka przychodowa zamówienia od dnia aneksu (ticket Finansów 16.11.2026).

Zgłoszenie: aneks w kontrakcie podniósł stawkę klienta od 01.11.2026, a linia
zamówienia MD została przy starej stawce. Do tego dnia synchronizacja
kontrakt → zamówienie przenosiła wyłącznie koszt (``contract_order_sync``),
a zamówienie miało jedną stawkę przychodową na cały okres — ręczna zmiana
przeliczyłaby „Do faktury” także za miesiące sprzed aneksu, bo kwota liczy
się przy odczycie: zużycie MD × stawka linii.

Reguły (decyzja Artura z 16.11.2026, wariant A):

* **Aneks ze stawką klienta zapisuje krok w każdym żywym zamówieniu
  kontraktu**, które trwa w dniu aneksu (start przed tym dniem, koniec nie
  wcześniej). Zamówienie zaczynające się w dniu aneksu albo później ma już
  własną stawkę i zostaje nietknięte; zakończone i anulowane są historią.
* **Stawka sprzed pierwszego kroku to kolumny zamówienia** (``rate_client``,
  ``md_rate_revenue``) — nie zmieniamy ich. Wszystko, co nie wie o krokach,
  liczy jak przed tą zmianą (także kierunek zamówienie → kontrakt, który
  bierze stawkę ze startu zamówienia).
* **Miesiąc liczy się stawką obowiązującą w jego pierwszym dniu**, bo
  zużycie MD przychodzi jedną liczbą na miesiąc. Aneks od 15.11 wchodzi do
  rozliczenia od grudnia; okno aneksu mówi to przed zapisem.
* **Przeliczenie z kontraktu**: kontrakt jest zawsze w zł/h (albo
  miesięczny), zamówienie MD dostaje stawkę × 8 zaokrągloną do grosza —
  stawka godzinowa z aneksu bywa przepisana z ekranu z trzema miejscami
  (221,881 zamiast 221,88125), a MD 1775,048 nie jest kwotą z żadnej umowy.
  Inna waluta zamówienia niż kontraktu = bez zmiany (nie przeliczamy kursem).

Miesięczne pieniądze czytają stawkę przez :func:`priced_for_month`
(„Do faktury” w ``client_invoicing/billing.py``) i :func:`priced_one`
(Rozliczenia, KEŚU, faktura klienta przez ``client_settlements.service._order_for``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.client_order_revenue_step import ClientOrderRevenueStep
from app.models.contract import Contract, RateUnit
from app.services.order_rate_snapshots import (
    CONTRACT_RATE_SCALE,
    RATE_SCALE,
    contract_rate_in_unit,
    convert_order_rate,
)

#: Zamówienia, które aneks zmienia. Zakończone i anulowane są historią.
LIVE_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)
GROSZ = Decimal("0.01")
#: To samo zdarzenie Historii co ręczna edycja linii — CHECK typów zdarzeń
#: zostaje bez zmian, a opis i ``payload.kind`` mówią, co się stało.
EVENT_TYPE = "edycja_reczna"
EVENT_KIND = "revenue_rate_step"


def _currency(order: Any) -> str:
    return (order.rate_client_currency or order.currency or "PLN").upper()


def month_first_day(day: date) -> date:
    return day.replace(day=1)


def first_priced_month(effective_from: date) -> date:
    """Pierwszy miesiąc liczony nową stawką (pierwszy dzień miesiąca)."""

    if effective_from.day == 1:
        return effective_from
    nxt = effective_from.replace(day=28) + timedelta(days=4)
    return nxt.replace(day=1)


def rates_on(
    order: Any, steps: Sequence[ClientOrderRevenueStep], day: date
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Stawka przychodowa zamówienia w dniu ``day`` (``rate_client``, PLN/MD)."""

    current: Optional[ClientOrderRevenueStep] = None
    for step in steps:
        if step.effective_from <= day and (
            current is None or step.effective_from > current.effective_from
        ):
            current = step
    if current is None:
        return order.rate_client, order.md_rate_revenue
    return current.rate_client, current.md_rate_revenue


class PricedOrder:
    """Zamówienie do odczytu ze stawką przychodową z danego dnia.

    Pozostałe pola czyta z zamówienia. Zapis jest zablokowany — to widok do
    liczenia pieniędzy, nie obiekt sesji."""

    __slots__ = ("_order", "rate_client", "md_rate_revenue")

    def __init__(
        self,
        order: ClientOrder,
        rate_client: Optional[Decimal],
        md_rate_revenue: Optional[Decimal],
    ) -> None:
        object.__setattr__(self, "_order", order)
        object.__setattr__(self, "rate_client", rate_client)
        object.__setattr__(self, "md_rate_revenue", md_rate_revenue)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._order, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"PricedOrder jest tylko do odczytu ({name})")


async def load_steps(
    db: AsyncSession, order_ids: Iterable[int]
) -> dict[int, list[ClientOrderRevenueStep]]:
    ids = sorted({int(i) for i in order_ids})
    if not ids:
        return {}
    out: dict[int, list[ClientOrderRevenueStep]] = defaultdict(list)
    for step in await db.scalars(
        select(ClientOrderRevenueStep)
        .where(ClientOrderRevenueStep.order_id.in_(ids))
        .order_by(ClientOrderRevenueStep.effective_from)
    ):
        out[step.order_id].append(step)
    return dict(out)


async def priced_for_month(
    db: AsyncSession, orders: Sequence[ClientOrder], month_first: date
) -> list[Any]:
    """Zamówienia ze stawką na miesiąc. Bez kroków — ten sam obiekt."""

    steps = await load_steps(db, (o.id for o in orders))
    if not steps:
        return list(orders)
    return [
        PricedOrder(o, *rates_on(o, steps[o.id], month_first)) if o.id in steps else o
        for o in orders
    ]


async def priced_one(
    db: AsyncSession, order: Optional[ClientOrder], month_first: date
) -> Any:
    if order is None:
        return None
    return (await priced_for_month(db, [order], month_first))[0]


def order_rates_from_contract(
    rate: Decimal, contract: Contract, order: ClientOrder
) -> Optional[tuple[Decimal, Optional[Decimal]]]:
    """Stawka klienta z kontraktu w jednostce zamówienia (+ PLN/MD).

    ``None`` — zamówienia nie da się przeliczyć bez zgadywania (inna waluta,
    brak jednostki, stawka MD w obcej walucie przeliczana kursem)."""

    if order.rate_unit is None:
        return None
    if _currency(order) != contract.resolved_rate_client_currency.upper():
        return None
    unit = RateUnit(order.rate_unit)
    value = contract_rate_in_unit(rate, contract, unit, scale=CONTRACT_RATE_SCALE)
    if value is None or value <= 0:
        return None
    if unit == RateUnit.daily:
        value = value.quantize(GROSZ, rounding=ROUND_HALF_UP)
    else:
        value = value.quantize(RATE_SCALE, rounding=ROUND_HALF_UP)
    md: Optional[Decimal] = None
    if order.md_rate_revenue is not None:
        if _currency(order) != "PLN":
            return None
        md = convert_order_rate(
            value,
            unit,
            RateUnit.daily,
            order.billing_hours_per_month or contract.billing_hours_per_month or 168,
            scale=CONTRACT_RATE_SCALE,
        )
        if md is None:
            return None
        md = md.quantize(GROSZ, rounding=ROUND_HALF_UP)
    return value, md


@dataclass(frozen=True)
class RevenueChange:
    order_id: int
    order_group_id: Optional[int]
    order_number: Optional[str]
    unit: str
    currency: str
    effective_from: date
    first_month: date
    old_rate: Optional[Decimal]
    new_rate: Decimal
    old_md_rate: Optional[Decimal]
    new_md_rate: Optional[Decimal]


def _label(order: ClientOrder, groups: dict[int, ClientOrderGroup]) -> Optional[str]:
    if order.order_group_id is not None and order.order_group_id in groups:
        return groups[order.order_group_id].order_number
    return (order.title or "").strip() or None


def _fmt(value: Optional[Decimal]) -> str:
    return "—" if value is None else f"{Decimal(value):.2f}"


async def apply_annex_client_rate(
    db: AsyncSession,
    contract: Contract,
    *,
    rate: Decimal,
    effective_from: date,
    amendment_id: Optional[int],
    actor_id: Optional[int],
    dry_run: bool = False,
) -> list[RevenueChange]:
    """Wpisz stawkę klienta z aneksu do żywych zamówień kontraktu.

    ``dry_run=True`` — tylko policz (podgląd w oknie aneksu)."""

    orders = list(
        await db.scalars(
            select(ClientOrder)
            .where(
                ClientOrder.contract_id == contract.id,
                ClientOrder.client_id == contract.client_id,
                ClientOrder.status.in_(LIVE_STATUSES),
                ClientOrder.start_date.is_not(None),
                ClientOrder.start_date < effective_from,
                (ClientOrder.end_date.is_(None))
                | (ClientOrder.end_date >= effective_from),
            )
            .order_by(ClientOrder.start_date, ClientOrder.id)
        )
    )
    if not orders:
        return []
    steps = await load_steps(db, (o.id for o in orders))
    group_ids = {o.order_group_id for o in orders if o.order_group_id is not None}
    groups: dict[int, ClientOrderGroup] = {}
    if group_ids:
        groups = {
            g.id: g
            for g in await db.scalars(
                select(ClientOrderGroup).where(ClientOrderGroup.id.in_(group_ids))
            )
        }

    changes: list[RevenueChange] = []
    day_before = effective_from - timedelta(days=1)
    for order in orders:
        converted = order_rates_from_contract(Decimal(rate), contract, order)
        if converted is None:
            continue
        new_rate, new_md = converted
        own = steps.get(order.id, [])
        old_rate, old_md = rates_on(order, own, day_before)
        same_day = next((s for s in own if s.effective_from == effective_from), None)
        current_rate = same_day.rate_client if same_day else old_rate
        current_md = same_day.md_rate_revenue if same_day else old_md
        if (
            current_rate is not None
            and Decimal(current_rate) == new_rate
            and (
                new_md is None
                or (current_md is not None and Decimal(current_md) == new_md)
            )
        ):
            continue
        change = RevenueChange(
            order_id=order.id,
            order_group_id=order.order_group_id,
            order_number=_label(order, groups),
            unit=RateUnit(order.rate_unit).value,
            currency=_currency(order),
            effective_from=effective_from,
            first_month=first_priced_month(effective_from),
            old_rate=Decimal(old_rate) if old_rate is not None else None,
            new_rate=new_rate,
            old_md_rate=Decimal(old_md) if old_md is not None else None,
            new_md_rate=new_md,
        )
        changes.append(change)
        if dry_run:
            continue
        note = (
            f"Aneks w kontrakcie #{contract.id}"
            if amendment_id is None
            else f"Aneks #{amendment_id} w kontrakcie #{contract.id}"
        )
        if same_day is not None:
            same_day.rate_client = new_rate
            same_day.md_rate_revenue = new_md
            same_day.contract_amendment_id = amendment_id
            same_day.note = note
            same_day.created_by = actor_id
        else:
            db.add(
                ClientOrderRevenueStep(
                    order_id=order.id,
                    effective_from=effective_from,
                    rate_client=new_rate,
                    md_rate_revenue=new_md,
                    contract_amendment_id=amendment_id,
                    note=note,
                    created_by=actor_id,
                )
            )
        if order.order_group_id is not None:
            unit_label = "zł/MD" if new_md is not None else change.unit
            shown_old = change.old_md_rate if new_md is not None else change.old_rate
            shown_new = new_md if new_md is not None else new_rate
            db.add(
                ClientOrderGroupEvent(
                    group_id=order.order_group_id,
                    order_id=order.id,
                    event_type=EVENT_TYPE,
                    description=(
                        f"Zmiana stawki przychodowej od {effective_from:%d.%m.%Y}: "
                        f"{_fmt(shown_old)} → {_fmt(shown_new)} {unit_label} "
                        f"(aneks w kontrakcie #{contract.id})."
                    ),
                    payload={
                        "kind": EVENT_KIND,
                        "contract_id": contract.id,
                        "amendment_id": amendment_id,
                        "effective_from": effective_from.isoformat(),
                        "old_rate_client": _fmt(change.old_rate),
                        "new_rate_client": _fmt(new_rate),
                        "old_md_rate_revenue": _fmt(change.old_md_rate),
                        "new_md_rate_revenue": _fmt(new_md),
                    },
                    created_by_user_id=actor_id,
                )
            )
    return changes


def current_rates(
    order: ClientOrder, steps: Sequence[ClientOrderRevenueStep], today: date
) -> dict[str, Any]:
    """Pola do listy zamówień: stawka na dziś i kroki (bez kroków — pusto)."""

    if not steps:
        return {"revenue_steps": []}
    rate_client, md = rates_on(order, steps, today)
    return {
        "current_rate_client": rate_client,
        "current_md_rate_revenue": md,
        "revenue_steps": [
            {
                "effective_from": s.effective_from,
                "rate_client": s.rate_client,
                "md_rate_revenue": s.md_rate_revenue,
                "first_month": first_priced_month(s.effective_from),
            }
            for s in sorted(steps, key=lambda s: s.effective_from)
        ],
    }
