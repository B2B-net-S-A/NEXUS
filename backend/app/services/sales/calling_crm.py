"""Dzwonienie → CRM: wynik rozmowy uzupełnia Leady i szansę ze spotkania (13.11.2026).

Decyzja Artura z 13.11.2026 (lista zmian od osób dzwoniących):

- **„Oferta ogólna wysłana”** zakłada wpis w Sprzedaż → Leady (status „W kontakcie”),
  wypełniony z rekordu: firma, NIP, osoba, stanowisko, telefon, adres, LinkedIn, usługa
  i uwagi. To nie jest szansa: decyzja z 10.11.2026 („wynik telefonu nie jest szansą”,
  94 szanse w 3 dni) zostaje. Jeden lead na rekord (``fingerprint`` ``call|<id>``),
  kolejna oferta go odświeża.
- **„Umówione spotkanie”** zamyka lead rekordu jako „Szanse” z odnośnikiem do szansy
  i dopisuje do pustego opisu szansy te same dane.

Bez migracji: lead ma źródło ``manual`` i ``payload.origin = "calling"`` (front
podpisuje go „Dzwonienie”). Firma, która jest klientem NEXUSA, leada nie dostaje
(reguła z 22.10.2026: popyt u klienta idzie do Delivery Leada).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesContact,
    SalesLead,
    SalesOpportunity,
)

LEAD_ORIGIN = "calling"
LEAD_SOURCE = "manual"
OFFER_TITLE = "Oferta ogólna wysłana"
TITLE_CHARS = 500


def lead_fingerprint(record_id: int) -> str:
    return f"call|{record_id}"


def _person(record: SalesCallRecord, contact: Optional[SalesContact]) -> Optional[str]:
    return record.person_name or (contact.full_name if contact else None)


def record_facts(
    record: SalesCallRecord,
    *,
    company: SalesCompany,
    contact: Optional[SalesContact],
    service: Optional[str],
) -> dict[str, Any]:
    """Dane rekordu do leada i szansy; puste pola odpadają."""

    facts = {
        "origin": LEAD_ORIGIN,
        "record_id": record.id,
        "campaign_id": record.campaign_id,
        "service": service,
        "person_name": _person(record, contact),
        "title": record.person_title or (contact.title if contact else None),
        "phone": record.phone,
        "email": record.email or (contact.email if contact else None),
        "linkedin": contact.linkedin_url if contact else None,
        "nip": company.nip,
        "website": company.website_url,
        "note": record.note,
        "contact_source": record.contact_source,
    }
    return {key: value for key, value in facts.items() if value not in (None, "")}


def facts_summary(
    facts: dict[str, Any], *, callback_on: Optional[date], call_note: Optional[str]
) -> str:
    person = ", ".join(
        part for part in (facts.get("person_name"), facts.get("title")) if part
    )
    lines = [
        f"Osoba: {person}" if person else None,
        f"Telefon: {facts['phone']}" if facts.get("phone") else None,
        f"E-mail: {facts['email']}" if facts.get("email") else None,
        f"LinkedIn: {facts['linkedin']}" if facts.get("linkedin") else None,
        f"NIP: {facts['nip']}" if facts.get("nip") else None,
        f"Usługa: {facts['service']}" if facts.get("service") else None,
        f"Skąd kontakt: {facts['contact_source']}"
        if facts.get("contact_source")
        else None,
        (
            f"Ponowny kontakt: {callback_on.strftime('%d.%m.%Y')}"
            if callback_on
            else "Bez ponownego kontaktu"
        )
        if "callback" in facts
        else None,
        f"Uwagi: {facts['note']}" if facts.get("note") else None,
        f"Z rozmowy: {call_note.strip()}" if call_note and call_note.strip() else None,
    ]
    return "\n".join(line for line in lines if line)


async def _service(db: AsyncSession, record: SalesCallRecord) -> Optional[str]:
    if record.campaign_id is None:
        return None
    return await db.scalar(
        select(SalesCallCampaign.service).where(
            SalesCallCampaign.id == record.campaign_id
        )
    )


async def offer_lead(
    db: AsyncSession,
    record: SalesCallRecord,
    *,
    company: SalesCompany,
    contact: Optional[SalesContact],
    note: Optional[str],
    user_id: int,
    now: datetime,
) -> SalesLead:
    """Lead „W kontakcie” z wysłanej oferty; kolejna oferta odświeża ten sam wpis."""

    service = await _service(db, record)
    facts = record_facts(record, company=company, contact=contact, service=service)
    facts["callback"] = record.callback_on.isoformat() if record.callback_on else None
    summary = facts_summary(facts, callback_on=record.callback_on, call_note=note)
    title = f"{OFFER_TITLE}: {service}" if service else OFFER_TITLE
    fingerprint = lead_fingerprint(record.id)
    lead = await db.scalar(
        select(SalesLead).where(SalesLead.fingerprint == fingerprint)
    )
    if lead is None:
        lead = SalesLead(source=LEAD_SOURCE, fingerprint=fingerprint)
        db.add(lead)
    elif lead.status == "converted":
        return lead
    lead.status = "contacted"
    lead.dismissed_reason = None
    lead.title = title[:TITLE_CHARS]
    lead.summary = summary or None
    lead.company_id = company.id
    lead.company_name = company.name
    lead.url = company.website_url
    lead.signal_at = now
    lead.payload = facts
    lead.assignee_user_id = record.assigned_user_id or user_id
    await db.flush()
    return lead


async def meeting_booked(
    db: AsyncSession,
    record: SalesCallRecord,
    opportunity: SalesOpportunity,
    *,
    company: SalesCompany,
    contact: Optional[SalesContact],
) -> None:
    """Spotkanie z rekordu: lead rekordu przechodzi w „Szanse”, szansa dostaje dane."""

    lead = await db.scalar(
        select(SalesLead).where(SalesLead.fingerprint == lead_fingerprint(record.id))
    )
    if lead is not None and lead.status != "converted":
        lead.status = "converted"
        lead.opportunity_id = opportunity.id
    if opportunity.primary_contact_id is None and contact is not None:
        opportunity.primary_contact_id = contact.id
    if not (opportunity.description or "").strip():
        facts = record_facts(
            record,
            company=company,
            contact=contact,
            service=await _service(db, record),
        )
        opportunity.description = (
            facts_summary(facts, callback_on=None, call_note=None) or None
        )
