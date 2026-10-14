"""Zapis kontraktów w API integracyjnym v1 (``contracts:write``).

Te same ciała co rejestr umów — ``apply_contract_update`` i
``apply_contract_status`` (``api/contracts.py``) — z ``IntegrationWritePolicy``
(``api/write_policy.py``). Reguły zostają ekranowe: data końca, która kończy
albo przywraca współpracę, idzie przez te same przejścia stanu (reaktywacja,
korekta daty rozwiązanej umowy, synchronizacja zamówień do końca umowy,
odwołanie zaplanowanego zastępstwa), a status — przez maszynę stanów
(``ended`` tylko oknem „Zakończ współpracę” na ekranie: 409
``termination_required``).

Świadomie węziej niż ekran: ``PATCH`` zmienia wyłącznie ``end_date``. Stawki
kontraktu (harmonogramy) zostają na ekranie — ich zapis zastępuje całe
harmonogramy, a stawki zamówień zmienia ``PATCH /orders/{id}``.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import contracts as contract_routes
from app.api.integrations_v1.common import (
    AmountLevel,
    ContractsStatus,
    ContractsWrite,
    IdPath,
    IntegrationRoute,
    amount_level,
    idempotent_write,
    principal_rate_key,
    write_policy,
    write_rate_limit,
)
from app.api.integrations_v1.contracts import ContractOut, _base_query, contract_out
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus
from app.schemas.contract import ContractStatusUpdate, ContractUpdate

router = APIRouter(route_class=IntegrationRoute)


class ContractPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: Optional[date] = Field(
        ..., description="Ostatni dzień umowy; null = umowa bezterminowa."
    )


class ContractStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "active", "ending", "ended"]


async def _assert_exists(db: AsyncSession, contract_id: int) -> None:
    # Sama kolumna: ciało ładuje kontrakt świeżo, pod `SELECT … FOR UPDATE`.
    found = await db.scalar(select(Contract.id).where(Contract.id == contract_id))
    if found is None:
        raise HTTPException(404, detail="Kontrakt nie istnieje.")


async def _contract_response(
    db: AsyncSession, contract_id: int, *, level: AmountLevel
) -> ContractOut:
    contract = (
        (
            await db.execute(
                _base_query(level)
                .where(Contract.id == contract_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .unique()
        .one()
    )
    return contract_out(contract, level=level, on=business_today())


@router.patch(
    "/contracts/{contract_id}",
    response_model=ContractOut,
    summary="Zmień datę końca kontraktu",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def update_contract(
    request: Request,
    contract_id: IdPath,
    body: ContractPatchIn,
    caller: ContractsWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Jak zmiana daty końca w rejestrze umów. Data skracająca umowę skraca
    też otwarte zamówienia tej osoby; nowa data na zakończonej umowie ją
    przywraca; data wstecz na trwającej umowie kończy ją przy nocnym
    przeliczeniu. Umowa B2B bez zakończenia współpracy daty końca nie
    dostaje (422)."""

    async def run():
        await _assert_exists(db, contract_id)
        contract, _detail = await contract_routes.apply_contract_update(
            contract_id,
            ContractUpdate.model_validate({"end_date": body.end_date}),
            db=db,
            policy=write_policy(caller, db),
        )
        return 200, await _contract_response(
            db, contract.id, level=amount_level(caller)
        )

    return await idempotent_write(
        request,
        db,
        caller,
        payload={"contract_id": contract_id, **body.model_dump(mode="json")},
        run=run,
    )


@router.post(
    "/contracts/{contract_id}/status",
    response_model=ContractOut,
    summary="Zmień status kontraktu",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def update_contract_status(
    request: Request,
    contract_id: IdPath,
    body: ContractStatusIn,
    caller: ContractsStatus,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Przejście stanu jak lista statusu w rejestrze umów: ``active`` sprawdza
    komplet danych (szkic) albo przywraca zakończoną umowę, ``ending`` wymaga
    daty końca, ``draft`` cofa do szkicu. ``ended`` = 409
    ``termination_required`` (zakończenie z powodem jest na ekranie)."""

    async def run():
        await _assert_exists(db, contract_id)
        contract = await contract_routes.apply_contract_status(
            contract_id,
            ContractStatusUpdate(status=ContractStatus(body.status)),
            db=db,
            policy=write_policy(caller, db),
        )
        return 200, await _contract_response(
            db, contract.id, level=amount_level(caller)
        )

    return await idempotent_write(
        request,
        db,
        caller,
        payload={"contract_id": contract_id, "status": body.status},
        run=run,
    )
