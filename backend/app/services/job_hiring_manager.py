"""Hiring manager rekrutacji: wybór kontaktu klienta albo nowa osoba (25.09.2026).

Do 25.09 hiring managera dało się wybrać wyłącznie z kontaktów klienta, a
kontakt zakładał tylko admin albo Delivery Lead — produkcja miała HM na 0 z
4349 rekrutacji, a 10 z 23 klientów z rekrutacjami nie miało żadnego kontaktu.
Decyzja Artura: osobę wpisuje każdy, kto redaguje rekrutację (także rekruter),
a serwis zakłada ją jako kontakt KLIENTA tej rekrutacji.

Weto hiring managera dopasowuje rekrutacje po ``hiring_manager_contact_id``,
więc dwa rekordy tej samej osoby rozbiłyby weto na dwie osoby. Dlatego wpisana
osoba najpierw jest szukana wśród kontaktów klienta (imię i nazwisko w dowolnej
kolejności, bez wielkości liter i polskich znaków; potem e-mail), a nowy
kontakt powstaje dopiero bez trafienia. Ten sam matcher czyta odczyt maila
klienta (``job_request_intake``), żeby podpowiedź wskazywała istniejący kontakt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.client_access import record_client_audit

NAME_MAX = 255
POSITION_MAX = 255
EMAIL_MAX = 255

_WORD_RE = re.compile(r"[^\s,;]+")


def name_key(name: Optional[str]) -> frozenset[str]:
    """Zbiór złożonych słów imienia i nazwiska.

    „Jan Kowalski”, „kowalski jan” i „Jan  KOWALSKI” dają ten sam klucz;
    „Łukasz” i „Lukasz” też (transliteracja ``normalize_person_name_part``).
    Nazwisko dwuczłonowe z łącznikiem jest jednym słowem („nowakkowalska”).
    """

    parts = (normalize_person_name_part(word) for word in _WORD_RE.findall(name or ""))
    return frozenset(part for part in parts if part)


def clean_person_name(value: Optional[str]) -> Optional[str]:
    """Imię i nazwisko do zapisu: pojedyncze spacje, bez spacji na końcach."""

    text = " ".join((value or "").split())
    return text or None


def _clean_optional(value: Optional[str], limit: int) -> Optional[str]:
    text = " ".join((value or "").split())
    return text[:limit] or None


def validate_new_person_name(name: Optional[str]) -> str:
    cleaned = clean_person_name(name)
    if cleaned is None or len(name_key(cleaned)) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Podaj imię i nazwisko hiring managera.",
        )
    if len(cleaned) > NAME_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Imię i nazwisko hiring managera jest za długie.",
        )
    return cleaned


def pick_matching_contact(
    contacts: list[Contact], *, name: Optional[str], email: Optional[str]
) -> Optional[Contact]:
    """Kontakt tej samej osoby: najpierw po imieniu i nazwisku, potem po e-mailu.

    Kilka trafień (duplikaty sprzed tej reguły) → najniższe ``id``, żeby weto
    zawsze trafiało w ten sam wiersz.
    """

    key = name_key(name)
    if len(key) >= 2:
        by_name = [c for c in contacts if name_key(c.name) == key]
        if by_name:
            return min(by_name, key=lambda c: c.id)
    mail = (email or "").strip().casefold()
    if mail:
        by_mail = [c for c in contacts if (c.email or "").strip().casefold() == mail]
        if by_mail:
            return min(by_mail, key=lambda c: c.id)
    return None


async def _client_contacts(db: AsyncSession, client_id: int) -> list[Contact]:
    return list(
        (await db.execute(select(Contact).where(Contact.client_id == client_id)))
        .scalars()
        .all()
    )


async def match_client_contact(
    db: AsyncSession, *, client_id: int, name: Optional[str], email: Optional[str]
) -> Optional[Contact]:
    return pick_matching_contact(
        await _client_contacts(db, client_id), name=name, email=email
    )


@dataclass(frozen=True)
class ResolvedContact:
    contact: Contact
    created: bool


async def find_or_create_contact(
    db: AsyncSession,
    *,
    client_id: int,
    name: str,
    position: Optional[str],
    email: Optional[str],
    actor_id: int,
    job_id: int,
) -> ResolvedContact:
    """Istniejący kontakt tej osoby u klienta albo nowy — nigdy duplikat.

    Trafienie uzupełnia WYŁĄCZNIE puste stanowisko i e-mail: kontakt prowadzi
    Delivery, więc wpis z rekrutacji niczego tam nie nadpisuje.
    """

    cleaned_name = validate_new_person_name(name)
    clean_position = _clean_optional(position, POSITION_MAX)
    clean_email = _clean_optional(email, EMAIL_MAX)
    existing = await match_client_contact(
        db, client_id=client_id, name=cleaned_name, email=clean_email
    )
    if existing is not None:
        filled: list[str] = []
        if clean_position and not (existing.position or "").strip():
            existing.position = clean_position
            filled.append("position")
        if clean_email and not (existing.email or "").strip():
            existing.email = clean_email
            filled.append("email")
        if filled:
            record_client_audit(
                db,
                client_id=client_id,
                actor_id=actor_id,
                action="contact_updated",
                details={
                    "contact_id": existing.id,
                    "fields": filled,
                    "source": "job_hiring_manager",
                    "job_id": job_id,
                },
            )
        return ResolvedContact(contact=existing, created=False)

    contact = Contact(
        client_id=client_id,
        name=cleaned_name,
        position=clean_position,
        email=clean_email,
    )
    db.add(contact)
    await db.flush()
    record_client_audit(
        db,
        client_id=client_id,
        actor_id=actor_id,
        action="contact_created",
        details={
            "contact_id": contact.id,
            "source": "job_hiring_manager",
            "job_id": job_id,
        },
    )
    return ResolvedContact(contact=contact, created=True)


async def assert_contact_of_client(
    db: AsyncSession, *, contact_id: int, client_id: Optional[int]
) -> Contact:
    """Hiring manager musi być kontaktem klienta tej rekrutacji (422 inaczej)."""

    contact = await db.get(Contact, contact_id)
    if contact is None or client_id is None or contact.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Hiring manager musi być osobą z firmy klienta tej rekrutacji.",
        )
    return contact


async def hiring_manager_options(
    db: AsyncSession, *, client_id: int
) -> list[dict[str, object]]:
    """Wąska lista kontaktów klienta do wyboru HM: id, imię i nazwisko, stanowisko.

    Bez e-maila, telefonu i notatek — lista trafia do każdego, kto redaguje
    rekrutację, a pełne kontakty klienta są za bramką Delivery.
    """

    rows = await _client_contacts(db, client_id)
    rows.sort(
        key=lambda c: (
            not c.is_key_relationship,
            not c.is_decision_maker,
            (c.name or "").casefold(),
        )
    )
    return [{"id": c.id, "name": c.name, "position": c.position} for c in rows]
