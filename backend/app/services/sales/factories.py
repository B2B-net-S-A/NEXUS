"""Lejek Fabryki IT mierzony kontaktem: liczniki map i kolejka do pierwszego kontaktu.

Decyzje Artura z 10.11.2026 (rekomendacje B2 i B3). Etap konta opisuje research
(„Mapa decyzyjna gotowa”), więc lista kont pokazuje obok niego, ile osób z mapy
ma kontakt za sobą. To sam odczyt: mapa leży w ``custom_fields`` szansy
(``decision_map.py``), a status kontaktu zmienia człowiek w oknie osoby albo
automat po mailu lub spotkaniu z Outlooka (``decision_map_outlook.py``).

Moduł podpowiada i niczego nie blokuje: rozjazd etapu z mapą to znacznik przy
wierszu, a nie warunek zapisu etapu. Kolejka nie ma celu, postępu ani rankingu.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services.sales import client_gate
from app.services.sales.decision_map import (
    IT_FACTORIES_PIPELINE_KEY,
    decision_entries,
)
from app.services.sales.motion import decision_people

#: Statusy osoby z mapy, które znaczą „kontakt za sobą”; „bez kontaktu” i brak
#: statusu to osoba, do której nikt jeszcze nie dotarł.
CONTACTED_STATUSES = frozenset({"in_progress", "first_contact", "regular_dialog"})
#: Kolejka to zarząd i dyrektorzy; kierownicy i zespół są pod zwiniętą listą.
QUEUE_LEVELS = frozenset({1, 2})
#: Od tego etapu nazwa etapu mówi, że kontakt już był.
FIRST_CONTACT_STAGE_KEY = "itf-first-contact"
COMPANY_DO_NOT_CONTACT = "do_not_contact"


@dataclass(frozen=True)
class MapCounts:
    """Mapa jednego konta w liczbach; ``waiting`` to osoby do kolejki."""

    total: int = 0
    contacted: int = 0
    top_total: int = 0
    top_contacted: int = 0
    waiting: int = 0


@dataclass(frozen=True)
class Account:
    opportunity_id: int
    company_id: int
    counts: MapCounts
    stage_mismatch: bool
    client: Optional[client_gate.ClientMatch]


@dataclass(frozen=True)
class QueuePerson:
    opportunity_id: int
    opportunity_title: str
    company_id: int
    company_name: str
    client: Optional[client_gate.ClientMatch]
    #: Wpis mapy z polami liczonymi przy odczycie, jak na karcie szansy.
    person: dict[str, Any]


@dataclass(frozen=True)
class Queue:
    people: list[QueuePerson]
    lower_levels: list[QueuePerson]


def _named(entry: dict[str, Any]) -> bool:
    name = entry.get("name")
    return isinstance(name, str) and bool(name.strip())


def _level(entry: dict[str, Any]) -> Optional[int]:
    """Poziom decyzji jako liczba; wpis z importu nie przeszedł walidacji API."""

    level = entry.get("decision_level")
    return level if isinstance(level, int) and not isinstance(level, bool) else None


def is_contacted(entry: dict[str, Any]) -> bool:
    status = entry.get("contact_status")
    return isinstance(status, str) and status in CONTACTED_STATUSES


def in_queue_levels(entry: dict[str, Any]) -> bool:
    return _level(entry) in QUEUE_LEVELS


def waits_for_first_contact(entry: dict[str, Any]) -> bool:
    """Osoba z nazwiskiem, bez kontaktu i bez sprzeciwu wobec kontaktu."""

    return _named(entry) and not is_contacted(entry) and not entry.get("do_not_contact")


def map_counts(
    entries: Sequence[dict[str, Any]], *, company_blocked: bool = False
) -> MapCounts:
    """Liczniki mapy; firma „Nie kontaktować” nie ma nikogo do kolejki."""

    people = [entry for entry in entries if _named(entry)]
    top = [entry for entry in people if in_queue_levels(entry)]
    return MapCounts(
        total=len(people),
        contacted=sum(map(is_contacted, people)),
        top_total=len(top),
        top_contacted=sum(map(is_contacted, top)),
        waiting=(0 if company_blocked else sum(map(waits_for_first_contact, top))),
    )


def stage_claims_contact(
    position: int, outcome: str, first_contact_position: Optional[int]
) -> bool:
    """Otwarty etap „Pierwszy kontakt” albo dalszy: jego nazwa mówi o kontakcie."""

    return (
        first_contact_position is not None
        and outcome == "open"
        and position >= first_contact_position
    )


def _queue_order(row: QueuePerson) -> tuple[Any, ...]:
    """Klient NEXUSA na końcu (temat prowadzi Delivery Lead), potem firma i poziom."""

    person = row.person
    has_channel = any(person.get(f) for f in ("phone", "email", "linkedin_url"))
    return (
        row.client is not None,
        row.company_name.casefold(),
        row.company_id,
        _level(person) or 9,
        not has_channel,
        str(person.get("name") or "").casefold(),
    )


def _opportunities(*, archived: bool):
    return (
        select(
            SalesOpportunity.id,
            SalesOpportunity.title,
            SalesOpportunity.company_id,
            SalesOpportunity.custom_fields,
            SalesPipelineStage.position.label("stage_position"),
            SalesPipelineStage.outcome.label("stage_outcome"),
            SalesCompany.name.label("company_name"),
            SalesCompany.client_id,
            SalesCompany.normalized_name,
            SalesCompany.status.label("company_status"),
        )
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesOpportunity.archived_at.is_not(None)
            if archived
            else SalesOpportunity.archived_at.is_(None),
        )
        .order_by(SalesOpportunity.id)
    )


async def _clients(
    db: AsyncSession, rows: Sequence[Any]
) -> dict[int, client_gate.ClientMatch]:
    """Firmy z listy, które są klientem NEXUSA; nasza spółka nim nie jest."""

    identities = {
        row.company_id: client_gate.CompanyIdentity(
            company_id=row.company_id,
            client_id=row.client_id,
            normalized_name=row.normalized_name,
        )
        for row in rows
        if row.normalized_name != client_gate.OWN_COMPANY_KEY
    }
    if not identities:
        return {}
    return await client_gate.match_companies(db, list(identities.values()))


async def _people(db: AsyncSession, rows: Sequence[Any]) -> list[list[dict[str, Any]]]:
    return await decision_people(
        db, [(row.company_id, decision_entries(row.custom_fields)) for row in rows]
    )


async def load_accounts(db: AsyncSession, *, archived: bool = False) -> list[Account]:
    """Liczniki map wszystkich kont lejka, bez zapytania per wiersz."""

    rows = (await db.execute(_opportunities(archived=archived))).all()
    if not rows:
        return []
    first_contact_position = await db.scalar(
        select(SalesPipelineStage.position)
        .join(SalesPipeline, SalesPipeline.id == SalesPipelineStage.pipeline_id)
        .where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesPipelineStage.key == FIRST_CONTACT_STAGE_KEY,
        )
    )
    clients = await _clients(db, rows)
    accounts = []
    for row, people in zip(rows, await _people(db, rows)):
        counts = map_counts(
            people, company_blocked=row.company_status == COMPANY_DO_NOT_CONTACT
        )
        accounts.append(
            Account(
                opportunity_id=row.id,
                company_id=row.company_id,
                counts=counts,
                stage_mismatch=counts.contacted == 0
                and stage_claims_contact(
                    row.stage_position, row.stage_outcome, first_contact_position
                ),
                client=clients.get(row.company_id),
            )
        )
    return accounts


async def load_queue(db: AsyncSession, *, owner_user_id: int) -> Queue:
    """Osoby bez kontaktu z map otwartych kont jednego opiekuna.

    Poziom 1 i 2 to kolejka; reszta (kierownicy, zespół, osoby bez poziomu)
    wraca osobno, bo ekran pokazuje ją zwiniętą. Nic nie znika na stałe.
    """

    rows = (
        await db.execute(
            _opportunities(archived=False).where(
                SalesOpportunity.owner_user_id == owner_user_id,
                SalesOpportunity.status == "open",
                SalesCompany.status != COMPANY_DO_NOT_CONTACT,
            )
        )
    ).all()
    if not rows:
        return Queue(people=[], lower_levels=[])
    clients = await _clients(db, rows)
    waiting = [
        QueuePerson(
            opportunity_id=row.id,
            opportunity_title=row.title,
            company_id=row.company_id,
            company_name=row.company_name,
            client=clients.get(row.company_id),
            person=person,
        )
        for row, people in zip(rows, await _people(db, rows))
        for person in people
        if waits_for_first_contact(person)
    ]
    waiting.sort(key=_queue_order)
    return Queue(
        people=[row for row in waiting if in_queue_levels(row.person)],
        lower_levels=[row for row in waiting if not in_queue_levels(row.person)],
    )
