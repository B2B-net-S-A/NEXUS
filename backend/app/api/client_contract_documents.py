"""Ekran „Umowy klientów”: lista umów ramowych i aneksów z plikami, bez kwot.

Decyzja Artura 04.11.2026: osoba z administracji ma widzieć umowy z klientami, ale
żadnych stawek na ekranach NEXUSA. Trasy ``/api/clients/{id}/framework-contracts``
wymagają „Stawki i kwoty: podgląd” i sekcji Delivery, które otwierają kwoty
i kontrakty w całym systemie, dlatego ten ekran ma własne uprawnienie i własny
schemat odpowiedzi. Notatki, warunki i odczytany tekst celowo nie wychodzą, bo mogą
nieść stawki. W samych plikach stawki mogą być i właściciel to zaakceptował.
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import ClientContractsViewUser
from app.core.database import get_db
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.user import User
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()

_FILE_MISSING = "Nie znaleziono pliku na serwerze. Zgłoś to administratorowi."


class ClientContractAmendmentRow(BaseModel):
    id: int
    name: str
    effective_date: date
    filename: Optional[str] = None
    has_file: bool


class ClientContractRow(BaseModel):
    id: int
    client_id: int
    client_name: str
    name: str
    status: str
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    filename: Optional[str] = None
    has_file: bool
    amendments: list[ClientContractAmendmentRow]


@router.get("", response_model=list[ClientContractRow])
async def list_client_contracts(
    current_user: ClientContractsViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[ClientContractRow]:
    stmt = (
        select(ClientFrameworkContract, Client.name)
        .join(Client, Client.id == ClientFrameworkContract.client_id)
        .where(Client.deleted_at.is_(None))
        .order_by(
            func.lower(Client.name),
            Client.id,
            ClientFrameworkContract.effective_date.desc().nullslast(),
        )
    )
    # Delivery Lead z tym uprawnieniem zostaje przy klientach ze swojego zakresu.
    allowed = await resolve_delivery_lead_client_ids(current_user, db)
    if allowed is not None:
        stmt = stmt.where(ClientFrameworkContract.client_id.in_(sorted(allowed)))
    rows = (await db.execute(stmt)).all()

    amendments: dict[int, list[ClientContractAmendment]] = {}
    contract_ids = [contract.id for contract, _ in rows]
    if contract_ids:
        amendment_rows = await db.scalars(
            select(ClientContractAmendment)
            .where(ClientContractAmendment.framework_contract_id.in_(contract_ids))
            .order_by(ClientContractAmendment.effective_date.desc().nullslast())
        )
        for amendment in amendment_rows:
            amendments.setdefault(amendment.framework_contract_id, []).append(amendment)

    return [
        ClientContractRow(
            id=contract.id,
            client_id=contract.client_id,
            client_name=client_name,
            name=contract.name,
            status=contract.status.value,
            effective_date=contract.effective_date,
            expiry_date=contract.expiry_date,
            filename=contract.filename,
            has_file=contract.file_path is not None,
            amendments=[
                ClientContractAmendmentRow(
                    id=amendment.id,
                    name=amendment.name,
                    effective_date=amendment.effective_date,
                    filename=amendment.filename,
                    has_file=amendment.file_path is not None,
                )
                for amendment in amendments.get(contract.id, [])
            ],
        )
        for contract, client_name in rows
    ]


async def _visible_contract(
    db: AsyncSession, current_user: User, contract_id: int
) -> ClientFrameworkContract:
    contract = await db.scalar(
        select(ClientFrameworkContract)
        .join(Client, Client.id == ClientFrameworkContract.client_id)
        .where(
            ClientFrameworkContract.id == contract_id,
            Client.deleted_at.is_(None),
        )
    )
    if contract is None:
        raise HTTPException(404, detail="Nie znaleziono umowy.")
    assert_delivery_lead_client_visible(
        contract.client_id, await resolve_delivery_lead_client_ids(current_user, db)
    )
    return contract


@router.get("/{contract_id}/file")
async def download_client_contract(
    contract_id: int,
    current_user: ClientContractsViewUser,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    contract = await _visible_contract(db, current_user, contract_id)
    if contract.file_path is None:
        raise HTTPException(404, detail="Ta umowa nie ma pliku.")
    try:
        path = storage_service.get_client_framework_contract_path(contract.file_path)
    except FileNotFoundError as exc:
        logger.error("Client contract %s: file missing on disk", contract.id)
        raise HTTPException(404, detail=_FILE_MISSING) from exc
    return FileResponse(
        path=str(path),
        filename=contract.filename or "umowa.pdf",
        media_type=contract.content_type or "application/pdf",
    )


@router.get("/{contract_id}/amendments/{amendment_id}/file")
async def download_client_contract_amendment(
    contract_id: int,
    amendment_id: int,
    current_user: ClientContractsViewUser,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    await _visible_contract(db, current_user, contract_id)
    amendment = await db.scalar(
        select(ClientContractAmendment).where(
            ClientContractAmendment.id == amendment_id,
            ClientContractAmendment.framework_contract_id == contract_id,
        )
    )
    if amendment is None or amendment.file_path is None:
        raise HTTPException(404, detail="Ten aneks nie ma pliku.")
    try:
        path = storage_service.get_client_contract_amendment_path(amendment.file_path)
    except FileNotFoundError as exc:
        logger.error("Client contract amendment %s: file missing on disk", amendment.id)
        raise HTTPException(404, detail=_FILE_MISSING) from exc
    return FileResponse(
        path=str(path),
        filename=amendment.filename or "aneks.pdf",
        media_type=amendment.content_type or "application/pdf",
    )
