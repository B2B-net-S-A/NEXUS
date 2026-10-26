"""Szczegóły administracyjne umowy z Generatora (decyzje Artura 26.10.2026).

* Rekruter i Delivery Lead są TYLKO do odczytu: to odbiorcy premii
  z placementu, liczeni tą samą regułą co automat premii
  (``services/hr/placement_bonuses.load_context``): rekruter = „Prowadzi”,
  a bez przypisania pierwszy weryfikujący; DL = DL rekrutacji, potem
  prowadzący rekrutację z rolą DL, potem główny DL klienta. Umowę może
  wygenerować każdy, ale placement i premie zostają przy tych osobach.
* Wpisuje się replacement (za czyj kontrakt) i wymiar FTE. Przy umowie
  powiązanej z rekrutacją oba są obowiązkowe; podpis kopiuje je do
  kontraktu fill-only.
* Prowadzący zapisuje się w ``recruiter_user_id`` wiersza (adresat
  przypomnień o podpisie) i dostaje dzwonek, gdy umowę wygenerował ktoś inny.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr.placement_bonuses import load_context
from app.services.notification_triggers import emit
from app.services.pair_owner import owner_ids
from app.services.polish_ilike import polish_folded_ilike

#: Wymiar etatu w kafelku — ten sam słownik pilnuje CHECK w bazie (0524).
FTE_VALUES: tuple[Decimal, ...] = (
    Decimal("1"),
    Decimal("0.75"),
    Decimal("0.5"),
    Decimal("0.25"),
)
#: Kontrakty, które można wskazać jako zastąpione (bez szkiców i anulowanych).
REPLACEABLE_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
    ContractStatus.ended,
)

# Etykiety źródła wartości przy polu — w kafelku i w kontrakcie.
RECRUITER_SOURCE_LABELS = {
    "pair_owner": "prowadzi kandydata („Prowadzi”)",
    "verifier": "pierwsza weryfikacja na Tablicy",
}
DL_SOURCE_LABELS = {
    "job": "DL rekrutacji",
    "job_lead": "prowadzi rekrutację (rola DL)",
    "client_head": "główny DL klienta",
    "client_assignment": "DL klienta",
}

_REPLACEMENT_IN_TITLE = re.compile(r"zast[ęe]pstw|replacement", re.IGNORECASE)
# „zastępstwo za: Zofia Przykładowa”, „Replacement for Adam (40001)”.
_REPLACED_NAME_IN_TITLE = re.compile(
    r"(?:zast[ęe]pstw\w*|replacement)\s*(?:za|for)?\s*:?\s*"
    r"([^\W\d_][\w-]+(?:\s+[^\W\d_][\w-]+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlacementPerson:
    user_id: int
    name: str
    source: str
    source_label: str


@dataclass(frozen=True)
class PlacementPeople:
    recruiter: Optional[PlacementPerson]
    delivery_lead: Optional[PlacementPerson]


@dataclass(frozen=True)
class ReplaceableContract:
    contract_id: int
    candidate_id: Optional[int]
    client_id: Optional[int]
    name: str
    client_name: Optional[str]
    job_title: Optional[str]
    status: str
    start_date: Optional[date]
    end_date: Optional[date]


@dataclass(frozen=True)
class ReplacementSuggestion:
    from_title: bool
    contract: Optional[ReplaceableContract]


async def placement_people(
    db: AsyncSession, *, candidate_id: int, job: Job
) -> PlacementPeople:
    """Kto dostanie placement i premie za parę — przed powstaniem kontraktu.

    Reguła żyje w ``placement_bonuses``; tu podajemy jej kontrakt-szkic
    (niezapisany), bo czyta z niego tylko kandydata, rekrutację i klienta.
    """

    probe = Contract(candidate_id=candidate_id, job_id=job.id, client_id=job.client_id)
    context = await load_context(db, [probe])
    dl_id, recruiter_id, dl_source = context.people(probe)
    owners = await owner_ids(db, [(candidate_id, job.id)])
    recruiter_source = (
        "pair_owner"
        if owners.get((candidate_id, job.id)) == recruiter_id
        else "verifier"
    )
    wanted = [uid for uid in (recruiter_id, dl_id) if uid is not None]
    names: dict[int, str] = {}
    if wanted:
        rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
        names = {uid: name for uid, name in rows.all()}

    def person(uid: Optional[int], source: str, labels: dict[str, str]):
        if uid is None:
            return None
        return PlacementPerson(
            user_id=uid,
            name=names.get(uid) or f"Użytkownik #{uid}",
            source=source,
            source_label=labels.get(source, ""),
        )

    return PlacementPeople(
        recruiter=person(recruiter_id, recruiter_source, RECRUITER_SOURCE_LABELS),
        delivery_lead=person(dl_id, dl_source, DL_SOURCE_LABELS),
    )


def _contract_end(contract: Contract) -> Optional[date]:
    return contract.terminated_at or contract.end_date


async def replaceable_contracts(
    db: AsyncSession,
    *,
    client_id: Optional[int] = None,
    query: Optional[str] = None,
    contract_ids: Optional[list[int]] = None,
    exclude_candidate_id: Optional[int] = None,
    limit: int = 50,
) -> list[ReplaceableContract]:
    """Kontraktorzy do „Replacement za kogo” — najpierw ci, którzy odeszli.

    Bez kwot: kafelek widzą role bez dostępu do stawek. Kolejność: zakończeni
    i kończący się (najświeższy koniec pierwszy), potem aktywni.
    """

    full_name = func.concat_ws(" ", Candidate.name, Candidate.lastname)
    stmt = (
        select(Contract, full_name, Client.name, Job.title)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .outerjoin(Job, Job.id == Contract.job_id)
        .where(Contract.status.in_(REPLACEABLE_STATUSES))
    )
    if client_id is not None:
        stmt = stmt.where(Contract.client_id == client_id)
    if contract_ids is not None:
        stmt = stmt.where(Contract.id.in_(contract_ids))
    if exclude_candidate_id is not None:
        stmt = stmt.where(Contract.candidate_id != exclude_candidate_id)
    needle = (query or "").strip()
    if needle:
        stmt = stmt.where(polish_folded_ilike(full_name, needle))
    stmt = stmt.order_by(
        (Contract.status == ContractStatus.active).asc(),
        func.coalesce(Contract.terminated_at, Contract.end_date).desc().nulls_last(),
        Contract.id.desc(),
    ).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        ReplaceableContract(
            contract_id=contract.id,
            candidate_id=contract.candidate_id,
            client_id=contract.client_id,
            name=name or f"Kontrakt #{contract.id}",
            client_name=client_name,
            job_title=job_title,
            status=getattr(contract.status, "value", contract.status),
            start_date=contract.start_date,
            end_date=_contract_end(contract),
        )
        for contract, name, client_name, job_title in rows
    ]


async def replacement_suggestion(
    db: AsyncSession, *, candidate_id: int, job: Job
) -> ReplacementSuggestion:
    """Zastępstwo z tytułu rekrutacji („…zastępstwo za: Zofia Przykładowa”).

    175 rekrutacji z ostatniego roku (staging 22.10.2026) mówi o tym w tytule.
    Osobę wskazujemy tylko wtedy, gdy u klienta jest dokładnie jeden pasujący
    kontraktor — inaczej „Tak” bez osoby, wybór zostaje człowiekowi.
    """

    title = job.title or ""
    if not _REPLACEMENT_IN_TITLE.search(title):
        return ReplacementSuggestion(from_title=False, contract=None)
    match = _REPLACED_NAME_IN_TITLE.search(title)
    if match is None or job.client_id is None:
        return ReplacementSuggestion(from_title=True, contract=None)
    found = await replaceable_contracts(
        db,
        client_id=job.client_id,
        query=match.group(1),
        exclude_candidate_id=candidate_id,
        limit=2,
    )
    people = {item.candidate_id for item in found}
    return ReplacementSuggestion(
        from_title=True, contract=found[0] if len(people) == 1 else None
    )


async def apply_admin_details(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    is_replacement: Optional[bool],
    replaced_contract_id: Optional[int],
    fte: Optional[Decimal],
    candidate_id: Optional[int],
    linked: bool,
) -> None:
    """Zapis replacementu i FTE w wierszu umowy (walidacja przy generowaniu).

    Przy umowie powiązanej z rekrutacją oba pola są obowiązkowe. Umowa
    ręczna (bez rekrutacji) zapisuje to, co przyszło.
    """

    if linked and (is_replacement is None or fte is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Uzupełnij „Szczegóły administracyjne”: replacement i wymiar FTE "
                "są obowiązkowe."
            ),
        )
    if not is_replacement:
        replaced_contract_id = None
    elif replaced_contract_id is None:
        if linked:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Wskaż w „Replacement za kogo”, kogo zastępuje ta osoba.",
            )
    else:
        replaced = await db.get(Contract, replaced_contract_id)
        if replaced is None or replaced.status not in REPLACEABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Wskazanego kontraktu nie ma albo nie był zawarty.",
            )
        if candidate_id is not None and replaced.candidate_id == candidate_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Osoba nie może być replacementem samej siebie.",
            )
    row.is_replacement = is_replacement
    row.replaced_contract_id = replaced_contract_id
    row.fte = fte


def copy_admin_details_to_contract(
    contract: Contract, row: B2BGeneratedContract
) -> list[str]:
    """Podpis: replacement i FTE z umowy do kontraktu, fill-only.

    Zwraca nazwy uzupełnionych pól (do audytu). Wpisane już w kontrakcie
    wygrywają — kontrakt jest od podpisu źródłem tych danych.
    """

    filled: list[str] = []
    if contract.fte is None and row.fte is not None:
        contract.fte = row.fte
        filled.append("fte")
    if contract.is_replacement is None and row.is_replacement is not None:
        contract.is_replacement = row.is_replacement
        filled.append("is_replacement")
        if (
            row.is_replacement
            and contract.replaced_contract_id is None
            and row.replaced_contract_id not in (None, contract.id)
        ):
            contract.replaced_contract_id = row.replaced_contract_id
            filled.append("replaced_contract_id")
    return filled


async def notify_pair_owner(
    db: AsyncSession,
    row: B2BGeneratedContract,
    *,
    owner: Optional[PlacementPerson],
    actor: User,
    job: Job,
    person_name: str,
) -> bool:
    """Dzwonek do prowadzącego, gdy umowę jego osoby wygenerował ktoś inny."""

    if owner is None or owner.user_id == actor.id:
        return False
    recipient = await db.get(User, owner.user_id)
    if recipient is None or not recipient.is_active:
        return False
    await emit(
        db,
        user_id=recipient.id,
        title=f"Umowa {row.contract_number} gotowa — {person_name}",
        message=(
            f"{actor.name} wygenerował(a) umowę {row.contract_number} "
            f"({person_name}, „{job.title}”). Prowadzisz tę osobę: wyślij umowę "
            "i dopilnuj podpisu — placement i premia są Twoje."
        ),
        ntype=NotificationType.b2b_agreement_ready,
        related_entity_type="b2b_generated_contract",
        related_entity_id=row.id,
        link=f"/jobs/{job.id}?candidate={row.candidate_id}",
    )
    return True


def replaceable_payload(item: ReplaceableContract) -> dict:
    return {
        "contract_id": item.contract_id,
        "candidate_id": item.candidate_id,
        "client_id": item.client_id,
        "name": item.name,
        "client_name": item.client_name,
        "job_title": item.job_title,
        "status": item.status,
        "start_date": item.start_date,
        "end_date": item.end_date,
    }


def _person_payload(person: Optional[PlacementPerson]) -> Optional[dict]:
    if person is None:
        return None
    return {
        "user_id": person.user_id,
        "name": person.name,
        "source": person.source,
        "source_label": person.source_label,
    }


async def admin_defaults(db: AsyncSession, *, candidate_id: int, job: Job) -> dict:
    """Kafelek po wybraniu rekrutacji: odbiorcy premii i zastępstwo z tytułu."""

    people = await placement_people(db, candidate_id=candidate_id, job=job)
    suggestion = await replacement_suggestion(db, candidate_id=candidate_id, job=job)
    client = await db.get(Client, job.client_id) if job.client_id else None
    return {
        "client_id": job.client_id,
        "client_name": (client.display_name or client.name) if client else None,
        "recruiter": _person_payload(people.recruiter),
        "delivery_lead": _person_payload(people.delivery_lead),
        "replacement_from_title": suggestion.from_title,
        "replaced": (
            replaceable_payload(suggestion.contract) if suggestion.contract else None
        ),
    }
