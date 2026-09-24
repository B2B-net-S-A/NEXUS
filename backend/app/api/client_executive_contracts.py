"""Router struktury umów wykonawczych Centrum e-Zdrowia.

Trasy (wszystkie pod ``/api/clients/{client_id}``):

- ``GET  /contract-structure`` — umowy ramowe-części z wykonawczymi,
- ``POST /executive-contracts`` — nowa umowa wykonawcza (``active``),
- ``PATCH /executive-contracts/{ec_id}`` — numer / status / notatki,
- ``GET  /executive-contracts/review`` — konsultanci do ręcznego przypisania,
- ``POST /executive-contracts/assignments`` — przypisanie konsultanta.

Bramki jak w ``client_framework_contracts``: cały router za sekcją Delivery
(odczyt — każdy zalogowany z sekcją), zapisy za ``DlAssignedOrAdmin`` (admin
globalnie albo DL przypisany do klienta). Funkcja dotyczy WYŁĄCZNIE Centrum
e-Zdrowia (``is_ezdrowie_client``) — u innego klienta każda trasa odpowiada
422, żeby pusta struktura nie wyglądała jak „jeszcze nic nie dodano".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DlAssignedOrAdmin
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.client import Client
from app.schemas.client_executive_contract import (
    ContractStructureResponse,
    ExecutiveContractAssignmentRequest,
    ExecutiveContractAssignmentResponse,
    ExecutiveContractCreate,
    ExecutiveContractRead,
    ExecutiveContractReviewResponse,
    ExecutiveContractUpdate,
)
from app.services import executive_contracts as service
from app.services.client_access import assert_client_writable
from app.services.ezdrowie import is_ezdrowie_client

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

ONLY_EZDROWIE_MESSAGE = (
    "Struktura umów wykonawczych dotyczy wyłącznie Centrum e-Zdrowia"
)


async def _assert_ezdrowie_client(
    db: AsyncSession, client_id: int, *, write: bool = False
) -> None:
    if write:
        # Zapis tylko na widocznym kliencie: usunięty, scalony albo ukryty
        # → 404 (audyt 24.09.2026, S1).
        await assert_client_writable(db, client_id)
    else:
        client = await db.scalar(select(Client).where(Client.id == client_id))
        # Klient usunięty z profilu (0307) nie ma już profilu ani struktury umów.
        if client is None or client.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Client not found")
    if not is_ezdrowie_client(client_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ONLY_EZDROWIE_MESSAGE,
        )


def _to_read(executive) -> ExecutiveContractRead:
    brief = service.executive_brief(executive)
    return ExecutiveContractRead(
        **brief.model_dump(),
        notes=executive.notes,
        consultants_count=0,
        created_at=executive.created_at,
    )


def _service_error(error: ValueError) -> HTTPException:
    """Duplikat numeru i zakończenie z przypisaniami to stan danych (409);
    reszta odmów opisuje payload (422)."""
    if isinstance(error, service.ExecutiveContractConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
    )


@router.get("/{client_id}/contract-structure", response_model=ContractStructureResponse)
async def get_contract_structure(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_ezdrowie_client(db, client_id)
    return await service.load_structure(db, client_id)


@router.post(
    "/{client_id}/executive-contracts",
    response_model=ExecutiveContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_executive_contract(
    client_id: int,
    payload: ExecutiveContractCreate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_ezdrowie_client(db, client_id, write=True)
    try:
        executive = await service.create_executive_contract(
            db, client_id, payload, user.id
        )
    except ValueError as error:
        raise _service_error(error) from None
    return _to_read(executive)


@router.patch(
    "/{client_id}/executive-contracts/{ec_id}", response_model=ExecutiveContractRead
)
async def update_executive_contract(
    client_id: int,
    ec_id: int,
    payload: ExecutiveContractUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_ezdrowie_client(db, client_id, write=True)
    try:
        executive = await service.update_executive_contract(
            db, client_id, ec_id, payload, user.id
        )
    except ValueError as error:
        raise _service_error(error) from None
    return _to_read(executive)


@router.get(
    "/{client_id}/executive-contracts/review",
    response_model=ExecutiveContractReviewResponse,
)
async def review_executive_contract_assignments(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_ezdrowie_client(db, client_id)
    return await service.review_rows(db, client_id)


@router.post(
    "/{client_id}/executive-contracts/assignments",
    response_model=ExecutiveContractAssignmentResponse,
)
async def assign_executive_contract(
    client_id: int,
    payload: ExecutiveContractAssignmentRequest,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_ezdrowie_client(db, client_id, write=True)
    try:
        return await service.assign_executive_contract(db, client_id, payload, user.id)
    except ValueError as error:
        raise _service_error(error) from None
