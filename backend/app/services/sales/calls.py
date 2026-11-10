"""Zapis rozmowy z karty szansy: jeden wynik, jeden wpis, ewentualny sprzeciw.

Sprzeciw leży przy kontakcie (``do_not_contact_at``), a gdy osoba z mapy decyzyjnej
kontaktu nie ma, przy jej wpisie na mapie: mapa nie zakłada nowych kontaktów.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesActivity,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
)
from app.services import sales_schema as schema
from app.services.sales import decision_map, history
from app.services.sales.motion import entry_keys, resolve_contacts
from app.services.sales_schema import OpportunityEventKind

DO_NOT_CONTACT = "do_not_contact"
OUTCOME_LABELS: dict[str, str] = {
    "connected": "Dodzwoniłem",
    "no_answer": "Nie odebrał",
    "call_back": "Oddzwonić",
    "wants_offer": "Prosi o ofertę",
    "not_now": "Nie teraz",
    DO_NOT_CONTACT: "Nie kontaktować",
    # Wyniki z kolejki dzwonienia (``services/sales/calling.py``).
    "offer_sent": "Oferta ogólna wysłana",
    "meeting_booked": "Umówione spotkanie",
}
OBJECTION_DETAIL = "Ta osoba zgłosiła sprzeciw wobec kontaktu, nie zapisujemy rozmowy."
STALE_PERSON_DETAIL = (
    "Ktoś właśnie zmienił tę osobę na mapie. Odśwież kartę i wybierz ją ponownie."
)
OTHER_COMPANY_DETAIL = "Ta osoba nie należy do firmy tej szansy."
NO_PERSON_DETAIL = "Wskaż osobę, której dotyczy sprzeciw."

Outcome = Literal[schema.CALL_OUTCOMES]  # type: ignore[valid-type]


class CallLogRequest(BaseModel):
    outcome: Outcome
    contact_id: Optional[int] = None
    #: Klucz osoby z mapy decyzyjnej (``motion.entry_keys``).
    person_key: Optional[str] = Field(default=None, max_length=32)
    note: Optional[str] = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _one_person(self) -> "CallLogRequest":
        if self.contact_id is not None and self.person_key is not None:
            raise ValueError("Wskaż jedną osobę.")
        return self


class CompanyCallRequest(BaseModel):
    """Telefon przy firmie bez szansy, np. zaległe zadanie założone przy samej firmie."""

    outcome: Outcome
    contact_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=5000)


@dataclass
class _Person:
    name: Optional[str] = None
    contact: Optional[SalesContact] = None
    map_index: Optional[int] = None


async def _contact_in_company(
    db: AsyncSession, opp: SalesOpportunity, contact_id: int
) -> SalesContact:
    linked_company = select(SalesCompanyContact.contact_id).where(
        SalesCompanyContact.company_id == opp.company_id
    )
    linked_opportunity = select(SalesOpportunityContact.contact_id).where(
        SalesOpportunityContact.opportunity_id == opp.id
    )
    contact = await db.scalar(
        select(SalesContact).where(
            SalesContact.id == contact_id,
            or_(
                SalesContact.company_id == opp.company_id,
                SalesContact.id.in_(linked_company),
                SalesContact.id.in_(linked_opportunity),
            ),
        )
    )
    if contact is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OTHER_COMPANY_DETAIL
        )
    return contact


async def _resolve_person(
    db: AsyncSession, opp: SalesOpportunity, payload: CallLogRequest
) -> tuple[_Person, list[dict[str, Any]]]:
    entries = decision_map.decision_entries(opp.custom_fields)
    if payload.contact_id is not None:
        contact = await _contact_in_company(db, opp, payload.contact_id)
        return _Person(name=contact.full_name, contact=contact), entries
    if payload.person_key is None:
        return _Person(), entries
    keys = entry_keys(entries)
    if payload.person_key not in keys:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=STALE_PERSON_DETAIL)
    index = keys.index(payload.person_key)
    entry = entries[index]
    [contact_id] = await resolve_contacts(db, opp.company_id, [entry])
    contact = await db.get(SalesContact, contact_id) if contact_id else None
    return _Person(name=entry.get("name"), contact=contact, map_index=index), entries


def _objected(person: _Person, entries: list[dict[str, Any]]) -> bool:
    if person.contact is not None and person.contact.do_not_contact_at is not None:
        return True
    return person.map_index is not None and bool(
        entries[person.map_index].get("do_not_contact")
    )


def _save_objection(
    db: AsyncSession,
    opp: SalesOpportunity,
    person: _Person,
    entries: list[dict[str, Any]],
    *,
    user_id: int,
    now: datetime,
) -> None:
    if person.contact is not None:
        person.contact.do_not_contact_at = now
        person.contact.do_not_contact_by_user_id = user_id
    elif person.map_index is not None:
        entries[person.map_index] = {
            **entries[person.map_index],
            "do_not_contact": True,
        }
        opp.custom_fields = decision_map.with_entries(
            opp.custom_fields, entries, user_id=user_id, now=now
        )
    history.record(
        db,
        opportunity_id=opp.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field="do_not_contact",
        new_value=person.name,
    )


async def log_call(
    db: AsyncSession,
    opp: SalesOpportunity,
    payload: CallLogRequest,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Zapisuje rozmowę bez commita; „Nie kontaktować” nie zakłada kroku."""

    person, entries = await _resolve_person(db, opp, payload)
    objecting = payload.outcome == DO_NOT_CONTACT
    if objecting and person.name is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=NO_PERSON_DETAIL
        )
    if _objected(person, entries):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OBJECTION_DETAIL)
    label = OUTCOME_LABELS[payload.outcome]
    db.add(
        SalesActivity(
            kind="call",
            outcome=payload.outcome,
            subject=f"{label}: {person.name}" if person.name else label,
            body=(payload.note or "").strip() or None,
            direction="out",
            company_id=opp.company_id,
            opportunity_id=opp.id,
            contact_id=person.contact.id if person.contact is not None else None,
            created_by_user_id=user_id,
            occurred_at=now,
            done_at=now,
        )
    )
    if opp.last_activity_at is None or opp.last_activity_at < now:
        opp.last_activity_at = now
    if objecting:
        _save_objection(db, opp, person, entries, user_id=user_id, now=now)


