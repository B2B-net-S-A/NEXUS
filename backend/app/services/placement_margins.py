"""Marża placementów na liście „Kto się liczy” (prośba Olafa 27.11.2026).

Zasady (decyzje Artura 27.11.2026, ``docs/claude/finanse-insights/marza-na-liscie-placementow.md``):

* Marża liczy się jak eksport „Placementy” i Płace (``contract_margin``):
  stawka klienta minus stawka kosztowa z kontraktu pary, zł/h z dnia
  startu (bez startu — z dziś), waluta obca po kursie NBP. Miesięcznie =
  marża/h × 168 h.
* Kontrakt bez stawki klienta: stawka „do klienta” z rekrutacji
  (``candidate_stages.client_rate_value``, ostatnia niepusta pary) ze znakiem
  ``client_from_recruitment``. Brak stawki albo kursu = brak liczby, nigdy
  zgadnięta.
* Kto widzi: „Moduł Finanse” (admin, Finanse) — wszystkich klientów; konto
  rządzone portfelem Delivery Leada z „Stawki i kwoty: podgląd” — tylko
  klientów z portfela (``can_read_client_finance``). Reszta, w tym Head of
  Recruitment i TCM, nie dostaje kwot w ogóle (reguła 24.09.2026 „HoR nie
  widzi pieniędzy w Insights”) — także gdy ma podgląd kwot z ekranu uprawnień.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.financial_access import can_read_client_finance, has_financial_access
from app.core.work_time import HOURS_PER_MONTH
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import fx_service
from app.services.access_scope import (
    is_delivery_lead_governed,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr.bonus_rules import money
from app.services.hr.placement_bonuses import contract_margin
from app.services.order_rate_snapshots import CONTRACT_RATE_SCALE, convert_order_rate

Pair = tuple[int, int]
MarginScope = Literal["all", "portfolio"]
MissingReason = Literal["no_contract", "missing_rates", "fx_missing"]


@dataclass(frozen=True)
class MarginAudience:
    """``scope`` None = bez kwot; ``client_ids`` None = każdy klient."""

    scope: Optional[MarginScope]
    client_ids: Optional[frozenset[int]]

    def sees(self, user: User, client_id: int) -> bool:
        if self.scope is None:
            return False
        return can_read_client_finance(
            user,
            client_id=client_id,
            delivery_lead_finance_client_ids=self.client_ids,
        )


async def margin_audience(db: AsyncSession, user: User) -> MarginAudience:
    if has_financial_access(user):
        return MarginAudience("all", None)
    if is_delivery_lead_governed(user) and has_permission(
        user, ProductAction.amounts_view
    ):
        ids = await resolve_delivery_lead_finance_client_ids(user, db)
        # ``None`` u konta z portfelem DL to błąd resolvera — bez kwot.
        if ids is None:
            return MarginAudience(None, None)
        return MarginAudience("portfolio", ids)
    return MarginAudience(None, None)


@dataclass(frozen=True)
class PairMargin:
    cost_per_hour: Optional[Decimal] = None
    client_per_hour: Optional[Decimal] = None
    cost_currency: str = "PLN"
    client_currency: str = "PLN"
    per_hour: Optional[Decimal] = None
    client_from_recruitment: bool = False
    missing: Optional[MissingReason] = None
    # Przychód zł/h po kursie — mianownik procentu marży.
    revenue_pln: Optional[Decimal] = None

    @property
    def per_month(self) -> Optional[Decimal]:
        return None if self.per_hour is None else money(self.per_hour * HOURS_PER_MONTH)

    @property
    def percent(self) -> Optional[Decimal]:
        """Marża w % przychodu (oba w PLN)."""
        if self.per_hour is None or not self.revenue_pln or self.revenue_pln <= 0:
            return None
        return (self.per_hour / self.revenue_pln * 100).quantize(Decimal("0.1"))


def _decimal(raw: object) -> Optional[Decimal]:
    return None if raw in (None, "") else Decimal(str(raw))


async def _contracts(db: AsyncSession, pairs: list[Pair]) -> dict[Pair, Contract]:
    """Kontrakt pary jak „Start” na liście: najpóźniejszy start, bez unieważnionych."""
    rows = (
        (
            await db.execute(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS)
                .where(
                    tuple_(Contract.candidate_id, Contract.job_id).in_(pairs),
                    Contract.status != ContractStatus.void,
                )
                .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
            )
        )
        .scalars()
        .all()
    )
    found: dict[Pair, Contract] = {}
    for contract in rows:
        key = (int(contract.candidate_id), int(contract.job_id))
        found.setdefault(key, contract)
    return found


async def _recruitment_client_rates(
    db: AsyncSession, pairs: list[Pair]
) -> dict[Pair, tuple[Decimal, RateUnit, str]]:
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.client_rate_value,
                CandidateStage.client_rate_unit,
                CandidateStage.client_rate_currency,
            )
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(pairs),
                CandidateStage.client_rate_value.is_not(None),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    found: dict[Pair, tuple[Decimal, RateUnit, str]] = {}
    for candidate_id, job_id, value, unit, currency in rows:
        found.setdefault(
            (int(candidate_id), int(job_id)),
            (
                Decimal(value),
                RateUnit(unit or RateUnit.hourly.value),
                (currency or "PLN").upper(),
            ),
        )
    return found


async def _to_pln(db: AsyncSession, currency: str, on: date) -> Optional[Decimal]:
    if currency == "PLN":
        return Decimal(1)
    rate, found = await fx_service.get_rate_to_pln(db, currency, on)
    return Decimal(rate) if found else None


async def _from_contract(db: AsyncSession, contract: Contract, on: date) -> PairMargin:
    margin = await contract_margin(db, contract, on)
    snapshot = margin.snapshot
    cost = _decimal(snapshot.get("cost_rate_per_hour"))
    client = _decimal(snapshot.get("client_rate_per_hour"))
    client_currency = contract.resolved_rate_client_currency
    fx = snapshot.get("fx_to_pln") or {}
    client_fx = Decimal(str(fx.get(client_currency, 1)))
    return PairMargin(
        cost_per_hour=cost,
        client_per_hour=client,
        cost_currency=contract.resolved_rate_candidate_currency,
        client_currency=client_currency,
        per_hour=margin.per_hour,
        missing=margin.reason,  # type: ignore[arg-type]
        revenue_pln=client * client_fx if client is not None else None,
    )


async def _with_recruitment_rate(
    db: AsyncSession,
    contract: Contract,
    on: date,
    rate: tuple[Decimal, RateUnit, str],
) -> PairMargin:
    hours = contract.billing_hours_per_month or HOURS_PER_MONTH
    unit = RateUnit(getattr(contract.rate_unit, "value", contract.rate_unit))
    cost = convert_order_rate(
        contract.effective_candidate_rate(on),
        unit,
        RateUnit.hourly,
        hours,
        scale=CONTRACT_RATE_SCALE,
    )
    value, client_unit, client_currency = rate
    client = convert_order_rate(
        value, client_unit, RateUnit.hourly, hours, scale=CONTRACT_RATE_SCALE
    )
    cost_currency = contract.resolved_rate_candidate_currency
    base = PairMargin(
        cost_per_hour=cost,
        client_per_hour=client,
        cost_currency=cost_currency,
        client_currency=client_currency,
        client_from_recruitment=True,
    )
    if cost is None or client is None:
        return replace(base, missing="missing_rates")
    cost_fx = await _to_pln(db, cost_currency, on)
    client_fx = await _to_pln(db, client_currency, on)
    if cost_fx is None or client_fx is None:
        return replace(base, missing="fx_missing")
    return replace(
        base,
        per_hour=money(client * client_fx - cost * cost_fx),
        revenue_pln=client * client_fx,
    )


async def pair_margins(
    db: AsyncSession, pairs: Iterable[Pair], today: date
) -> dict[Pair, PairMargin]:
    """Marża każdej pary (kandydat, rekrutacja); stała liczba zapytań + kursy walut."""
    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    contracts = await _contracts(db, wanted)
    recruitment_rates = await _recruitment_client_rates(db, wanted)
    out: dict[Pair, PairMargin] = {}
    for pair in wanted:
        contract = contracts.get(pair)
        if contract is None:
            out[pair] = PairMargin(missing="no_contract")
            continue
        on = contract.start_date or today
        found = await _from_contract(db, contract, on)
        rate = recruitment_rates.get(pair)
        if (
            found.missing == "missing_rates"
            and contract.effective_client_rate(on) is None
            and contract.effective_candidate_rate(on) is not None
            and rate is not None
        ):
            found = await _with_recruitment_rate(db, contract, on, rate)
        out[pair] = found
    return out
