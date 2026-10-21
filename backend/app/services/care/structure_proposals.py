"""Propozycje struktury u klienta i ich akceptacja (decyzja Artura 18.10.2026).

„Propozycja automatu + akcept DL”: automat liczy przy odczycie (nic nie
zapisuje), kto jest menedżerem konsultanta u klienta
(``contracts.client_pm_contact_id``) i pod kogo podlega osoba klienta
(``contacts.reports_to_contact_id``). Reguły i punkty źródeł —
``care/structure_rules.py``. Delivery Lead zatwierdza (pojedynczo albo
„Zatwierdź pewne”), zmienia na inną osobę klienta albo pomija
(``client_structure_skips``). Pominięta propozycja wraca, gdy automat
wskaże inną osobę.

Źródła z bazy: pola kontraktu (e-mail PM, „Line Manager”, „PM po stronie
klienta”, zespół), hiring manager rekrutacji kontraktu, osoba kontaktowa
odczytana z zamówienia (``client_orders.invoice_lines.contact``), nadawca
maila z zamówieniem (``order_mail_documents.sender_email``), dział z ostatniej
karty technologicznej (``tech_cards.client_area_id`` — tylko odczyt)
i menedżerowie kolegów, których DL już zatwierdził.

Do klientów nic nie wychodzi — prośby o opinię liczą się przy odczycie
(``client_people.feedback_requests``), formularza do klienta nie ma (D10).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.client_structure import ClientStructureSkip
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import CONTACTS_ORG, ClientArea, TechCard
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.order_mail import OrderMailDocument
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import contract_client_manager
from app.services.care import access as care_access
from app.services.care import structure_rules as rules
from app.services.care.access import CareContract
from app.services.client_access import record_client_audit
from app.services.hr import audit

#: Najwięcej pozycji w jednym zatwierdzeniu (front wysyła „Zatwierdź pewne”).
APPLY_MAX = 200
#: Alternatywy pokazywane przy propozycji (poza najmocniejszym kandydatem).
ALTERNATIVES_SHOWN = 3
STRUCTURE_REMINDER_EVERY_DAYS = 7

_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY

FOREIGN_CONTRACT = "Konsultant nie pracuje u tego klienta."
CONTRACT_NOT_LIVE = "Kontrakt nie jest aktywny — menedżera wskaż w kontrakcie."
CONTACT_NOT_FOUND = "Nie ma takiej osoby u tego klienta."
TOO_MANY = f"Najwyżej {APPLY_MAX} pozycji naraz."
BOTH_INPUTS = "Wybierz osobę z listy albo wpisz nową — nie oba naraz."
NO_INPUT = "Wybierz osobę klienta albo wpisz nową."

_contacts_org = CONTACTS_ORG.alias("contacts_org")


# ── Wczytanie danych ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClientData:
    client_id: int
    client_name: str
    contracts: tuple[CareContract, ...]
    #: Kontrakt → wpisany menedżer (``None`` = brak albo kontakt innego klienta).
    managers: dict[int, Optional[int]]
    #: Kontrakt → kontakt innego klienta wpisany przed walidacją D8.
    outside: frozenset[int]
    facts: dict[int, rules.ContractFacts]
    people: tuple[rules.PersonRow, ...]
    areas: dict[int, str]
    skips: dict[tuple[str, int], ClientStructureSkip]


async def _people(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, list[rules.PersonRow]]:
    out: dict[int, list[rules.PersonRow]] = {cid: [] for cid in client_ids}
    rows = (
        await db.execute(
            select(
                Contact.id,
                Contact.client_id,
                Contact.name,
                Contact.position,
                Contact.department,
                Contact.email,
                _contacts_org.c.client_area_id,
                _contacts_org.c.reports_to_contact_id,
            )
            .join(_contacts_org, _contacts_org.c.id == Contact.id)
            .where(Contact.client_id.in_(client_ids))
            .order_by(Contact.id)
        )
    ).all()
    for row in rows:
        out[row[1]].append(
            rules.PersonRow(
                id=row[0],
                name=row[2],
                position=row[3],
                department=row[4],
                email=row[5],
                area_id=row[6],
                reports_to_id=row[7],
            )
        )
    return out


async def load(
    db: AsyncSession, *, client_ids: Optional[Iterable[int]]
) -> dict[int, ClientData]:
    """Dane propozycji dla klientów (``None`` = wszyscy z żywymi kontraktami)."""

    allowed = None if client_ids is None else frozenset(client_ids)
    contracts = await care_access.live_contracts(db, allowed=allowed)
    ids = sorted(
        {c.client_id for c in contracts}
        | (set(allowed) if allowed is not None else set())
    )
    if not ids:
        return {}
    names = {
        row[0]: row[1]
        for row in (
            await db.execute(select(Client.id, Client.name).where(Client.id.in_(ids)))
        ).all()
    }
    people = await _people(db, ids)
    contact_client = {p.id: cid for cid, group in people.items() for p in group}
    contract_ids = [c.id for c in contracts]

    fields: dict[int, tuple] = {}
    job_hm: dict[int, Optional[int]] = {}
    order_contacts: dict[int, list[str]] = {}
    order_senders: dict[int, list[str]] = {}
    card_area: dict[int, int] = {}
    if contract_ids:
        fields = {
            row[0]: row[1:]
            for row in (
                await db.execute(
                    select(
                        Contract.id,
                        Contract.client_pm_contact_id,
                        Contract.line_manager,
                        Contract.client_pm_name,
                        Contract.client_pm_email,
                        Contract.team_name,
                    ).where(Contract.id.in_(contract_ids))
                )
            ).all()
        }
        job_ids = sorted({c.job_id for c in contracts if c.job_id is not None})
        if job_ids:
            job_hm = {
                row[0]: row[1]
                for row in (
                    await db.execute(
                        select(Job.id, Job.hiring_manager_contact_id).where(
                            Job.id.in_(job_ids)
                        )
                    )
                ).all()
            }
        for contract_id, contact in (
            await db.execute(
                select(
                    ClientOrder.contract_id, ClientOrder.invoice_lines["contact"].astext
                ).where(
                    ClientOrder.contract_id.in_(contract_ids),
                    ClientOrder.invoice_lines.is_not(None),
                )
            )
        ).all():
            if contact:
                order_contacts.setdefault(contract_id, []).append(contact)
        for contract_id, sender in (
            await db.execute(
                select(ClientOrder.contract_id, OrderMailDocument.sender_email)
                .join(
                    OrderMailDocument,
                    OrderMailDocument.applied_order_id == ClientOrder.id,
                )
                .where(
                    ClientOrder.contract_id.in_(contract_ids),
                    OrderMailDocument.sender_email.is_not(None),
                )
            )
        ).all():
            order_senders.setdefault(contract_id, []).append(sender)
        # Dział konsultanta = obszar z najnowszej karty technologicznej z obszarem.
        for contract_id, area_id in (
            await db.execute(
                select(TechCard.contract_id, TechCard.client_area_id)
                .where(
                    TechCard.contract_id.in_(contract_ids),
                    TechCard.client_area_id.is_not(None),
                )
                .order_by(
                    TechCard.contract_id,
                    TechCard.interview_on.desc(),
                    TechCard.id.desc(),
                )
            )
        ).all():
            card_area.setdefault(contract_id, area_id)
    areas = {
        row[0]: (row[1], row[2])
        for row in (
            await db.execute(
                select(ClientArea.id, ClientArea.client_id, ClientArea.name).where(
                    ClientArea.client_id.in_(ids)
                )
            )
        ).all()
    }
    skips: dict[int, dict[tuple[str, int], ClientStructureSkip]] = {
        cid: {} for cid in ids
    }
    for skip in (
        await db.scalars(
            select(ClientStructureSkip).where(ClientStructureSkip.client_id.in_(ids))
        )
    ).all():
        subject = skip.contract_id if skip.kind == "manager" else skip.contact_id
        if subject is not None:
            skips[skip.client_id][(skip.kind, subject)] = skip

    out: dict[int, ClientData] = {}
    for client_id in ids:
        mine = tuple(c for c in contracts if c.client_id == client_id)
        managers: dict[int, Optional[int]] = {}
        outside: set[int] = set()
        facts: dict[int, rules.ContractFacts] = {}
        for contract in mine:
            pm_id, line_manager, pm_name, pm_email, team = fields.get(
                contract.id, (None, None, None, None, None)
            )
            if pm_id is not None and contact_client.get(pm_id) != client_id:
                outside.add(contract.id)
                pm_id = None
            managers[contract.id] = pm_id
            hm = job_hm.get(contract.job_id) if contract.job_id is not None else None
            area_id = card_area.get(contract.id)
            area = areas.get(area_id) if area_id is not None else None
            facts[contract.id] = rules.ContractFacts(
                contract_id=contract.id,
                client_id=client_id,
                line_manager=line_manager,
                client_pm_name=pm_name,
                client_pm_email=pm_email,
                team_name=team,
                job_id=contract.job_id,
                job_title=contract.job_title,
                job_hm_contact_id=hm
                if hm is not None and contact_client.get(hm) == client_id
                else None,
                order_contacts=tuple(
                    dict.fromkeys(order_contacts.get(contract.id, ()))
                ),
                order_senders=tuple(dict.fromkeys(order_senders.get(contract.id, ()))),
                area_id=area_id if area and area[0] == client_id else None,
                area_name=area[1] if area and area[0] == client_id else None,
            )
        out[client_id] = ClientData(
            client_id=client_id,
            client_name=names.get(client_id, ""),
            contracts=mine,
            managers=managers,
            outside=frozenset(outside),
            facts=facts,
            people=tuple(people.get(client_id, ())),
            areas={aid: name for aid, (cid, name) in areas.items() if cid == client_id},
            skips=skips[client_id],
        )
    return out


# ── Propozycje ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManagerItem:
    contract: CareContract
    proposal: rules.Proposal
    skipped: Optional[ClientStructureSkip]
    outside: bool
    #: „Dodaj X jako menedżera” — osoba z „Line Manager”, której nie ma w kontaktach.
    new_person: Optional[rules.NewPersonHint] = None


@dataclass(frozen=True)
class ReportsToItem:
    person: rules.PersonRow
    proposal: rules.Proposal
    skipped: Optional[ClientStructureSkip]


def _is_skipped(skip: Optional[ClientStructureSkip], proposal: rules.Proposal) -> bool:
    """Pominięcie dotyczy tej propozycji — inna osoba przywraca pozycję."""

    return skip is not None and skip.proposed_contact_id == proposal.contact_id


def manager_items(data: ClientData) -> list[ManagerItem]:
    """Konsultanci bez menedżera u klienta z propozycją automatu."""

    index = rules.ContactIndex(data.people)
    peers = [
        rules.PeerManager(
            contract_id=contract.id,
            manager_id=manager_id,
            team_name=data.facts[contract.id].team_name,
            job_id=contract.job_id,
            job_title=contract.job_title,
        )
        for contract in data.contracts
        if (manager_id := data.managers.get(contract.id)) is not None
    ]
    items: list[ManagerItem] = []
    for contract in data.contracts:
        if data.managers.get(contract.id) is not None:
            continue
        facts = data.facts[contract.id]
        proposal = rules.decide(rules.manager_signals(facts, index, peers=peers))
        skip = data.skips.get(("manager", contract.id))
        items.append(
            ManagerItem(
                contract=contract,
                proposal=proposal,
                skipped=skip if _is_skipped(skip, proposal) else None,
                outside=contract.id in data.outside,
                new_person=rules.new_person_hint(facts, index),
            )
        )
    return items


def reports_to_items(data: ClientData) -> list[ReportsToItem]:
    """Osoby klienta bez „Podlega pod” z propozycją przełożonego (tylko z kandydatem)."""

    managers_of: dict[int, list[CareContract]] = {}
    for contract in data.contracts:
        manager_id = data.managers.get(contract.id)
        if manager_id is not None:
            managers_of.setdefault(manager_id, []).append(contract)
    hm_by_contract = {cid: facts.job_hm_contact_id for cid, facts in data.facts.items()}
    items: list[ReportsToItem] = []
    for person in data.people:
        if person.reports_to_id is not None:
            continue
        hm_of_team = [
            (hm, contract.job_title)
            for contract in managers_of.get(person.id, ())
            if (hm := hm_by_contract.get(contract.id)) is not None and hm != person.id
        ]
        proposal = rules.decide(
            rules.reports_to_signals(person, data.people, hm_of_team=hm_of_team)
        )
        if proposal.top is None:
            continue
        skip = data.skips.get(("reports_to", person.id))
        items.append(
            ReportsToItem(
                person=person,
                proposal=proposal,
                skipped=skip if _is_skipped(skip, proposal) else None,
            )
        )
    return items


@dataclass(frozen=True)
class Counts:
    consultants: int
    without_manager: int
    certain: int
    uncertain: int
    none: int
    skipped: int
    reports_to_certain: int
    reports_to_uncertain: int
    #: Niepominięci bez pewnej propozycji z „Dodaj X jako menedżera”.
    new_person: int = 0

    @property
    def open_managers(self) -> int:
        """Konsultanci do uzupełnienia (bez menedżera i bez pominięcia)."""

        return self.without_manager - self.skipped

    def as_dict(self) -> dict[str, int]:
        return {
            "consultants": self.consultants,
            "without_manager": self.without_manager,
            "certain": self.certain,
            "uncertain": self.uncertain,
            "none": self.none,
            "skipped": self.skipped,
            "open": self.open_managers,
            "reports_to_certain": self.reports_to_certain,
            "reports_to_uncertain": self.reports_to_uncertain,
            "new_person": self.new_person,
        }


def counts(
    data: ClientData,
    managers: Sequence[ManagerItem],
    reports_to: Sequence[ReportsToItem],
) -> Counts:
    live = [item for item in managers if item.skipped is None]
    org_live = [item for item in reports_to if item.skipped is None]
    return Counts(
        consultants=len(data.contracts),
        without_manager=len(managers),
        certain=sum(1 for i in live if i.proposal.confidence == "certain"),
        uncertain=sum(1 for i in live if i.proposal.confidence == "uncertain"),
        none=sum(1 for i in live if i.proposal.confidence == "none"),
        skipped=len(managers) - len(live),
        reports_to_certain=sum(
            1 for i in org_live if i.proposal.confidence == "certain"
        ),
        reports_to_uncertain=sum(
            1 for i in org_live if i.proposal.confidence == "uncertain"
        ),
        new_person=sum(1 for i in live if _offers_new_person(i)),
    )


def _offers_new_person(item: ManagerItem) -> bool:
    """„Dodaj X” stoi przy pozycji bez pewnej propozycji — pewna wskazuje już osobę."""

    return item.new_person is not None and item.proposal.confidence != "certain"


# ── Odpowiedzi tras ─────────────────────────────────────────────────────────


def _person_ref(
    person: Optional[rules.PersonRow], areas: dict[int, str]
) -> Optional[dict[str, Any]]:
    if person is None:
        return None
    return {
        "id": person.id,
        "name": person.name,
        "position": person.position,
        "area": areas.get(person.area_id) if person.area_id is not None else None,
    }


def _candidate(
    candidate: rules.Candidate,
    people: dict[int, rules.PersonRow],
    areas: dict[int, str],
) -> dict[str, Any]:
    return {
        "contact": _person_ref(people.get(candidate.contact_id), areas),
        "score": candidate.score,
        "sources": [
            {"source": s.source, "detail": s.detail} for s in candidate.signals
        ],
    }


def _proposal(
    proposal: rules.Proposal, people: dict[int, rules.PersonRow], areas: dict[int, str]
) -> dict[str, Any]:
    top = proposal.top
    return {
        "confidence": proposal.confidence,
        "proposal": _candidate(top, people, areas) if top else None,
        "alternatives": [
            _candidate(c, people, areas)
            for c in proposal.candidates[1 : 1 + ALTERNATIVES_SHOWN]
        ],
    }


def _skip(
    skip: Optional[ClientStructureSkip], names: dict[int, str]
) -> Optional[dict[str, Any]]:
    if skip is None:
        return None
    return {
        "skipped_at": skip.skipped_at,
        "by": names.get(skip.skipped_by_user_id) if skip.skipped_by_user_id else None,
    }


_ORDER = {"certain": 0, "uncertain": 1, "none": 2}


async def client_payload(db: AsyncSession, data: ClientData) -> dict[str, Any]:
    """Propozycje jednego klienta dla ekranu Delivery Leada."""

    managers = manager_items(data)
    reports_to = reports_to_items(data)
    people = {person.id: person for person in data.people}
    names = await care_access.user_names(
        db,
        [i.skipped.skipped_by_user_id for i in (*managers, *reports_to) if i.skipped],
    )
    manager_rows = [
        {
            "contract_id": item.contract.id,
            "candidate_id": item.contract.candidate_id,
            "candidate_name": item.contract.candidate_name,
            "role": item.contract.job_title,
            "end_date": item.contract.end_date,
            "manager_outside_client": item.outside,
            **_proposal(item.proposal, people, data.areas),
            "new_person": (
                {"name": item.new_person.name, "source": item.new_person.source}
                if _offers_new_person(item)
                else None
            ),
            "skipped": _skip(item.skipped, names),
        }
        for item in sorted(
            managers,
            key=lambda i: (
                i.skipped is not None,
                _ORDER[i.proposal.confidence],
                (i.contract.candidate_name or "").casefold(),
            ),
        )
    ]
    org_rows = [
        {
            "contact": _person_ref(item.person, data.areas),
            "department_text": item.person.department,
            **_proposal(item.proposal, people, data.areas),
            "skipped": _skip(item.skipped, names),
        }
        for item in sorted(
            reports_to,
            key=lambda i: (
                i.skipped is not None,
                _ORDER[i.proposal.confidence],
                i.person.name.casefold(),
            ),
        )
    ]
    return {
        "client_id": data.client_id,
        "client_name": data.client_name,
        "counts": counts(data, managers, reports_to).as_dict(),
        "managers": manager_rows,
        "reports_to": org_rows,
        "people": [
            _person_ref(person, data.areas)
            for person in sorted(data.people, key=lambda p: (p.name.casefold(), p.id))
        ],
    }


def summary_rows(datas: Iterable[ClientData]) -> list[dict[str, Any]]:
    """Klienci z zakresu z licznikami propozycji (lista „Struktura u klientów”)."""

    rows = []
    for data in datas:
        if not data.contracts:
            continue
        managers = manager_items(data)
        reports_to = reports_to_items(data)
        rows.append(
            {
                "client_id": data.client_id,
                "client_name": data.client_name,
                **counts(data, managers, reports_to).as_dict(),
            }
        )
    rows.sort(key=lambda r: (-r["open"], -r["certain"], r["client_name"].casefold()))
    return rows


# ── Zapis ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManagerChoice:
    contract_id: int
    contact_id: Optional[int] = None
    new_person_name: Optional[str] = None
    new_person_position: Optional[str] = None


async def apply_managers(
    db: AsyncSession,
    *,
    client_id: int,
    choices: Sequence[ManagerChoice],
    actor_id: int,
) -> dict[str, Any]:
    """Wpisuje menedżera u klienta na kontrakty (zatwierdzenie DL).

    Kontrakt, któremu ktoś w międzyczasie wpisał menedżera, zostaje bez zmian
    (``conflicts``) — zatwierdzenie propozycji nie nadpisuje decyzji człowieka.
    Zła pozycja (cudzy kontrakt albo osoba innego klienta) odrzuca całość (422).
    """

    if len(choices) > APPLY_MAX:
        raise HTTPException(_UNPROCESSABLE, TOO_MANY)
    if not choices:
        return {"applied": [], "conflicts": []}
    ids = sorted({c.contract_id for c in choices})
    contracts = {
        contract.id: contract
        for contract in (
            await db.scalars(
                select(Contract).where(Contract.id.in_(ids)).with_for_update()
            )
        ).all()
    }
    live = {c.id for c in await care_access.live_contracts(db, contract_ids=ids)}
    applied: list[int] = []
    conflicts: list[dict[str, Any]] = []
    for choice in choices:
        contract = contracts.get(choice.contract_id)
        if contract is None or contract.client_id != client_id:
            raise HTTPException(_UNPROCESSABLE, FOREIGN_CONTRACT)
        if contract.id not in live:
            raise HTTPException(_UNPROCESSABLE, CONTRACT_NOT_LIVE)
        has_name = bool((choice.new_person_name or "").strip())
        if has_name and choice.contact_id is not None:
            raise HTTPException(_UNPROCESSABLE, BOTH_INPUTS)
        current = contract.client_pm_contact_id
        if current is not None and current != choice.contact_id:
            owner = await db.scalar(
                select(Contact.client_id).where(Contact.id == current)
            )
            if owner == client_id:
                # Menedżer wpisany w międzyczasie — bez zmian i bez zakładania
                # nowej osoby, która zostałaby osierocona.
                conflicts.append({"contract_id": contract.id, "reason": "manager_set"})
                continue
        if has_name:
            contact = await contract_client_manager.resolve_new_person(
                db,
                contract,
                name=choice.new_person_name or "",
                position=choice.new_person_position,
                email=None,
                actor_id=actor_id,
            )
        elif choice.contact_id is not None:
            contact = await contract_client_manager.assert_contact_of_client(
                db, contact_id=choice.contact_id, client_id=client_id
            )
        else:
            raise HTTPException(_UNPROCESSABLE, NO_INPUT)
        if current == contact.id:
            applied.append(contract.id)
            continue
        contract.client_pm_contact_id = contact.id
        applied.append(contract.id)
        audit.record(
            db,
            actor_user_id=actor_id,
            subject_user_id=None,
            entity_type="contract",
            entity_id=contract.id,
            action="care.client_manager_set",
            details={
                "client_id": client_id,
                "contact_id": contact.id,
                "previous_contact_id": current,
                "source": "structure_proposals",
            },
        )
    if applied:
        await db.execute(
            delete(ClientStructureSkip).where(
                ClientStructureSkip.kind == "manager",
                ClientStructureSkip.contract_id.in_(applied),
            )
        )
        record_client_audit(
            db,
            client_id=client_id,
            actor_id=actor_id,
            action="client_managers_set",
            details={"contract_ids": applied, "source": "structure_proposals"},
        )
    await db.flush()
    return {"applied": applied, "conflicts": conflicts}


async def set_skip(
    db: AsyncSession,
    *,
    client_id: int,
    kind: str,
    subject_id: int,
    proposed_contact_id: Optional[int],
    actor_id: int,
) -> None:
    """„Pomiń” — jeden wiersz na pozycję; nowe pominięcie zastępuje poprzednie."""

    if kind == "manager":
        owner = await db.scalar(
            select(Contract.client_id).where(Contract.id == subject_id)
        )
        if owner != client_id:
            raise HTTPException(_UNPROCESSABLE, FOREIGN_CONTRACT)
    else:
        owner = await db.scalar(
            select(Contact.client_id).where(Contact.id == subject_id)
        )
        if owner != client_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, CONTACT_NOT_FOUND)
    if proposed_contact_id is not None:
        proposed_owner = await db.scalar(
            select(Contact.client_id).where(Contact.id == proposed_contact_id)
        )
        if proposed_owner != client_id:
            raise HTTPException(_UNPROCESSABLE, CONTACT_NOT_FOUND)
    subject_column = "contract_id" if kind == "manager" else "contact_id"
    await clear_skip(db, client_id=client_id, kind=kind, subject_id=subject_id)
    await db.execute(
        pg_insert(ClientStructureSkip)
        .values(
            client_id=client_id,
            kind=kind,
            proposed_contact_id=proposed_contact_id,
            skipped_by_user_id=actor_id,
            **{subject_column: subject_id},
        )
        # Podwójne „Pomiń” z dwóch kart: drugie trafia w unikalny indeks pozycji.
        .on_conflict_do_nothing()
    )


async def clear_skip(
    db: AsyncSession, *, client_id: int, kind: str, subject_id: int
) -> None:
    column = (
        ClientStructureSkip.contract_id
        if kind == "manager"
        else ClientStructureSkip.contact_id
    )
    await db.execute(
        delete(ClientStructureSkip).where(
            ClientStructureSkip.client_id == client_id,
            ClientStructureSkip.kind == kind,
            column == subject_id,
        )
    )


# ── Dzwonek „uzupełnij strukturę klienta X” ────────────────────────────────


def _plural(count: int, one: str, few: str, many: str) -> str:
    if count == 1:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def structure_link(client_id: int) -> str:
    return f"/care?tab=structure&client={client_id}"


def reminder_message(client_name: str, row: dict[str, int]) -> str:
    open_count = row["open"]
    people = _plural(open_count, "konsultant", "konsultantów", "konsultantów")
    text = f"{client_name}: {open_count} {people} bez menedżera u klienta"
    if row["certain"]:
        proposals = _plural(
            row["certain"], "pewna propozycja", "pewne propozycje", "pewnych propozycji"
        )
        text += f", {row['certain']} {proposals} do zatwierdzenia"
    return text + "."


async def _client_leads(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, list[int]]:
    """Aktywni Delivery Leadzi przypisani do klienta (główny pierwszy).

    Także DL przypisany tylko do scalonego duplikatu klienta — jego portfel
    obejmuje klienta kanonicznego (``resolve_delivery_lead_assigned_client_ids``),
    więc i dzwonek (audyt 19.10.2026).
    """

    out: dict[int, list[int]] = {}
    if not client_ids:
        return out
    canonical = {client_id: client_id for client_id in client_ids}
    for duplicate_id, target_id in (
        await db.execute(
            select(Client.id, Client.merged_into_client_id).where(
                Client.merged_into_client_id.in_(client_ids)
            )
        )
    ).all():
        canonical.setdefault(duplicate_id, target_id)
    rows = (
        await db.execute(
            select(DeliveryLeadClientAssignment.client_id, User)
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(
                DeliveryLeadClientAssignment.client_id.in_(sorted(canonical)),
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.is_head.desc(),
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.id,
            )
        )
    ).all()
    for client_id, user in rows:
        leads = out.setdefault(canonical[client_id], [])
        if user.has_role(UserRole.delivery_lead) and user.id not in leads:
            leads.append(user.id)
    return {client_id: leads for client_id, leads in out.items() if leads}


#: Ci sami odbiorcy dostają dzwonek popytu z rozmowy opiekuna (``care/demand``).
client_leads = _client_leads


async def _recently_reminded(
    db: AsyncSession, client_ids: Sequence[int], now: datetime
) -> set[tuple[int, int]]:
    if not client_ids:
        return set()
    rows = (
        await db.execute(
            select(Notification.user_id, Notification.related_entity_id).where(
                Notification.notification_type
                == NotificationType.care_client_structure,
                Notification.related_entity_type == "client",
                Notification.related_entity_id.in_(client_ids),
                Notification.created_at
                >= now - timedelta(days=STRUCTURE_REMINDER_EVERY_DAYS),
            )
        )
    ).all()
    return {
        (int(user_id), int(client_id))
        for user_id, client_id in rows
        if client_id is not None
    }


async def remind(db: AsyncSession, *, now: datetime) -> dict[str, int]:
    """Dzwonki do Delivery Leadów klientów z konsultantami bez menedżera (bez commita).

    Najwyżej raz na 7 dni na (DL, klient). Klient bez przypisanego DL nie
    dostaje nikogo — to luka portfela, nie struktury.
    """

    from app.services.hr.notify import notify_each  # noqa: PLC0415 — jak w care.reminders

    rows = [
        row
        for row in summary_rows((await load(db, client_ids=None)).values())
        if row["open"] > 0
    ]
    ids = [row["client_id"] for row in rows]
    leads = await _client_leads(db, ids)
    recent = await _recently_reminded(db, ids, now)
    sent = skipped = no_lead = 0
    for row in rows:
        recipients = [
            user_id
            for user_id in leads.get(row["client_id"], [])
            if (user_id, row["client_id"]) not in recent
        ]
        if not leads.get(row["client_id"]):
            no_lead += 1
            continue
        if not recipients:
            skipped += 1
            continue
        sent += await notify_each(
            db,
            recipients,
            title="Uzupełnij strukturę u klienta",
            message=reminder_message(row["client_name"], row),
            ntype=NotificationType.care_client_structure,
            related_entity_type="client",
            related_entity_id=row["client_id"],
            link=structure_link(row["client_id"]),
            log_tag="care",
        )
    return {
        "structure_clients": len(rows),
        "structure_sent": sent,
        "structure_skipped": skipped,
        "structure_no_lead": no_lead,
    }
