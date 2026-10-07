"""Stawki konsultanta u klienta: godzinowo z zamówienia, marża w PLN.

Wydzielone 08.10.2026 z api/clients.py (profil klienta), bo te same liczby
czyta przegląd Delivery Leada przed wysłaniem CV (D9: mediana marży i zakres
stawek konsultantów u klienta). Reguły bez zmian — profil klienta importuje
je pod starymi nazwami.

* order_hourly_leg — stawka ZAMÓWIENIA za godzinę (linia MD w PLN/MD ÷ 8,
  zamówienie okresowe w swojej jednostce), None = brak zamówienia/stawki;
* finance_rates_in_pln — obie nogi kontraktu przeliczone OSOBNO na PLN,
  kolumny godzinowe najpierw z zamówienia, marża miesięczna z kontraktu;
* contract_hourly — stawka kosztowa kontraktu PLN/h na dzień (historia
  stawek kandydata, „ostatni kontrakt” w przeglądzie DL);
* client_consultant_summary — agregaty obecnych konsultantów u klienta
  (bez nazwisk i kwot pojedynczych osób).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.work_time import HOURS_PER_MONTH
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.contractor_identity import is_current_contract
from app.services.fx_service import amount_to_pln_with_rate, rates_to_pln
from app.services.order_rate_snapshots import convert_order_rate
from app.services.representative_order import representative_order


def contract_rate_currencies(contract: Contract) -> tuple[str, str]:
    """Return the independently resolved client and candidate currencies."""

    return (
        contract.resolved_rate_client_currency,
        contract.resolved_rate_candidate_currency,
    )


def hourly_rate(contract: Contract, rate: object) -> Optional[Decimal]:
    """Stawka KONTRAKTU za godzinę — zapasowe źródło kolumn profilu klienta.

    Używane, gdy kontrakt nie ma zamówienia albo zamówienie nie niesie danej
    stawki (patrz ``order_hourly_leg``). Od 14.09.2026 kontrakt jest godzinowy
    albo ryczałtowy (``contract_order_sync``): godzinowa bez przeliczenia,
    ryczałt ÷ godziny rozliczeniowe kontraktu, MD ÷ 8 tylko dla kontraktu
    sprzed korekty 0309. Nic nie jest zapisywane.
    """
    if rate is None:
        return None
    return convert_order_rate(
        rate,
        RateUnit(contract.rate_unit),
        RateUnit.hourly,
        contract.billing_hours_per_month or HOURS_PER_MONTH,
    )


HourlyLeg = tuple[Decimal, str]


def order_currency(order: ClientOrder, side: str) -> str:
    raw = (
        order.rate_client_currency
        if side == "revenue"
        else order.rate_candidate_currency
    )
    return str(raw or order.currency or "PLN").strip().upper() or "PLN"


def order_hourly_leg(order: Optional[ClientOrder], side: str) -> Optional[HourlyLeg]:
    """Stawka ZAMÓWIENIA za godzinę (kwota w walucie zamówienia) — albo ``None``.

    Lustro tego, co pokazuje zakładka „Zamówienia": linia zamówienia MD/kosztowego
    niesie kanoniczną stawkę PLN/MD w ``md_rate_*`` (waluta obca → ``rate_*``
    w jednostce linii, jak ``source_rate_*`` w ``client_order_groups``), a
    zamówienie okresowe — ``rate_client``/``rate_candidate`` w swojej
    ``rate_unit``. Godzinowa bez przeliczenia, MD ÷ 8 (``convert_order_rate``).
    Kontrakt bywa z zamówieniem rozjechany (linie MD, których stawki nie
    zsynchronizowały się do kontraktu — zmierzone na prodzie 14.09.2026), a
    ticket wymaga wartości Z ZAMÓWIENIA. ``None`` = brak zamówienia albo brak
    tej stawki na nim; wołający cofa się wtedy na kontrakt.
    """
    if order is None:
        return None
    currency = order_currency(order, side)
    order_rate = order.rate_client if side == "revenue" else order.rate_candidate
    md_rate = order.md_rate_revenue if side == "revenue" else order.md_rate_cost
    if order.order_group_id is not None and currency == "PLN" and md_rate is not None:
        amount, unit = md_rate, RateUnit.daily
    elif order_rate is not None:
        default_unit = (
            RateUnit.daily if order.order_group_id is not None else RateUnit.hourly
        )
        amount, unit = order_rate, RateUnit(order.rate_unit or default_unit)
    else:
        return None
    hourly = convert_order_rate(
        amount, unit, RateUnit.hourly, order.billing_hours_per_month or HOURS_PER_MONTH
    )
    if hourly is None:
        return None
    return hourly, currency


def finance_rates_in_pln(
    contract: Contract,
    rate_fields: dict[str, object],
    fx_rates: dict[str, Optional[Decimal]],
    order: Optional[ClientOrder] = None,
) -> dict[str, object]:
    """Convert both monthly rate legs independently and derive a PLN margin.

    ``effective_rate_fields`` deliberately leaves mixed-currency margin empty,
    because subtracting the nominal amounts would be meaningless. Client
    profile amounts are ``WholePLN`` fields, so this surface resolves both legs
    to PLN first. A missing FX rate stays ``None`` and is reported through the
    two internal flags so aggregates can fail closed instead of publishing a
    partial total as complete.
    """

    client_currency, candidate_currency = contract_rate_currencies(contract)
    raw_client = rate_fields.get("monthly_rate_client")
    raw_candidate = rate_fields.get("monthly_rate_candidate")
    client_fx = fx_rates.get(client_currency)
    candidate_fx = fx_rates.get(candidate_currency)

    client_pln, client_complete = amount_to_pln_with_rate(raw_client, client_fx)
    candidate_pln, candidate_complete = amount_to_pln_with_rate(
        raw_candidate, candidate_fx
    )
    client_missing_fx = not client_complete
    candidate_missing_fx = not candidate_complete
    margin_pln = (
        client_pln - candidate_pln
        if client_pln is not None and candidate_pln is not None
        else None
    )
    # Kolumny godzinowe: najpierw ZAMÓWIENIE (wartość z ticketu), a gdy go
    # nie ma albo nie niesie tej stawki — kontrakt. Marża zostaje miesięczna
    # z kontraktu (kafel „Aktywne MRR" jest jej sumą).
    hourly: dict[str, Optional[Decimal]] = {}
    for side, rate_key, contract_currency in (
        ("revenue", "rate_client", client_currency),
        ("cost", "rate_candidate", candidate_currency),
    ):
        leg = order_hourly_leg(order, side) or (
            (hourly_rate(contract, rate_fields.get(rate_key)), contract_currency)
        )
        hourly[side], _ = amount_to_pln_with_rate(leg[0], fx_rates.get(leg[1]))
    hourly_client_pln = hourly["revenue"]
    hourly_candidate_pln = hourly["cost"]
    return {
        "monthly_rate_client": client_pln,
        "monthly_rate_candidate": candidate_pln,
        "monthly_margin": margin_pln,
        "hourly_rate_client": hourly_client_pln,
        "hourly_rate_candidate": hourly_candidate_pln,
        "client_missing_fx": client_missing_fx,
        "candidate_missing_fx": candidate_missing_fx,
    }


def contract_hourly(contract: Contract, on: date) -> Optional[Decimal]:
    """Stawka KOSZTOWA kontraktu w PLN/h na dzień on (None poza PLN).

    Dzień ÷ 8, ryczałt ÷ godziny rozliczeniowe kontraktu (168 domyślnie).
    Wymaga harmonogramów stawek (RATE_SCHEDULE_LOADS).
    """
    fields = effective_rate_fields(contract, on)
    if str(fields.get("rate_candidate_currency") or "PLN").upper() != "PLN":
        return None
    rate = fields.get("rate_candidate")
    if rate is None:
        return None
    rate = Decimal(str(rate))
    unit = contract.rate_unit
    if unit == RateUnit.hourly:
        return rate.quantize(Decimal("0.01"))
    if unit == RateUnit.daily:
        return (rate / Decimal(8)).quantize(Decimal("0.01"))
    hours = Decimal(contract.billing_hours_per_month or HOURS_PER_MONTH)
    return (rate / hours).quantize(Decimal("0.01"))


# ── Agregaty konsultantów u klienta (przegląd DL, D9) ───────────────────────


@dataclass(frozen=True)
class ConsultantRates:
    """Godzinowe stawki jednego obecnego konsultanta w PLN."""

    contract_id: int
    category_id: Optional[int]
    cost_hourly: Optional[Decimal]
    revenue_hourly: Optional[Decimal]

    @property
    def margin_hourly(self) -> Optional[Decimal]:
        if self.cost_hourly is None or self.revenue_hourly is None:
            return None
        return self.revenue_hourly - self.cost_hourly


@dataclass
class ClientConsultantSummary:
    """Agregaty bez nazwisk: mediana marży u klienta i w kategorii."""

    consultants: int = 0
    client_margin_median_hourly: Optional[Decimal] = None
    category_count: int = 0
    category_cost_min: Optional[Decimal] = None
    category_cost_max: Optional[Decimal] = None
    category_revenue_min: Optional[Decimal] = None
    category_revenue_max: Optional[Decimal] = None
    category_margin_median_hourly: Optional[Decimal] = None
    rates: list[ConsultantRates] = field(default_factory=list)


def _median(values: Iterable[Optional[Decimal]]) -> Optional[Decimal]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return Decimal(str(statistics.median(clean))).quantize(Decimal("0.01"))


def summarize(
    rates: list[ConsultantRates], category_id: Optional[int]
) -> ClientConsultantSummary:
    """Czysta część agregatów — testowana bez bazy."""
    out = ClientConsultantSummary(consultants=len(rates), rates=list(rates))
    out.client_margin_median_hourly = _median(r.margin_hourly for r in rates)
    if category_id is None:
        return out
    same = [r for r in rates if r.category_id == category_id]
    out.category_count = len(same)
    costs = [r.cost_hourly for r in same if r.cost_hourly is not None]
    revenues = [r.revenue_hourly for r in same if r.revenue_hourly is not None]
    out.category_cost_min = min(costs) if costs else None
    out.category_cost_max = max(costs) if costs else None
    out.category_revenue_min = min(revenues) if revenues else None
    out.category_revenue_max = max(revenues) if revenues else None
    out.category_margin_median_hourly = _median(r.margin_hourly for r in same)
    return out


async def client_consultant_summary(
    db: AsyncSession,
    *,
    client_ids: Iterable[int],
    category_id: Optional[int],
    today: date,
) -> ClientConsultantSummary:
    """Obecni konsultanci klientów client_ids (rodzina scalonych klientów).

    Stała liczba zapytań: kontrakty z zamówieniami i harmonogramami, kursy NBP.
    Kategoria = główna kategoria kompetencji kandydata kontraktu.
    """
    ids = sorted({int(c) for c in client_ids if c is not None})
    if not ids:
        return ClientConsultantSummary()
    contracts = (
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.client_id.in_(ids),
                    Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
                )
                .options(selectinload(Contract.client_orders), *RATE_SCHEDULE_LOADS)
            )
        )
        .scalars()
        .all()
    )
    current = [
        c
        for c in contracts
        if is_current_contract(
            c,
            today,
            fallback_start=getattr(representative_order(c, today), "start_date", None),
        )
    ]
    if not current:
        return ClientConsultantSummary()
    categories: dict[int, Optional[int]] = {}
    candidate_ids = sorted({c.candidate_id for c in current if c.candidate_id})
    if candidate_ids:
        categories = dict(
            (
                await db.execute(
                    select(Candidate.id, Candidate.competence_category_id).where(
                        Candidate.id.in_(candidate_ids)
                    )
                )
            ).all()
        )
    fields_by_id = {c.id: effective_rate_fields(c, today) for c in current}
    currencies: set[str] = set()
    for c in current:
        currencies.update(contract_rate_currencies(c))
        order = representative_order(c, today)
        if order is not None:
            currencies.update(
                order_currency(order, side) for side in ("revenue", "cost")
            )
    fx = await rates_to_pln(db, currencies, today)
    rates: list[ConsultantRates] = []
    for c in current:
        legs = finance_rates_in_pln(
            c, fields_by_id[c.id], fx, representative_order(c, today)
        )
        rates.append(
            ConsultantRates(
                contract_id=c.id,
                category_id=categories.get(c.candidate_id),
                cost_hourly=legs["hourly_rate_candidate"],
                revenue_hourly=legs["hourly_rate_client"],
            )
        )
    return summarize(rates, category_id)


__all__ = [
    "ClientConsultantSummary",
    "ConsultantRates",
    "HourlyLeg",
    "client_consultant_summary",
    "contract_hourly",
    "contract_rate_currencies",
    "finance_rates_in_pln",
    "hourly_rate",
    "order_currency",
    "order_hourly_leg",
    "summarize",
]