async def log_company_call(
    db: AsyncSession,
    company_id: int,
    payload: CompanyCallRequest,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Jak ``log_call``, tylko przy firmie: bez mapy decyzyjnej i bez szansy."""

    contact: Optional[SalesContact] = None
    if payload.contact_id is not None:
        linked = select(SalesCompanyContact.contact_id).where(
            SalesCompanyContact.company_id == company_id
        )
        contact = await db.scalar(
            select(SalesContact).where(
                SalesContact.id == payload.contact_id,
                or_(SalesContact.company_id == company_id, SalesContact.id.in_(linked)),
            )
        )
        if contact is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OTHER_COMPANY_DETAIL
            )
    objecting = payload.outcome == DO_NOT_CONTACT
    if objecting and contact is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=NO_PERSON_DETAIL
        )
    if contact is not None and contact.do_not_contact_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OBJECTION_DETAIL)
    label = OUTCOME_LABELS[payload.outcome]
    db.add(
        SalesActivity(
            kind="call",
            outcome=payload.outcome,
            subject=f"{label}: {contact.full_name}" if contact else label,
            body=(payload.note or "").strip() or None,
            direction="out",
            company_id=company_id,
            contact_id=contact.id if contact else None,
            created_by_user_id=user_id,
            occurred_at=now,
            done_at=now,
        )
    )
    if objecting and contact is not None:
        contact.do_not_contact_at = now
        contact.do_not_contact_by_user_id = user_id
