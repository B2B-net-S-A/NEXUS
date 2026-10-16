"""Zakres i opiekun w module opieki.

* **Zakres klientów** = zakres Delivery (``access_scope.resolve_delivery_lead_client_ids``):
  Delivery Lead działa u swoich klientów, admin, Finanse i TCM u wszystkich.
  Cudzy klient → 403 z tym samym zdaniem co w Klientach i Kontraktach.
* **Opiekun kontraktu** (decyzja z makiety „Opieka”, 16.10.2026): pole
  kontraktu, a gdy puste — domyślny opiekun klienta, a gdy i tego brak —
  Delivery Lead kontraktu (prowadzący rekrutację, z której przyszedł
  konsultant, albo główny DL klienta).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_care import CLIENTS_CARE, CONTRACTS_CARE
from app.models.job import Job
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    resolve_delivery_lead_client_ids,
)
from app.services.care.plan import end_of_cooperation

#: Role, które prowadzą opiekę (zapis rozmów, kart, przepięć) i mogą być opiekunem.
CARE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
)
#: Kontrakty, przy których opieka trwa (plan, przypomnienia, „Moi konsultanci”).
LIVE_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
)

CONTRACT_NOT_FOUND = "Nie ma takiego kontraktu."
CLIENT_NOT_FOUND = "Nie ma takiego klienta."

_contracts_care = CONTRACTS_CARE.alias("contracts_care")
_clients_care = CLIENTS_CARE.alias("clients_care")


def is_care_worker(user: User) -> bool:
    return user.has_any_role(*CARE_ROLES)


@dataclass(frozen=True)
class CareContract:
    id: int
    client_id: int
    client_name: str
    candidate_id: Optional[int]
    candidate_name: Optional[str]
    job_id: Optional[int]
    job_title: Optional[str]
    job_delivery_lead_id: Optional[int]
    status: str
    start_date: Optional[date]
    contract_end_date: Optional[date]
    order_end_date: Optional[date]
    explicit_owner_id: Optional[int]
    client_default_owner_id: Optional[int]

    @property
    def end_date(self) -> Optional[date]:
        return end_of_cooperation(self.contract_end_date, self.order_end_date)

    @property
    def is_live(self) -> bool:
        return self.status in {value.value for value in LIVE_STATUSES}

    @property
    def label(self) -> str:
        person = self.candidate_name or "Konsultant"
        return f"{person} · {self.client_name}"


def _contract_query():
    return (
        select(
            Contract.id,
            Contract.client_id,
            Client.name,
            Contract.candidate_id,
            Candidate.name,
            Contract.job_id,
            Job.title,
            Job.delivery_lead_id,
            Contract.status,
            Contract.start_date,
            Contract.end_date,
            Contract.client_order_end_date,
            _contracts_care.c.care_owner_user_id,
            _clients_care.c.default_care_owner_user_id,
        )
        .select_from(Contract)
        .join(Client, Client.id == Contract.client_id)
        .join(_contracts_care, _contracts_care.c.id == Contract.id)
        .join(_clients_care, _clients_care.c.id == Contract.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Job, Job.id == Contract.job_id)
    )


def _row_to_contract(row) -> CareContract:
    status_value = row[8].value if hasattr(row[8], "value") else str(row[8])
    return CareContract(
        id=row[0],
        client_id=row[1],
        client_name=row[2],
        candidate_id=row[3],
        candidate_name=row[4],
        job_id=row[5],
        job_title=row[6],
        job_delivery_lead_id=row[7],
        status=status_value,
        start_date=row[9],
        contract_end_date=row[10],
        order_end_date=row[11],
        explicit_owner_id=row[12],
        client_default_owner_id=row[13],
    )


async def allowed_client_ids(user: User, db: AsyncSession) -> frozenset[int] | None:
    """``None`` = wszyscy klienci; zbiór = portfel Delivery Leada."""

    return await resolve_delivery_lead_client_ids(user, db)


def assert_client_in_scope(client_id: int, allowed: frozenset[int] | None) -> None:
    if allowed is not None and client_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DL_CLIENT_OUT_OF_SCOPE_DETAIL)


async def load_contract(db: AsyncSession, contract_id: int, user: User) -> CareContract:
    row = (
        await db.execute(_contract_query().where(Contract.id == contract_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CONTRACT_NOT_FOUND)
    contract = _row_to_contract(row)
    assert_client_in_scope(contract.client_id, await allowed_client_ids(user, db))
    return contract


async def load_client(db: AsyncSession, client_id: int, user: User) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CLIENT_NOT_FOUND)
    assert_client_in_scope(client.id, await allowed_client_ids(user, db))
    return client


async def live_contracts(
    db: AsyncSession,
    *,
    allowed: frozenset[int] | None = None,
    contract_ids: Optional[Iterable[int]] = None,
    client_id: Optional[int] = None,
) -> list[CareContract]:
    """Kontrakty aktywne i kończące się (z datą startu) w zakresie."""

    query = _contract_query().where(
        Contract.status.in_(LIVE_STATUSES),
        Contract.voided_at.is_(None),
    )
    if allowed is not None:
        query = query.where(Contract.client_id.in_(sorted(allowed) or [-1]))
    if contract_ids is not None:
        query = query.where(Contract.id.in_(sorted(set(contract_ids)) or [-1]))
    if client_id is not None:
        query = query.where(Contract.client_id == client_id)
    rows = (await db.execute(query.order_by(Contract.id))).all()
    return [_row_to_contract(row) for row in rows]


async def contracts_by_id(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, CareContract]:
    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    rows = (await db.execute(_contract_query().where(Contract.id.in_(ids)))).all()
    return {row[0]: _row_to_contract(row) for row in rows}


async def _client_head_leads(
    db: AsyncSession, client_ids: Iterable[int]
) -> dict[int, int]:
    """Główny (a bez niego pierwszy) aktywny Delivery Lead klienta."""

    ids = sorted(set(client_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(DeliveryLeadClientAssignment.client_id, User)
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(
                DeliveryLeadClientAssignment.client_id.in_(ids),
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.is_head.desc(),
                DeliveryLeadClientAssignment.id,
            )
        )
    ).all()
    out: dict[int, int] = {}
    for client_id, user in rows:
        if client_id not in out and user.has_role(UserRole.delivery_lead):
            out[client_id] = user.id
    return out


@dataclass(frozen=True)
class OwnerChoice:
    user_id: Optional[int]
    source: Optional[str]  # contract | client | delivery_lead


async def effective_owners(
    db: AsyncSession, contracts: Sequence[CareContract]
) -> dict[int, OwnerChoice]:
    heads = await _client_head_leads(
        db,
        (
            c.client_id
            for c in contracts
            if c.explicit_owner_id is None
            and c.client_default_owner_id is None
            and c.job_delivery_lead_id is None
        ),
    )
    out: dict[int, OwnerChoice] = {}
    for contract in contracts:
        if contract.explicit_owner_id is not None:
            out[contract.id] = OwnerChoice(contract.explicit_owner_id, "contract")
        elif contract.client_default_owner_id is not None:
            out[contract.id] = OwnerChoice(contract.client_default_owner_id, "client")
        elif contract.job_delivery_lead_id is not None:
            out[contract.id] = OwnerChoice(
                contract.job_delivery_lead_id, "delivery_lead"
            )
        elif contract.client_id in heads:
            out[contract.id] = OwnerChoice(heads[contract.client_id], "delivery_lead")
        else:
            out[contract.id] = OwnerChoice(None, None)
    return out


async def owner_candidates(db: AsyncSession) -> list[User]:
    """Aktywne konta, które mogą być opiekunem (admin, DL, TCM)."""

    clauses = []
    for role in CARE_ROLES:
        clauses.append(User.role == role)
        clauses.append(User.roles.contains([role.value]))
    users = (
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), or_(*clauses))
            .order_by(User.name)
        )
    ).all()
    return [user for user in users if is_care_worker(user)]


async def validate_owner(db: AsyncSession, user_id: int, *, client_id: int) -> User:
    """Opiekun musi widzieć klienta — inaczej przypomnienie prowadzi na 403."""

    user = await db.get(User, user_id)
    if user is None or not user.is_active or not is_care_worker(user):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Opiekunem może być aktywny Delivery Lead, Talent Community Manager albo administrator.",
        )
    scope = await allowed_client_ids(user, db)
    if scope is not None and client_id not in scope:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ten Delivery Lead nie ma tego klienta w portfelu.",
        )
    return user


async def user_names(
    db: AsyncSession, user_ids: Iterable[Optional[int]]
) -> dict[int, str]:
    ids = sorted({uid for uid in user_ids if uid is not None})
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {uid: name for uid, name in rows}
