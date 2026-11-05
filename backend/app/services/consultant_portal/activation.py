"""Aktywacja panelu konsultanta: ręcznie, przez człowieka, po podpisaniu umowy.

Panel nie powstaje sam (decyzja Artura 05.11.2026). Link z maila jest jedynym krokiem
logowania, więc adres potwierdza osoba aktywująca i to on trafia do
``contracts.candidate_email``: stamtąd czyta go ``identity``. Adres innej osoby z aktywnym
panelem to odmowa, bo ``identity`` i tak by go nie otworzył.

Wyłączenie zostawia wiersz (kto, kiedy) i od razu zamyka sesje tego kontraktu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.consultant_panel import CpActivation
from app.models.consultant_portal import CpSession
from app.models.contract import Contract, ContractStatus
from app.models.user import User
from app.services.consultant_portal import identity
from app.services.consultant_portal.auth import PortalError

CONTRACT_NOT_FOUND = "Nie ma takiego kontraktu."
CONTRACT_NOT_LIVE = "Panel można aktywować tylko przy działającym kontrakcie."
EMAIL_TAKEN = (
    "Ten adres ma inna osoba z aktywnym panelem. Podaj adres tego konsultanta."
)
NOT_ACTIVE = "Panel tego kontraktu nie jest aktywny."

#: Szkic to umowa przed podpisem, a kontrakt z datą startu w przyszłości jest już aktywny.
ACTIVATABLE = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class ActivationState:
    active: bool
    email: Optional[str]
    activated_at: Optional[datetime]
    activated_by: Optional[str]
    deactivated_at: Optional[datetime]
    last_login_at: Optional[datetime]


async def _row(db: AsyncSession, contract_id: int) -> Optional[CpActivation]:
    return await db.scalar(
        select(CpActivation).where(CpActivation.contract_id == contract_id)
    )


async def suggested_email(db: AsyncSession, contract: Contract) -> Optional[str]:
    """Adres z kontraktu, a bez niego z kartoteki: ten sam porządek co na umowie."""

    if (contract.candidate_email or "").strip():
        return contract.candidate_email.strip()
    if contract.candidate_id is None:
        return None
    candidate = await db.get(Candidate, contract.candidate_id)
    return (candidate.email or "").strip() or None if candidate else None


async def state_for(db: AsyncSession, contract_id: int) -> ActivationState:
    row = await _row(db, contract_id)
    if row is None:
        return ActivationState(False, None, None, None, None, None)
    actor = await db.get(User, row.activated_by) if row.activated_by else None
    last_login = await db.scalar(
        select(func.max(CpSession.created_at)).where(
            CpSession.contract_id == contract_id
        )
    )
    return ActivationState(
        active=row.deactivated_at is None,
        email=row.email,
        activated_at=row.activated_at,
        activated_by=actor.name if actor else None,
        deactivated_at=row.deactivated_at,
        last_login_at=last_login,
    )


async def _email_taken(db: AsyncSession, contract: Contract, email: str) -> bool:
    """Czy adres należy już do innej osoby z aktywnym panelem."""

    rows = (
        await db.execute(
            select(Contract.id, Contract.candidate_id)
            .join(CpActivation, CpActivation.contract_id == Contract.id)
            .where(
                func.lower(Contract.candidate_email) == email,
                CpActivation.deactivated_at.is_(None),
                Contract.id != contract.id,
            )
        )
    ).all()
    return any(
        contract.candidate_id is None or candidate_id != contract.candidate_id
        for _id, candidate_id in rows
    )


async def activate(
    db: AsyncSession, contract_id: int, *, email: str, actor: User, now: datetime
) -> CpActivation:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise PortalError(CONTRACT_NOT_FOUND, status=404, code="contract_not_found")
    if contract.status not in ACTIVATABLE:
        raise PortalError(CONTRACT_NOT_LIVE, status=409, code="contract_not_live")
    address = identity.normalize_email(email)
    if await _email_taken(db, contract, address):
        raise PortalError(EMAIL_TAKEN, status=409, code="email_taken")
    contract.candidate_email = address
    row = await _row(db, contract_id)
    if row is None:
        row = CpActivation(
            contract_id=contract_id,
            email=address,
            activated_by=actor.id,
            activated_at=now,
        )
        db.add(row)
    else:
        row.email = address
        row.activated_by = actor.id
        row.activated_at = now
        row.deactivated_at = None
        row.deactivated_by = None
    await db.flush()
    return row


async def deactivate(
    db: AsyncSession, contract_id: int, *, actor: User, now: datetime
) -> CpActivation:
    row = await _row(db, contract_id)
    if row is None or row.deactivated_at is not None:
        raise PortalError(NOT_ACTIVE, status=409, code="not_active")
    row.deactivated_at = now
    row.deactivated_by = actor.id
    await db.execute(
        update(CpSession)
        .where(CpSession.contract_id == contract_id, CpSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()
    return row
