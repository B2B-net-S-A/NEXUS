"""Koszt zamówienia od dnia zmiany stawki Partnera (0741, decyzja Artura 19.11.2026).

Zgłoszenie: zamówienie Nordei 284887 trwa 01.07–15.12.2026 i ma jedną stawkę
kosztową. Aneks podniósł stawkę Partnera ze 120 na 130 zł/h od 01.09 i na 140
od 01.11, a synchronizacja kontrakt → zamówienie wpisała 140 na cały okres
(zamówienie niesie jedną liczbę: stawkę na „dziś”). Podział na nowe wiersze
odpadł: do zamówienia są przypięte faktury sprzedaży za każdy miesiąc, PDF
i opis do faktury.

Reguły:

* **Żywe zamówienie (szkic, aktywne, wstrzymane, poza zbiorczymi) ma części
  kosztu z harmonogramu kontraktu.** Synchronizacja (`contract_order_sync`)
  przelicza je razem z kolumną; wiersze są tylko przy co najmniej dwóch
  różnych stawkach w okresie, a pierwsza część zaczyna się w dniu startu
  zamówienia. Kolumna ``rate_candidate`` zostaje stawką na dzień odniesienia
  (``cost_reference_day``), więc każdy czytnik bez części liczy jak dotąd.
* **Zakończone zamówienie jest zapisem tego, co rozliczono** — synchronizacja
  go nie rusza. Gdy harmonogram kontraktu zmienił się wstecz w jego okresie,
  zamówienie trafia na listę Finansów „Do korekty po zmianie stawki”:
  „Ustaw koszt z kontraktu” zapisuje części (``source='finance'``) i kolumnę,
  „Zostaw” zapamiętuje decyzję przy tym harmonogramie (podpis); kolejna zmiana
  stawki w tym okresie przywraca zamówienie na listę.
* **Miesiąc liczy się stawką z jego pierwszego dnia** — jak kroki przychodu
  (`order_revenue_steps`); czytniki pieniędzy „za miesiąc” biorą stawkę przez
  `order_revenue_steps.priced_for_month` / `priced_one`, które nakładają oba
  rodzaje kroków.
* Linie zamówień zbiorczych (``order_group_id``) są poza zakresem, jak w całej
  synchronizacji kosztu: ich stawkę prowadzi Delivery Lead, a rozjazd z
  kontraktem pokazuje nocny raport `rate_divergence_report`.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.work_time import HOURS_PER_MONTH, MD_PER_MONTH_DEC
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_cost_step import ClientOrderCostReview, ClientOrderCostStep
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.order_rate_snapshots import contract_rate_in_unit

Part = tuple[date, Decimal]

#: Różnica poniżej grosza to reszta z przeliczenia jednostek.
TOLERANCE = Decimal("0.01")
#: Jak daleko wstecz lista Finansów szuka zakończonych zamówień.
HISTORY_DAYS = 180


def _same(a: Optional[Decimal], b: Optional[Decimal]) -> bool:
    if a is None or b is None:
        return a is b
    return abs(Decimal(a) - Decimal(b)) < TOLERANCE


def contract_parts(contract: Contract, order: Any) -> list[Part]:
    """Wszystkie części kosztu okresu zamówienia z harmonogramu kontraktu.

    Pusta lista = nie da się policzyć bez zgadywania (brak okresu, jednostki
    albo stawki w którymś dniu). Wymaga wczytanego ``candidate_rate_schedule``.
    """

    start, end = order.start_date, order.end_date
    if start is None or order.rate_unit is None:
        return []
    if end is not None and end < start:
        return []
    days = {start} | {
        step.effective_from
        for step in contract.candidate_rate_schedule or ()
        if step.effective_from > start and (end is None or step.effective_from <= end)
    }
    parts: list[Part] = []
    for day in sorted(days):
        rate = contract.effective_candidate_rate(day)
        value = contract_rate_in_unit(rate, contract, RateUnit(order.rate_unit))
        if value is None or value <= 0:
            return []
        if parts and _same(parts[-1][1], value):
            continue
        parts.append((day, value))
    return parts


def steps_for(parts: Sequence[Part]) -> list[Part]:
    """Wiersze do zapisu: tylko gdy w okresie są co najmniej dwie stawki."""

    return list(parts) if len(parts) >= 2 else []


def rate_on(order: Any, steps: Sequence[Any], day: date) -> Optional[Decimal]:
    """Stawka kosztowa zamówienia w dniu ``day`` (jednostka zamówienia).

    Dzień przed pierwszą częścią (miesięczny czytnik pyta o 1. dzień miesiąca,
    a zamówienie zaczęło się 15.) czyta pierwszą część, nie kolumnę — kolumna
    żywego zamówienia to stawka na dziś."""

    if not steps:
        return order.rate_candidate
    ordered = sorted(steps, key=lambda s: s.effective_from)
    current = ordered[0]
    for step in ordered:
        if step.effective_from <= day:
            current = step
    return current.rate_candidate


def order_parts(order: Any, steps: Sequence[Any]) -> list[Part]:
    """Części kosztu zapisane w zamówieniu (bez wierszy — jedna, z kolumny)."""

    if steps:
        return [
            (s.effective_from, Decimal(s.rate_candidate))
            for s in sorted(steps, key=lambda s: s.effective_from)
        ]
    if order.start_date is None or order.rate_candidate is None:
        return []
    return [(order.start_date, Decimal(order.rate_candidate))]


async def load_steps(
    db: AsyncSession, order_ids: Iterable[int]
) -> dict[int, list[ClientOrderCostStep]]:
    ids = sorted({int(i) for i in order_ids if i is not None})
    if not ids:
        return {}
    out: dict[int, list[ClientOrderCostStep]] = defaultdict(list)
    for step in await db.scalars(
        select(ClientOrderCostStep)
        .where(ClientOrderCostStep.order_id.in_(ids))
        .order_by(ClientOrderCostStep.effective_from)
    ):
        out[step.order_id].append(step)
    return dict(out)


async def write_steps(
    db: AsyncSession,
    order: ClientOrder,
    wanted: Sequence[Part],
    existing: Sequence[ClientOrderCostStep],
    *,
    source: str,
    actor_id: Optional[int],
) -> bool:
    """Ustaw wiersze części zamówienia. Zapis tylko przy różnicy; True = zmiana."""

    have = [(s.effective_from, Decimal(s.rate_candidate)) for s in existing]
    if len(have) == len(wanted) and all(
        d1 == d2 and _same(r1, r2) for (d1, r1), (d2, r2) in zip(have, wanted)
    ):
        return False
    if existing:
        await db.execute(
            delete(ClientOrderCostStep).where(ClientOrderCostStep.order_id == order.id)
        )
    for day, rate in wanted:
        db.add(
            ClientOrderCostStep(
                order_id=order.id,
                effective_from=day,
                rate_candidate=rate,
                source=source,
                created_by=actor_id,
            )
        )
    return True


def parts_label(parts: Sequence[Part], end: Optional[date]) -> list[dict[str, Any]]:
    """Części do odpowiedzi API: od–do i stawka."""

    out = []
    for index, (day, rate) in enumerate(parts):
        nxt = parts[index + 1][0] - timedelta(days=1) if index + 1 < len(parts) else end
        out.append({"from": day, "to": nxt, "rate": rate})
    return out


# ── Lista Finansów „Do korekty po zmianie stawki” ────────────────────────────


def _months(start: date, end: date) -> list[date]:
    month = start.replace(day=1)
    if month < start:
        # Miesiąc liczy się stawką z pierwszego dnia; zamówienie zaczęte
        # w środku miesiąca ma ten miesiąc wyceniony stawką ze startu.
        out = [start]
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        out = []
    while month <= end:
        out.append(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _rate_at(parts: Sequence[Part], day: date) -> Optional[Decimal]:
    current = None
    for start, rate in parts:
        if start <= day:
            current = rate
    return current


def _units_per_month(order: Any) -> Decimal:
    unit = RateUnit(order.rate_unit)
    if unit == RateUnit.hourly:
        return Decimal(order.billing_hours_per_month or HOURS_PER_MONTH)
    if unit == RateUnit.daily:
        return MD_PER_MONTH_DEC
    return Decimal(1)


def signature(parts: Sequence[Part]) -> str:
    raw = ";".join(f"{day.isoformat()}={Decimal(rate):.3f}" for day, rate in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class Correction:
    order: ClientOrder
    contract: Contract
    in_order: list[Part]
    in_contract: list[Part]
    months: list[dict[str, Any]]
    estimate: Decimal
    signature: str


def correction_for(
    order: ClientOrder, contract: Contract, steps: Sequence[Any]
) -> Optional[Correction]:
    """Różnica kosztu zakończonego zamówienia z harmonogramem kontraktu albo None."""

    wanted = contract_parts(contract, order)
    have = order_parts(order, steps)
    if not wanted or not have or order.end_date is None:
        return None
    months = []
    estimate = Decimal(0)
    units = _units_per_month(order)
    for month in _months(order.start_date, order.end_date):
        a, b = _rate_at(have, month), _rate_at(wanted, month)
        if a is None or b is None or _same(a, b):
            continue
        diff = Decimal(b) - Decimal(a)
        estimate += diff * units
        months.append(
            {
                "month": month.strftime("%Y-%m"),
                "in_order": a,
                "in_contract": b,
                "diff": diff,
            }
        )
    if not months:
        return None
    return Correction(
        order=order,
        contract=contract,
        in_order=have,
        in_contract=wanted,
        months=months,
        estimate=estimate,
        signature=signature(wanted),
    )


async def list_corrections(db: AsyncSession, *, today: date) -> list[Correction]:
    """Zakończone zamówienia (ostatnie pół roku), których koszt rozjechał się
    z harmonogramem kontraktu, bez decyzji „Zostaw” przy tym harmonogramie."""

    from app.services.contract_rates import RATE_SCHEDULE_LOADS

    orders = list(
        await db.scalars(
            select(ClientOrder)
            .join(Contract, Contract.id == ClientOrder.contract_id)
            .where(
                ClientOrder.status == ClientOrderStatus.completed,
                ClientOrder.order_group_id.is_(None),
                ClientOrder.client_id == Contract.client_id,
                ClientOrder.start_date.is_not(None),
                ClientOrder.end_date >= today - timedelta(days=HISTORY_DAYS),
                ClientOrder.rate_candidate.is_not(None),
                ClientOrder.rate_unit.is_not(None),
                Contract.status != ContractStatus.void,
            )
            .order_by(ClientOrder.end_date.desc(), ClientOrder.id)
        )
    )
    if not orders:
        return []
    contracts = {
        c.id: c
        for c in await db.scalars(
            select(Contract)
            .where(Contract.id.in_({o.contract_id for o in orders}))
            .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
        )
    }
    steps = await load_steps(db, (o.id for o in orders))
    reviews = {
        r.order_id: r.signature
        for r in await db.scalars(
            select(ClientOrderCostReview).where(
                ClientOrderCostReview.order_id.in_([o.id for o in orders])
            )
        )
    }
    out = []
    for order in orders:
        contract = contracts.get(order.contract_id)
        if contract is None or (
            contract.rate_candidate is None and not contract.candidate_rate_schedule
        ):
            continue
        found = correction_for(order, contract, steps.get(order.id, []))
        if found is None or reviews.get(order.id) == found.signature:
            continue
        out.append(found)
    return out


async def apply_correction(
    db: AsyncSession, order: ClientOrder, contract: Contract, *, actor_id: int
) -> Correction:
    """„Ustaw koszt z kontraktu” na zakończonym zamówieniu."""

    existing = (await load_steps(db, [order.id])).get(order.id, [])
    found = correction_for(order, contract, existing)
    if found is None:
        raise LookupError("Koszt tego zamówienia zgadza się już z kontraktem.")
    await write_steps(
        db,
        order,
        steps_for(found.in_contract),
        existing,
        source="finance",
        actor_id=actor_id,
    )
    # Kolumna = stawka z ostatniego dnia (jak `cost_reference_day` zakończonego).
    order.rate_candidate = found.in_contract[-1][1]
    order.rate_candidate_currency = contract.resolved_rate_candidate_currency
    await db.execute(
        delete(ClientOrderCostReview).where(ClientOrderCostReview.order_id == order.id)
    )
    return found


async def dismiss_correction(
    db: AsyncSession, order: ClientOrder, contract: Contract, *, actor_id: int
) -> Correction:
    """„Zostaw” — decyzja Finansów przy obecnym harmonogramie."""

    existing = (await load_steps(db, [order.id])).get(order.id, [])
    found = correction_for(order, contract, existing)
    if found is None:
        raise LookupError("Koszt tego zamówienia zgadza się już z kontraktem.")
    review = await db.get(ClientOrderCostReview, order.id)
    if review is None:
        db.add(
            ClientOrderCostReview(
                order_id=order.id, signature=found.signature, decided_by=actor_id
            )
        )
    else:
        review.signature = found.signature
        review.decided_by = actor_id
    return found
