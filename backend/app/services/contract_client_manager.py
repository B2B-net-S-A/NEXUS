"""Menedżer u klienta na kontrakcie (D8, „Ludzie w NEXUSIE”, etap 2, 17.10.2026).

Menedżer to KONTAKT klienta (``contracts.client_pm_contact_id``, kolumna z 0097),
pod którym konsultant pracuje. Teksty „PM po stronie klienta” i „Line Manager”
zostają opisem — przy pustym kontakcie, gdy tekst to dokładnie imię i nazwisko
kontaktu klienta (bez wielkości liter), ekran pokazuje podpowiedź „Przypnij: X”.
Nic nie przypina się samo.

* Kontakt musi należeć do klienta kontraktu — inaczej 422 (zmiana klienta
  kontraktu ma osobną blokadę w ``contract_client_reassign``).
* Nowa osoba idzie przez ``job_hiring_manager.find_or_create_contact``: ta sama
  osoba wpisana inaczej nie staje się duplikatem kontaktu.
* Kontrakt z rekrutacji (automat przy „Zatrudniony” i ręczne zakładanie
  z ``job_id``) dostaje domyślnie hiring managera tej rekrutacji, o ile to
  kontakt klienta kontraktu.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contract import Contract
from app.models.job import Job
from app.services.job_hiring_manager import (
    clean_person_name,
    find_or_create_contact,
    name_key,
)

FOREIGN_CONTACT_DETAIL = (
    "Menedżer u klienta musi być osobą z firmy klienta tego kontraktu."
)
NEW_PERSON_NAME_DETAIL = "Podaj imię i nazwisko menedżera u klienta."


async def assert_contact_of_client(
    db: AsyncSession, *, contact_id: int, client_id: int
) -> Contact:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.client_id != client_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, FOREIGN_CONTACT_DETAIL
        )
    return contact


async def resolve_new_person(
    db: AsyncSession,
    contract: Contract,
    *,
    name: str,
    position: Optional[str],
    email: Optional[str],
    actor_id: Optional[int],
) -> Contact:
    """Kontakt klienta dla wpisanej osoby — istniejący tej osoby albo nowy."""

    cleaned = clean_person_name(name)
    if cleaned is None or len(name_key(cleaned)) < 2:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, NEW_PERSON_NAME_DETAIL
        )
    resolved = await find_or_create_contact(
        db,
        client_id=contract.client_id,
        name=cleaned,
        position=position,
        email=email,
        actor_id=actor_id,
        # Ślad zakładania kontaktu wskazuje rekrutację, z której przyszedł
        # konsultant (może jej nie być — kontrakt spoza rekrutacji).
        job_id=contract.job_id,
    )
    return resolved.contact


async def default_from_job(
    db: AsyncSession, *, job: Optional[Job], client_id: int
) -> Optional[int]:
    """Hiring manager rekrutacji jako menedżer — tylko kontakt klienta kontraktu."""

    if job is None or job.hiring_manager_contact_id is None:
        return None
    owner = await db.scalar(
        select(Contact.client_id).where(Contact.id == job.hiring_manager_contact_id)
    )
    return job.hiring_manager_contact_id if owner == client_id else None


def _exact_key(value: Optional[str]) -> Optional[str]:
    """Imię i nazwisko do dokładnego porównania: pojedyncze spacje, bez wielkości liter."""

    text = " ".join((value or "").split()).casefold()
    return text or None


def text_hint(
    contacts: Sequence[Contact],
    *,
    line_manager: Optional[str],
    client_pm_name: Optional[str],
) -> Optional[dict[str, Any]]:
    """Podpowiedź „Przypnij: X” z tekstu Line Manager albo PM (w tej kolejności).

    Tylko dokładne imię i nazwisko kontaktu — skrót („Michał R.”) albo samo imię
    nie podpowiada nikogo, bo przypięcie złej osoby zabrałoby opinię innemu
    menedżerowi. Kilku imienników → najniższe ``id`` (jak hiring manager).
    """

    for source, text in (
        ("line_manager", line_manager),
        ("client_pm_name", client_pm_name),
    ):
        key = _exact_key(text)
        if key is None or " " not in key:
            continue
        matches = [c for c in contacts if _exact_key(c.name) == key]
        if matches:
            contact = min(matches, key=lambda c: c.id)
            return {
                "contact_id": contact.id,
                "name": contact.name,
                "position": contact.position,
                "source": source,
                "text": " ".join((text or "").split()),
            }
    return None


async def client_contacts(
    db: AsyncSession, client_ids: Iterable[int]
) -> dict[int, list[Contact]]:
    ids = sorted(set(client_ids))
    out: dict[int, list[Contact]] = {cid: [] for cid in ids}
    if not ids:
        return out
    for contact in (
        await db.scalars(select(Contact).where(Contact.client_id.in_(ids)))
    ).all():
        out[contact.client_id].append(contact)
    return out


async def detail_fields(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    """Pola odpowiedzi szczegółów: imię i stanowisko menedżera albo podpowiedź."""

    if contract.client_pm_contact_id is not None:
        contact = await db.get(Contact, contract.client_pm_contact_id)
        return {
            "client_pm_contact_name": contact.name if contact else None,
            "client_pm_contact_position": contact.position if contact else None,
            "client_pm_contact_hint": None,
        }
    contacts = (await client_contacts(db, [contract.client_id]))[contract.client_id]
    return {
        "client_pm_contact_name": None,
        "client_pm_contact_position": None,
        "client_pm_contact_hint": text_hint(
            contacts,
            line_manager=contract.line_manager,
            client_pm_name=contract.client_pm_name,
        ),
    }
