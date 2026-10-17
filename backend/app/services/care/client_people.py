"""Struktura u klienta i prośby o opinię (etap 2, D8–D11, 17.10.2026).

* **Drzewo** (zakładka klienta „Struktura u klienta”): działy klienta
  (``client_areas`` — „Działy i obszary”, ten sam słownik co mapa technologii)
  → osoby klienta (kontakty: stanowisko, decydent, hiring manager rekrutacji,
  menedżer naszych konsultantów) z wcięciem po „podlega pod” → pod osobą nasi
  konsultanci, których jest menedżerem (``contracts.client_pm_contact_id``):
  kandydat, rola, koniec zamówienia, ostatnia opinia. Kontakt bez działu →
  „Bez działu”, konsultant bez menedżera → „Bez wskazanego menedżera”
  z podpowiedzią z tekstu Line Manager/PM.
* **Prośba o opinię (D9)** — wyliczana przy odczycie, nic nie zapisuje. Menedżer
  ma prośbę, gdy któryś jego konsultant kończy zamówienie albo umowę w ciągu
  30 dni i od początku tego okna nie było rozmowy z menedżerem, albo od
  ostatniej rozmowy minął kwartał (90 dni; bez żadnej rozmowy — od startu
  pierwszego z jego konsultantów). Jedna pozycja na menedżera ze wszystkimi
  jego konsultantami. Koniec współpracy = ta sama data co w planie opieki
  (``CareContract.end_date``: bliższy z końca umowy i zamówienia).
* **Podlega pod** — kontakt tego samego klienta, bez pętli (422).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import CONTACTS_ORG, ClientArea
from app.models.job import Job
from app.services import contract_client_manager
from app.services.care import access as care_access
from app.services.care import client_feedback
from app.services.care import records
from app.services.care import skills as care_skills
from app.services.care.access import CareContract
from app.services.client_access import record_client_audit

PRE_END_DAYS = 30
QUARTER_DAYS = 90
#: Rekrutacje, w których osoba jest hiring managerem — w panelu tylko ostatnie.
HM_JOBS_SHOWN = 5
#: Głębokość łańcucha „podlega pod” sprawdzana przy zapisie (bezpiecznik).
MAX_CHAIN = 200
# Przestrzeń nazw blokady doradczej zapisu struktury jednego klienta.
_ORG_LOCK_NS = 20261017

_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY

CONTACT_NOT_FOUND = "Nie ma takiej osoby u tego klienta."
FOREIGN_MANAGER = "Przełożony musi być osobą z firmy tego klienta."
SELF_MANAGER = "Osoba nie może podlegać sama pod siebie."
FOREIGN_AREA = "Dział musi należeć do tego klienta."
BOTH_AREA_INPUTS = "Wybierz dział z listy albo wpisz nowy — nie oba naraz."

_contacts_org = CONTACTS_ORG.alias("contacts_org")


# ── Prośby o opinię (D9) ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RequestDecision:
    reasons: tuple[str, ...]  # pre_end | quarterly
    due_on: date


def request_decision(
    *,
    starts: Iterable[Optional[date]],
    ends: Iterable[Optional[date]],
    last_held_on: Optional[date],
    today: date,
) -> Optional[RequestDecision]:
    """Czy menedżer ma prośbę o opinię i od kiedy (czysta reguła D9)."""

    reasons: list[str] = []
    dues: list[date] = []
    window_dues = [
        end - timedelta(days=PRE_END_DAYS)
        for end in ends
        if end is not None
        and today <= end <= today + timedelta(days=PRE_END_DAYS)
        and (last_held_on is None or last_held_on < end - timedelta(days=PRE_END_DAYS))
    ]
    if window_dues:
        reasons.append("pre_end")
        dues.append(min(window_dues))
    base = last_held_on
    if base is None:
        base = min((start for start in starts if start is not None), default=None)
    if base is not None and today >= base + timedelta(days=QUARTER_DAYS):
        reasons.append("quarterly")
        dues.append(base + timedelta(days=QUARTER_DAYS))
    if not reasons:
        return None
    return RequestDecision(tuple(reasons), min(dues))


@dataclass(frozen=True)
class ManagedContract:
    contract: CareContract
    manager_id: Optional[int]
    line_manager: Optional[str]
    client_pm_name: Optional[str]


async def _live_with_managers(
    db: AsyncSession, *, allowed: Optional[frozenset[int]]
) -> list[ManagedContract]:
    contracts = await care_access.live_contracts(db, allowed=allowed)
    if not contracts:
        return []
    fields = {
        row[0]: row[1:]
        for row in (
            await db.execute(
                select(
                    Contract.id,
                    Contract.client_pm_contact_id,
                    Contract.line_manager,
                    Contract.client_pm_name,
                ).where(Contract.id.in_([c.id for c in contracts]))
            )
        ).all()
    }
    return [
        ManagedContract(contract, *fields.get(contract.id, (None, None, None)))
        for contract in contracts
    ]


def _end_source(contract: CareContract) -> Optional[str]:
    if contract.end_date is None:
        return None
    if (
        contract.order_end_date is not None
        and contract.order_end_date == contract.end_date
    ):
        return "order"
    return "contract"


def _consultant(
    contract: CareContract, last: Optional[client_feedback.LastFeedback]
) -> dict[str, Any]:
    return {
        "contract_id": contract.id,
        "candidate_id": contract.candidate_id,
        "candidate_name": contract.candidate_name,
        "role": contract.job_title,
        "end_date": contract.end_date,
        "end_source": _end_source(contract),
        "last_feedback": last.as_dict() if last else None,
    }


async def _requests_from(
    db: AsyncSession,
    rows: Sequence[ManagedContract],
    *,
    today: date,
    contacts: Optional[dict[int, Contact]] = None,
) -> list[dict[str, Any]]:
    by_manager: dict[int, list[CareContract]] = {}
    for row in rows:
        if row.manager_id is not None:
            by_manager.setdefault(row.manager_id, []).append(row.contract)
    if not by_manager:
        return []
    if contacts is None:
        contacts = {
            contact.id: contact
            for contact in (
                await db.scalars(
                    select(Contact).where(Contact.id.in_(sorted(by_manager)))
                )
            ).all()
        }
    last_contact = await client_feedback.last_by_contact(db, by_manager)
    every = [c for group in by_manager.values() for c in group]
    last_contract = await client_feedback.last_by_contract(db, [c.id for c in every])
    owners = await care_access.effective_owners(db, every)
    items: list[dict[str, Any]] = []
    for manager_id, consultants in by_manager.items():
        contact = contacts.get(manager_id)
        if contact is None:
            continue
        # Kontakt innego klienta (dane sprzed walidacji D8) nie zbiera próśb.
        consultants = [c for c in consultants if c.client_id == contact.client_id]
        if not consultants:
            continue
        last = last_contact.get(manager_id)
        decision = request_decision(
            starts=(c.start_date for c in consultants),
            ends=(c.end_date for c in consultants),
            last_held_on=last.held_on if last else None,
            today=today,
        )
        if decision is None:
            continue
        consultants = sorted(
            consultants, key=lambda c: (c.end_date or date.max, c.candidate_name or "")
        )
        items.append(
            {
                "contact_id": contact.id,
                "contact_name": contact.name,
                "position": contact.position,
                "client_id": consultants[0].client_id,
                "client_name": consultants[0].client_name,
                "reasons": list(decision.reasons),
                "due_on": decision.due_on,
                "overdue": decision.due_on < today,
                "last_feedback": last.as_dict() if last else None,
                "consultants": [
                    _consultant(c, last_contract.get(c.id)) for c in consultants
                ],
                "owner_ids": sorted(
                    {
                        owners[c.id].user_id
                        for c in consultants
                        if owners[c.id].user_id is not None
                    }
                ),
            }
        )
    items.sort(key=lambda item: (item["due_on"], item["contact_name"].casefold()))
    return items


async def feedback_requests(
    db: AsyncSession, *, client_ids: Optional[Iterable[int]], today: date
) -> list[dict[str, Any]]:
    """Prośby o opinię u klientów z zakresu (``None`` = wszyscy klienci).

    Jedna pozycja na menedżera; ``owner_ids`` = opiekunowie jego konsultantów
    (lista „Opieka · Ten tydzień” filtruje po nich, DL widzi swoich klientów).
    """

    allowed = None if client_ids is None else frozenset(client_ids)
    rows = await _live_with_managers(db, allowed=allowed)
    return await _requests_from(db, rows, today=today)


# ── Drzewo ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrgContact:
    id: int
    name: str
    position: Optional[str]
    department: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    is_decision_maker: bool
    reports_to_id: Optional[int]
    area_id: Optional[int]


async def _org_contacts(db: AsyncSession, client_id: int) -> list[OrgContact]:
    rows = (
        await db.execute(
            select(
                Contact.id,
                Contact.name,
                Contact.position,
                Contact.department,
                Contact.email,
                Contact.phone,
                Contact.is_decision_maker,
                _contacts_org.c.reports_to_contact_id,
                _contacts_org.c.client_area_id,
            )
            .join(_contacts_org, _contacts_org.c.id == Contact.id)
            .where(Contact.client_id == client_id)
            .order_by(Contact.name, Contact.id)
        )
    ).all()
    return [
        OrgContact(
            id=row[0],
            name=row[1],
            position=row[2],
            department=row[3],
            email=row[4],
            phone=row[5],
            is_decision_maker=bool(row[6]),
            reports_to_id=row[7],
            area_id=row[8],
        )
        for row in rows
    ]


def _ordered_with_depth(people: Sequence[OrgContact]) -> list[tuple[OrgContact, int]]:
    """Osoby działu w kolejności drzewa (przełożony, pod nim podwładni)."""

    in_group = {person.id for person in people}
    children: dict[int, list[OrgContact]] = {}
    roots: list[OrgContact] = []
    for person in people:
        if person.reports_to_id in in_group and person.reports_to_id != person.id:
            children.setdefault(person.reports_to_id, []).append(person)
        else:
            roots.append(person)
    out: list[tuple[OrgContact, int]] = []
    seen: set[int] = set()

    def visit(person: OrgContact, depth: int) -> None:
        if person.id in seen:
            return
        seen.add(person.id)
        out.append((person, depth))
        for child in sorted(
            children.get(person.id, []), key=lambda p: p.name.casefold()
        ):
            visit(child, depth + 1)

    for root in sorted(roots, key=lambda p: p.name.casefold()):
        visit(root, 0)
    # Pętla zapisana z pominięciem walidacji (np. import) nie gubi osób.
    for person in people:
        if person.id not in seen:
            visit(person, 0)
    return out


def _department_hint(
    person: OrgContact, areas_by_key: dict[str, ClientArea]
) -> Optional[dict[str, Any]]:
    """„Dział z kontaktu: X” — dopasowanie tekstu do działu albo propozycja nowego."""

    if person.area_id is not None:
        return None
    text_value = " ".join((person.department or "").split())
    if not text_value:
        return None
    area = areas_by_key.get(care_skills.name_key(text_value))
    return {
        "area_id": area.id if area else None,
        "name": area.name if area else text_value,
    }


async def client_org(
    db: AsyncSession,
    client_id: int,
    *,
    today: date,
    show_contact_details: bool,
) -> dict[str, Any]:
    people = await _org_contacts(db, client_id)
    by_id = {person.id: person for person in people}
    areas = (
        await db.scalars(
            select(ClientArea)
            .where(ClientArea.client_id == client_id)
            .order_by(ClientArea.name)
        )
    ).all()
    area_by_id = {area.id: area for area in areas}
    areas_by_key = {area.name_key: area for area in areas}

    rows = await _live_with_managers(db, allowed=frozenset([client_id]))
    consultants_of: dict[int, list[CareContract]] = {}
    without: list[ManagedContract] = []
    for row in rows:
        if row.manager_id is not None and row.manager_id in by_id:
            consultants_of.setdefault(row.manager_id, []).append(row.contract)
        else:
            without.append(row)
    last_contract = await client_feedback.last_by_contract(
        db, [row.contract.id for row in rows]
    )
    last_contact = await client_feedback.last_by_contact(db, consultants_of)
    contact_rows = {
        contact.id: contact
        for contact in (
            await db.scalars(select(Contact).where(Contact.client_id == client_id))
        ).all()
    }
    requests = await _requests_from(
        db,
        [row for row in rows if row.manager_id in by_id],
        today=today,
        contacts=contact_rows,
    )
    request_of = {item["contact_id"]: item for item in requests}

    hm_jobs: dict[int, list[dict[str, Any]]] = {}
    if people:
        for job_id, title, job_status, contact_id in (
            await db.execute(
                select(Job.id, Job.title, Job.status, Job.hiring_manager_contact_id)
                .where(
                    Job.client_id == client_id,
                    Job.hiring_manager_contact_id.in_(sorted(by_id)),
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        ).all():
            hm_jobs.setdefault(contact_id, []).append(
                {
                    "id": job_id,
                    "title": title,
                    "status": getattr(job_status, "value", job_status),
                }
            )

    subordinates: dict[int, list[OrgContact]] = {}
    for person in people:
        if person.reports_to_id in by_id and person.reports_to_id != person.id:
            subordinates.setdefault(person.reports_to_id, []).append(person)

    def node(person: OrgContact, depth: int) -> dict[str, Any]:
        manager = by_id.get(person.reports_to_id) if person.reports_to_id else None
        consultants = sorted(
            consultants_of.get(person.id, []),
            key=lambda c: (c.end_date or date.max, c.candidate_name or ""),
        )
        jobs = hm_jobs.get(person.id, [])
        request = request_of.get(person.id)
        last = last_contact.get(person.id)
        return {
            "id": person.id,
            "name": person.name,
            "position": person.position,
            "department_text": person.department,
            "area_id": person.area_id if person.area_id in area_by_id else None,
            "depth": depth,
            "is_decision_maker": person.is_decision_maker,
            "is_hiring_manager": bool(jobs),
            "is_manager": bool(consultants),
            "reports_to": {"id": manager.id, "name": manager.name} if manager else None,
            "subordinates": [
                {"id": p.id, "name": p.name}
                for p in sorted(
                    subordinates.get(person.id, []), key=lambda p: p.name.casefold()
                )
            ],
            "email": person.email if show_contact_details else None,
            "phone": person.phone if show_contact_details else None,
            "hiring_manager_jobs": jobs[:HM_JOBS_SHOWN],
            "hiring_manager_jobs_total": len(jobs),
            "consultants": [
                _consultant(c, last_contract.get(c.id)) for c in consultants
            ],
            "last_feedback": last.as_dict() if last else None,
            "feedback_request": (
                {
                    "reasons": request["reasons"],
                    "due_on": request["due_on"],
                    "overdue": request["overdue"],
                }
                if request
                else None
            ),
            "department_hint": _department_hint(person, areas_by_key),
        }

    groups: dict[Optional[int], list[OrgContact]] = {}
    for person in people:
        key = person.area_id if person.area_id in area_by_id else None
        groups.setdefault(key, []).append(person)
    departments = [
        {
            "area": {"id": area.id, "name": area.name},
            "people": [
                node(p, depth) for p, depth in _ordered_with_depth(groups[area.id])
            ],
        }
        for area in areas
        if area.id in groups
    ]
    if None in groups:
        departments.append(
            {
                "area": None,
                "people": [
                    node(p, depth) for p, depth in _ordered_with_depth(groups[None])
                ],
            }
        )

    contacts_list = list(contact_rows.values())
    without_rows = []
    for row in sorted(
        without,
        key=lambda r: (
            r.contract.end_date or date.max,
            r.contract.candidate_name or "",
        ),
    ):
        hint = (
            contract_client_manager.text_hint(
                contacts_list,
                line_manager=row.line_manager,
                client_pm_name=row.client_pm_name,
            )
            if row.manager_id is None
            else None
        )
        without_rows.append(
            {
                **_consultant(row.contract, last_contract.get(row.contract.id)),
                "line_manager": row.line_manager,
                "client_pm_name": row.client_pm_name,
                # Kontakt spoza tego klienta (dane sprzed walidacji) — do poprawy.
                "manager_outside_client": row.manager_id is not None,
                "hint": hint,
            }
        )
    return {
        "client_id": client_id,
        "areas": [{"id": area.id, "name": area.name} for area in areas],
        "departments": departments,
        "without_manager": without_rows,
        "requests": requests,
        "people_count": len(people),
        "consultants_count": len(rows),
    }


# ── Zapis struktury ─────────────────────────────────────────────────────────


async def manager_chain_reaches(
    db: AsyncSession, *, start_id: int, target_id: int
) -> bool:
    """Czy idąc od ``start_id`` w górę „podlega pod” dochodzimy do ``target_id``."""

    current: Optional[int] = start_id
    seen: set[int] = set()
    while current is not None and current not in seen and len(seen) < MAX_CHAIN:
        if current == target_id:
            return True
        seen.add(current)
        current = await db.scalar(
            select(CONTACTS_ORG.c.reports_to_contact_id).where(
                CONTACTS_ORG.c.id == current
            )
        )
    return False


async def update_contact_org(
    db: AsyncSession,
    *,
    client_id: int,
    contact_id: int,
    changes: dict[str, Any],
    actor_id: int,
) -> None:
    """„Podlega pod” i „Dział” kontaktu. ``changes`` niesie tylko wysłane pola."""

    # Dwa równoległe zapisy (A pod B, B pod A) przeszłyby osobno kontrolę pętli.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :client_id)"),
        {"ns": _ORG_LOCK_NS, "client_id": client_id},
    )
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CONTACT_NOT_FOUND)
    values: dict[str, Any] = {}
    if "reports_to_contact_id" in changes:
        manager_id = changes["reports_to_contact_id"]
        if manager_id is not None:
            if manager_id == contact.id:
                raise HTTPException(_UNPROCESSABLE, SELF_MANAGER)
            manager = await db.get(Contact, manager_id)
            if manager is None or manager.client_id != client_id:
                raise HTTPException(_UNPROCESSABLE, FOREIGN_MANAGER)
            if await manager_chain_reaches(
                db, start_id=manager_id, target_id=contact.id
            ):
                raise HTTPException(
                    _UNPROCESSABLE,
                    f"Ta zmiana zamknęłaby pętlę: {manager.name} podlega już "
                    f"(bezpośrednio albo pośrednio) pod {contact.name}.",
                )
        values["reports_to_contact_id"] = manager_id
    new_area = (changes.get("new_area_name") or "").strip()
    if new_area and changes.get("client_area_id") is not None:
        raise HTTPException(_UNPROCESSABLE, BOTH_AREA_INPUTS)
    if new_area:
        area = await records.add_area(db, client_id, new_area, actor_id=actor_id)
        values["client_area_id"] = area.id
    elif "client_area_id" in changes:
        area_id = changes["client_area_id"]
        if area_id is not None:
            area = await db.get(ClientArea, area_id)
            if area is None or area.client_id != client_id:
                raise HTTPException(_UNPROCESSABLE, FOREIGN_AREA)
        values["client_area_id"] = area_id
    if not values:
        return
    await db.execute(
        update(CONTACTS_ORG).where(CONTACTS_ORG.c.id == contact.id).values(**values)
    )
    record_client_audit(
        db,
        client_id=client_id,
        actor_id=actor_id,
        action="contact_updated",
        details={
            "contact_id": contact.id,
            "fields": sorted(values),
            "source": "client_org",
        },
    )
