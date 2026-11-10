"""Kontakty sprzedaży: firma główna osoby i sprzeciw wobec kontaktu.

Wspólne dla tras kontaktów i formularza „Umów spotkanie”, który zakłada osobę
razem z szansą: obie ścieżki mają dawać ten sam wiersz powiązania i tę samą
odmowę dla osoby ze sprzeciwem.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompanyContact, SalesContact

OBJECTION_DETAIL = "Ta osoba zgłosiła sprzeciw wobec kontaktu, numeru nie zapisujemy."
PHONE_FIELDS = ("phone", "mobile_phone")


async def set_primary_company(
    db: AsyncSession, contact: SalesContact, company_id: Optional[int]
) -> None:
    """Firma główna = jedyny wiersz powiązania z ``is_primary``."""

    await db.execute(
        update(SalesCompanyContact)
        .where(
            SalesCompanyContact.contact_id == contact.id,
            SalesCompanyContact.company_id != (company_id or 0),
            SalesCompanyContact.is_primary.is_(True),
        )
        .values(is_primary=False)
    )
    if company_id is None:
        return
    await db.execute(
        insert(SalesCompanyContact)
        .values(
            company_id=company_id,
            contact_id=contact.id,
            title=contact.title,
            is_primary=True,
        )
        .on_conflict_do_update(
            index_elements=["company_id", "contact_id"],
            set_={"is_primary": True},
        )
    )


async def ensure_new_person_not_objected(
    db: AsyncSession, full_name: str, fields: dict[str, Any]
) -> None:
    """Sprzeciw zostaje też wtedy, gdy numer przyjdzie pod „nową osobą” o tej nazwie."""

    company_id = fields.get("company_id")
    if company_id is None or not any(fields.get(key) for key in PHONE_FIELDS):
        return
    linked = select(SalesCompanyContact.contact_id).where(
        SalesCompanyContact.company_id == company_id
    )
    objected = await db.scalar(
        select(SalesContact.id)
        .where(
            func.lower(SalesContact.full_name) == full_name.lower(),
            SalesContact.do_not_contact_at.is_not(None),
            or_(SalesContact.company_id == company_id, SalesContact.id.in_(linked)),
        )
        .limit(1)
    )
    if objected is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=OBJECTION_DETAIL)
