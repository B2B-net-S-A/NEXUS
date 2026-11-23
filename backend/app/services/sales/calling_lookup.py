"""Kto dzwoni? Szukanie firmy i osoby po numerze (zgłoszenie dzwoniących, 23.11.2026).

Klient oddzwania na numer, pod który nie dało się dodzwonić, a telefon pokazuje sam
numer. Pole „Firma, osoba, numer” w Tabeli porównywało tekst, więc „+48 500 058 777”
nie znajdowało się po wpisaniu 500058777 (na kopii z 23.11: 562 z 4953 numerów list).
Tu porównujemy ostatnie dziewięć cyfr, bez względu na +48, spacje i myślniki, w listach
dzwonienia wszystkich osób i w kontaktach firm (telefon i komórka).

Numer wpisuje osoba, która go zna, więc odpowiedź nie oddaje żadnego numeru.
Rekord i kontakt ze sprzeciwem też są na liście, z ``do_not_contact``: oddzwaniający
klient ma się dowiedzieć, że nie dzwonimy do niego z kolejki, a nie zobaczyć „brak”.
Makiety: https://claude.ai/artifact/Gxjj6erDvtVBijP4S73g6p (punkt 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesContact,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.sales.calls import DO_NOT_CONTACT

#: Ile cyfr porównujemy: polski numer bez kierunkowego.
PHONE_DIGITS = 9
MATCH_LIMIT = 20


def phone_tail(value: Optional[str]) -> Optional[str]:
    """Ostatnie dziewięć cyfr numeru albo ``None``, gdy cyfr jest mniej."""

    digits = "".join(char for char in (value or "") if char.isdigit())
    return digits[-PHONE_DIGITS:] if len(digits) >= PHONE_DIGITS else None


def phone_digits_sql(column: Any) -> Any:
    """Same cyfry numeru po stronie bazy (bez indeksu: kilka tysięcy wierszy)."""

    return func.regexp_replace(func.coalesce(column, ""), r"\D", "", "g")


def phone_tail_sql(column: Any) -> Any:
    """To samo co :func:`phone_tail` po stronie bazy."""

    return func.right(phone_digits_sql(column), PHONE_DIGITS)


@dataclass(frozen=True)
class PhoneMatch:
    company_id: int
    company_name: str
    person_name: Optional[str]
    person_title: Optional[str]
    do_not_contact: bool
    #: Rekord listy dzwonienia; ``None`` dla samego kontaktu firmy.
    record_id: Optional[int] = None
    record_state: Optional[str] = None
    callback_on: Optional[Any] = None
    last_outcome_at: Optional[Any] = None
    campaign_name: Optional[str] = None
    caller_name: Optional[str] = None
    contact_id: Optional[int] = None


async def find_by_phone(db: AsyncSession, phone: str) -> list[PhoneMatch]:
    """Rekordy list dzwonienia i kontakty firm z tym numerem, najpierw rekordy."""

    tail = phone_tail(phone)
    if tail is None:
        return []
    objecting_company = SalesCompany.status == schema.CompanyStatus.do_not_contact.value
    record_rows = (
        await db.execute(
            select(
                SalesCallRecord,
                SalesCompany.name,
                SalesCallCampaign.name,
                User.name,
                objecting_company,
                SalesContact.do_not_contact_at,
            )
            .join(SalesCompany, SalesCompany.id == SalesCallRecord.company_id)
            .outerjoin(
                SalesCallCampaign, SalesCallCampaign.id == SalesCallRecord.campaign_id
            )
            .outerjoin(User, User.id == SalesCallRecord.assigned_user_id)
            .outerjoin(SalesContact, SalesContact.id == SalesCallRecord.contact_id)
            .where(phone_tail_sql(SalesCallRecord.phone) == tail)
            .order_by(SalesCallRecord.updated_at.desc(), SalesCallRecord.id.desc())
            .limit(MATCH_LIMIT)
        )
    ).all()
    matches = [
        PhoneMatch(
            company_id=record.company_id,
            company_name=company_name,
            person_name=record.person_name,
            person_title=record.person_title,
            do_not_contact=bool(
                record.state == DO_NOT_CONTACT or objecting or objected_at is not None
            ),
            record_id=record.id,
            record_state=record.state,
            callback_on=record.callback_on,
            last_outcome_at=record.last_outcome_at,
            campaign_name=campaign_name,
            caller_name=caller_name,
            contact_id=record.contact_id,
        )
        for (
            record,
            company_name,
            campaign_name,
            caller_name,
            objecting,
            objected_at,
        ) in record_rows
    ]

    known = {match.contact_id for match in matches if match.contact_id is not None}
    contact_rows = (
        await db.execute(
            select(SalesContact, SalesCompany.name, objecting_company)
            .join(SalesCompany, SalesCompany.id == SalesContact.company_id)
            .where(
                SalesContact.archived_at.is_(None),
                or_(
                    phone_tail_sql(SalesContact.phone) == tail,
                    phone_tail_sql(SalesContact.mobile_phone) == tail,
                ),
            )
            .order_by(SalesContact.updated_at.desc(), SalesContact.id.desc())
            .limit(MATCH_LIMIT)
        )
    ).all()
    for contact, company_name, objecting in contact_rows:
        if contact.id in known:
            continue
        matches.append(
            PhoneMatch(
                company_id=contact.company_id,
                company_name=company_name,
                person_name=contact.full_name,
                person_title=contact.title,
                do_not_contact=bool(objecting or contact.do_not_contact_at is not None),
                contact_id=contact.id,
            )
        )
    return matches[:MATCH_LIMIT]
