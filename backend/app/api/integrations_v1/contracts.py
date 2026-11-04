"""Kontrakty w API integracyjnym v1 (scope ``contracts:read``).

Kształt jest węższy niż widok ekranu (ponad 60 pól) — to umowa z
automatyzacjami: osoba, klient, okres, status, jednostka i waluta stawki.
Kwoty według poziomu klucza (``common.amount_level``): stawka do klienta ze
``sales_amounts:read``, stawka konsultanta i marża dopiero z ``amounts:read``
(jak „Stawki i kwoty: podgląd” u ludzi). Bez kwot ``rates`` = ``null``
i ``amounts_redacted = true``; bez kosztów pola kosztowe w ``rates`` są
``null`` i ``costs_redacted = true``. Stawki z harmonogramów na dzień firmy
(``effective_rate_fields``), nigdy z cache'owanych kolumn.

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

from app.api.deps import Caller
from app.api.integrations_v1.common import (
    AmountLevel,
    ContractsRead,
    IdPath,
    IntegrationRoute,
    Money,
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
from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus
from app.services.client_identity import client_display_name
from app.services.contract_candidate_contact import resolve_for_contract
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields

router = APIRouter(route_class=IntegrationRoute)


class PersonOut(BaseModel):
    candidate_id: Optional[int]
    name: Optional[str]
    email: Optional[str]


class ContractRatesOut(BaseModel):
    """Stawki obowiązujące dnia ``as_of`` (z harmonogramów).

    Stawka konsultanta i marża (``rate_candidate``, ``margin`` i ich
    miesięczne odpowiedniki) są ``null`` bez ``amounts:read``."""

    as_of: date
    rate_candidate: Money
    rate_client: Money
    margin: Money
    monthly_rate_candidate: Money
    monthly_rate_client: Money
    monthly_margin: Money


class ContractOut(BaseModel):
    id: int
    status: str
    contract_type: Optional[str]
    engagement_model: Optional[str]
    person: PersonOut
    client_id: Optional[int]
    client_name: Optional[str]
    job_id: Optional[int]
    project_code: Optional[str]
    project_name: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    terminated_at: Optional[date]
    rate_unit: Optional[str]
    billing_hours_per_month: Optional[int]
    rate_client_currency: Optional[str]
    rate_candidate_currency: Optional[str]
    amounts_redacted: bool
    costs_redacted: bool
    rates: Optional[ContractRatesOut]
    updated_at: datetime


class RateStepOut(BaseModel):
    rate: Money
    effective_from: date
    effective_to: Optional[date] = None
    source_order_id: Optional[int] = None


class RateHistoryOut(BaseModel):
    """``candidate`` (stawki konsultanta) jest pusty, gdy ``costs_redacted``."""

    contract_id: int
    rate_unit: Optional[str]
    rate_client_currency: Optional[str]
    rate_candidate_currency: Optional[str]
    candidate: list[RateStepOut]
    client: list[RateStepOut]
    costs_redacted: bool


def _value(raw) -> Optional[str]:
    if raw is None:
        return None
    return getattr(raw, "value", raw)


def _dec(raw) -> Optional[Decimal]:
    return None if raw is None else Decimal(str(raw))


def contract_out(contract: Contract, *, level: AmountLevel, on: date) -> ContractOut:
    contact = resolve_for_contract(contract)
    candidate = contract.candidate
    costs = level is AmountLevel.all
    rates: Optional[ContractRatesOut] = None
    if level >= AmountLevel.sales:
        fields = effective_rate_fields(contract, on)

        def cost(name: str) -> Optional[Decimal]:
            return _dec(fields[name]) if costs else None

        rates = ContractRatesOut(
            as_of=on,
            rate_candidate=cost("rate_candidate"),
            rate_client=_dec(fields["rate_client"]),
            margin=cost("margin"),
            monthly_rate_candidate=cost("monthly_rate_candidate"),
            monthly_rate_client=_dec(fields["monthly_rate_client"]),
            monthly_margin=cost("monthly_margin"),
        )
    return ContractOut(
        id=contract.id,
        status=_value(contract.status) or "",
        contract_type=_value(contract.contract_type),
        engagement_model=_value(contract.engagement_model),
        person=PersonOut(
            candidate_id=contract.candidate_id,
            name=(
                f"{candidate.name} {candidate.lastname}".strip() if candidate else None
            ),
            email=contact.email,
        ),
        client_id=contract.client_id,
        client_name=client_display_name(contract.client) if contract.client else None,
        job_id=contract.job_id,
        project_code=contract.project_code,
        project_name=contract.project_name,
        start_date=contract.start_date,
        end_date=contract.end_date,
        terminated_at=contract.terminated_at,
        rate_unit=_value(contract.rate_unit),
        billing_hours_per_month=contract.billing_hours_per_month,
        rate_client_currency=contract.resolved_rate_client_currency,
        rate_candidate_currency=contract.resolved_rate_candidate_currency,
        amounts_redacted=level is AmountLevel.none,
        costs_redacted=not costs,
        rates=rates,
        updated_at=contract.updated_at,
    )


def _base_query(level: AmountLevel):
    options = [selectinload(Contract.candidate), selectinload(Contract.client)]
    if level >= AmountLevel.sales:
        options.extend(RATE_SCHEDULE_LOADS)
    return select(Contract).options(*options)


@router.get("/contracts", response_model=Page[ContractOut], summary="Lista kontraktów")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_contracts(
    request: Request,
    caller: ContractsRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    status: Optional[list[ContractStatus]] = Query(None),
    client_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    active_on: Optional[date] = Query(
        None, description="Tylko umowy trwające tego dnia (start ≤ dzień ≤ koniec)."
    ),
    updated_since: Optional[datetime] = Query(None),
) -> dict:
    """Kontrakty sortowane po id. ``void`` (anulowane) tylko przez filtr ``status``."""
    level = amount_level(caller)
    query = _base_query(level)
    if status:
        query = query.where(Contract.status.in_(status))
    else:
        query = query.where(Contract.status != ContractStatus.void)
    if client_id is not None:
        query = query.where(Contract.client_id == client_id)
    if active_on is not None:
        query = query.where(
            and_(
                or_(Contract.start_date.is_(None), Contract.start_date <= active_on),
                or_(Contract.end_date.is_(None), Contract.end_date >= active_on),
            )
        )
    if updated_since is not None:
        query = query.where(Contract.updated_at >= updated_since)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    contracts = (
        (
            await db.execute(
                query.order_by(Contract.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    today = business_today()
    items = [contract_out(c, level=level, on=today) for c in contracts]
    return page_of(items, page=page, page_size=page_size, total=total)


async def _load(db: AsyncSession, contract_id: int, level: AmountLevel) -> Contract:
    contract = (
        (await db.execute(_base_query(level).where(Contract.id == contract_id)))
        .scalars()
        .unique()
        .one_or_none()
    )
    if contract is None:
        raise HTTPException(404, detail="Kontrakt nie istnieje.")
    return contract


@router.get("/contracts/{contract_id}", response_model=ContractOut, summary="Kontrakt")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_contract(
    request: Request,
    contract_id: IdPath,
    caller: ContractsRead,
    db: AsyncSession = Depends(get_db),
    as_of: Optional[date] = Query(
        None, description="Stawki na ten dzień (domyślnie dziś)."
    ),
) -> ContractOut:
    level = amount_level(caller)
    contract = await _load(db, contract_id, level)
    return contract_out(contract, level=level, on=as_of or business_today())


def _require_amounts(caller: Caller) -> AmountLevel:
    level = amount_level(caller)
    if level is AmountLevel.none:
        raise HTTPException(
            403,
            detail={
                "error": "insufficient_scope",
                "message": (
                    "Historia stawek wymaga scope'u sales_amounts:read "
                    "(stawki do klienta) albo amounts:read (wszystkie stawki)."
                ),
                "required": ["sales_amounts:read"],
                "missing": ["sales_amounts:read"],
            },
        )
    return level


@router.get(
    "/contracts/{contract_id}/rate-history",
    response_model=RateHistoryOut,
    summary="Historia stawek kontraktu",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def contract_rate_history(
    request: Request,
    contract_id: IdPath,
    caller: ContractsRead,
    db: AsyncSession = Depends(get_db),
) -> RateHistoryOut:
    """Kroki harmonogramów stawek (od najstarszego). Stawki do klienta ze
    ``sales_amounts:read``; stawki konsultanta (``candidate``) tylko
    z ``amounts:read`` — bez niego lista jest pusta i ``costs_redacted = true``."""
    level = _require_amounts(caller)
    costs = level is AmountLevel.all
    contract = await _load(db, contract_id, level)
    return RateHistoryOut(
        contract_id=contract.id,
        rate_unit=_value(contract.rate_unit),
        rate_client_currency=contract.resolved_rate_client_currency,
        rate_candidate_currency=contract.resolved_rate_candidate_currency,
        candidate=[
            RateStepOut(
                rate=_dec(step.rate),
                effective_from=step.effective_from,
                effective_to=getattr(step, "effective_to", None),
            )
            for step in sorted(
                (contract.candidate_rate_schedule or []) if costs else [],
                key=lambda s: s.effective_from,
            )
        ],
        client=[
            RateStepOut(
                rate=_dec(step.rate),
                effective_from=step.effective_from,
                source_order_id=getattr(step, "source_order_id", None),
            )
            for step in sorted(
                contract.client_rate_schedule or [], key=lambda s: s.effective_from
            )
        ],
        costs_redacted=not costs,
    )
