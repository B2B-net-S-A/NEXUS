"""Zakres i opiekun w module opieki.

* **Zakres klientów** = zakres Delivery (``access_scope.resolve_delivery_lead_client_ids``):
  Delivery Lead działa u swoich klientów, admin, Finanse i TCM u wszystkich.
  Cudzy klient → 403 z tym samym zdaniem co w Klientach i Kontraktach.
  „Konsultanci”, rytm i „Przydział” (``rhythm_scope``): head back office
  u wszystkich klientów, także gdy jest Delivery Leadem (O8, O10).
* **Opiekun kontraktu** (decyzja z makiety „Opieka”, 16.10.2026): pole
  kontraktu, a gdy puste — domyślny opiekun klienta, a gdy i tego brak —
  Delivery Lead kontraktu (prowadzący rekrutację, z której przyszedł
  konsultant, albo główny DL klienta). Ogniwo z kontem nieaktywnym przepuszcza
  do następnego — dzwonek do wyłączonego konta nikomu by się nie pokazał.
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
from app.services.hr.lifecycle_templates import is_back_office_head

#: Role, które prowadzą opiekę (zapis rozmów, kart, przepięć) i mogą być opiekunem.
CARE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
)
#: D11: kto widzi strukturę u klienta, opinie klienta i zdrowie relacji
#: (opiekun z roli, DL, Head of Recruitment, admin; Finanse i Kadry nie).
PEOPLE_READER_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.head_of_recruitment,
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


def reads_client_people(user: User) -> bool:
    """Krąg D11: opinie klienta i zdrowie relacji (bramka ``PeopleReader``)."""

    return user.has_any_role(*PEOPLE_READER_ROLES)


async def is_care_writer(db: AsyncSession, user: User) -> bool:
    """Prowadzi opiekę: rola DL, TCM, admin albo osoba z puli opiekunów (18.10.2026).

    Osoba z puli pisze tylko z zapisem w sekcji Delivery — bez niego bramka
    ``CareWriter`` i tak odmawia (zapis = POST/PUT/PATCH w sekcji), a flagi
    ``can_edit`` pokazywałyby przyciski kończące się 403 (audyt 19.10.2026).
    """

    from app.services.care import owner_pool  # noqa: PLC0415
    from app.services.section_permissions import (  # noqa: PLC0415
        ProductSection,
        SectionAccess,
        section_access_for_user,
    )

    if is_care_worker(user):
        return True
    if section_access_for_user(user, ProductSection.delivery) < SectionAccess.write:
        return False
    return user.id in await owner_pool.writer_ids(db)


def full_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    """Imię i nazwisko kandydata (``Candidate.name`` to samo imię)."""

    joined = " ".join(part.strip() for part in (first, last) if part and part.strip())
    return joined or None


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
    #: Forma współpracy kontraktu (``b2b`` | ``uop`` | ``uzlecenie``).
    contract_type: Optional[str] = None

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
            Candidate.lastname,
            Contract.job_id,
            Job.title,
            Job.delivery_lead_id,
            Contract.status,
            Contract.start_date,
            Contract.end_date,
            Contract.client_order_end_date,
            _contracts_care.c.care_owner_user_id,
            _clients_care.c.default_care_owner_user_id,
            Contract.contract_type,
        )
        .select_from(Contract)
        .join(Client, Client.id == Contract.client_id)
        .join(_contracts_care, _contracts_care.c.id == Contract.id)
        .join(_clients_care, _clients_care.c.id == Contract.client_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Job, Job.id == Contract.job_id)
    )


def _value(raw) -> Optional[str]:
    if raw is None:
        return None
    return raw.value if hasattr(raw, "value") else str(raw)


def _row_to_contract(row) -> CareContract:
    status_value = _value(row[9])
    return CareContract(
        id=row[0],
        client_id=row[1],
        client_name=row[2],
        candidate_id=row[3],
        candidate_name=full_name(row[4], row[5]),
        job_id=row[6],
        job_title=row[7],
        job_delivery_lead_id=row[8],
        status=status_value,
        start_date=row[10],
        contract_end_date=row[11],
        order_end_date=row[12],
        explicit_owner_id=row[13],
        client_default_owner_id=row[14],
        contract_type=_value(row[15]),
    )


async def allowed_client_ids(user: User, db: AsyncSession) -> frozenset[int] | None:
    """``None`` = wszyscy klienci; zbiór = portfel Delivery Leada."""

    return await resolve_delivery_lead_client_ids(user, db)


async def rhythm_scope(user: User, db: AsyncSession) -> frozenset[int] | None:
    """Zakres „Konsultantów”, rytmu i „Przydziału”: head back office — wszyscy."""

    if await is_back_office_head(db, user):
        return None
    return await allowed_client_ids(user, db)


def assert_client_in_scope(client_id: int, allowed: frozenset[int] | None) -> None:
    if allowed is not None and client_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DL_CLIENT_OUT_OF_SCOPE_DETAIL)


async def load_contract(
    db: AsyncSession, contract_id: int, user: User, *, rhythm: bool = False
) -> CareContract:
    """Kontrakt w zakresie czytającego (``rhythm`` = zakres ``rhythm_scope``)."""

    row = (
        await db.execute(_contract_query().where(Contract.id == contract_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CONTRACT_NOT_FOUND)
    contract = _row_to_contract(row)
    scope = rhythm_scope if rhythm else allowed_client_ids
    assert_client_in_scope(contract.client_id, await scope(user, db))
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


async def _active_user_ids(db: AsyncSession, user_ids: Iterable[int]) -> set[int]:
    ids = sorted(set(user_ids))
    if not ids:
        return set()
    rows = await db.scalars(
        select(User.id).where(User.id.in_(ids), User.is_active.is_(True))
    )
    return set(rows.all())


def _named_owner(
    contract: CareContract,
    active: set[int],
    lead_scopes: Optional[dict[int, Optional[frozenset[int]]]] = None,
) -> Optional[OwnerChoice]:
    """Pierwsze aktywne ogniwo: kontrakt → domyślny opiekun klienta → DL rekrutacji.

    DL rekrutacji tylko wtedy, gdy klient kontraktu jest w jego portfelu:
    rekrutacje widać w całej firmie, więc DL bywa prowadzącym u cudzego
    klienta — jako opiekun dostawałby dzwonki z linkiem kończącym się 403
    (audyt 19.10.2026). Ręczny przydział sprawdza to samo (``owner_problem``).
    """

    scopes = lead_scopes or {}
    for user_id, source in (
        (contract.explicit_owner_id, "contract"),
        (contract.client_default_owner_id, "client"),
        (contract.job_delivery_lead_id, "delivery_lead"),
    ):
        if user_id is None or user_id not in active:
            continue
        if source == "delivery_lead" and user_id in scopes:
            scope = scopes[user_id]
            if scope is not None and contract.client_id not in scope:
                continue
        return OwnerChoice(user_id, source)
    return None


async def _lead_scopes(
    db: AsyncSession, user_ids: Iterable[int]
) -> dict[int, Optional[frozenset[int]]]:
    """Portfel (``allowed_client_ids``) każdego DL rekrutacji z łańcucha."""

    ids = sorted(set(user_ids))
    if not ids:
        return {}
    users = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {user.id: await allowed_client_ids(user, db) for user in users}


async def effective_owners(
    db: AsyncSession, contracts: Sequence[CareContract]
) -> dict[int, OwnerChoice]:
    active = await _active_user_ids(
        db,
        (
            user_id
            for c in contracts
            for user_id in (
                c.explicit_owner_id,
                c.client_default_owner_id,
                c.job_delivery_lead_id,
            )
            if user_id is not None
        ),
    )
    scopes = await _lead_scopes(
        db,
        (
            c.job_delivery_lead_id
            for c in contracts
            if c.job_delivery_lead_id is not None and c.job_delivery_lead_id in active
        ),
    )
    named = {
        contract.id: _named_owner(contract, active, scopes) for contract in contracts
    }
    heads = await _client_head_leads(
        db, (c.client_id for c in contracts if named[c.id] is None)
    )
    out: dict[int, OwnerChoice] = {}
    for contract in contracts:
        choice = named[contract.id]
        if choice is not None:
            out[contract.id] = choice
        elif contract.client_id in heads:
            out[contract.id] = OwnerChoice(heads[contract.client_id], "delivery_lead")
        else:
            out[contract.id] = OwnerChoice(None, None)
    return out


async def owner_candidates(db: AsyncSession) -> list[User]:
    """Aktywne konta, które mogą być opiekunem: admin, DL, TCM i pula opiekunów.

    Z puli tylko ci, którzy widzą opiekę; osoby z listy wykluczonych
    (``owner_pool``) nie są do wyboru.
    """

    from app.services.care import owner_pool  # noqa: PLC0415

    pool = await owner_pool.eligible_ids(db)
    excluded = await owner_pool.excluded_ids(db)
    clauses = [User.id.in_(sorted(pool) or [-1])]
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
    return [
        user
        for user in users
        if user.id not in excluded and (is_care_worker(user) or user.id in pool)
    ]


OWNER_INVALID = (
    "Opiekunem może być aktywny Delivery Lead, Talent Community Manager, "
    "administrator albo osoba z puli opiekunów."
)


async def owner_problem(
    db: AsyncSession, user: Optional[User], *, client_ids: Iterable[int] = ()
) -> Optional[str]:
    """Dlaczego ta osoba nie może być opiekunem (``None`` = może)."""

    from app.services.care import owner_pool  # noqa: PLC0415

    if user is None or not user.is_active:
        return OWNER_INVALID
    if user.id in await owner_pool.excluded_ids(db):
        return f"{user.name} jest na liście osób, którym nie przypisujemy konsultantów."
    if not is_care_worker(user) and user.id not in await owner_pool.eligible_ids(db):
        return OWNER_INVALID
    scope = await allowed_client_ids(user, db)
    if scope is not None and any(cid not in scope for cid in client_ids):
        return f"{user.name} nie ma tego klienta w portfelu."
    return None


async def validate_owner(db: AsyncSession, user_id: int, *, client_id: int) -> User:
    """Opiekun musi widzieć klienta — inaczej przypomnienie prowadzi na 403."""

    user = await db.get(User, user_id)
    problem = await owner_problem(db, user, client_ids=[client_id])
    if problem is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    return user


async def user_names(
    db: AsyncSession, user_ids: Iterable[Optional[int]]
) -> dict[int, str]:
    ids = sorted({uid for uid in user_ids if uid is not None})
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {uid: name for uid, name in rows}
