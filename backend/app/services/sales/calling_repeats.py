"""Powtórki na liście dzwonienia: ten sam numer, adres albo osoba w innym rekordzie.

Zgłoszenie osób dzwoniących z 17.11.2026 (``docs/claude/sprzedaz/dzwonienie-powtorki-i-firmy-w-crm.md``):
lista z 13.11 wprowadziła do kolejki 380 numerów, pod które już dzwoniono, bo import
porównywał imię i nazwisko („Nowacka” ≠ „Ewa Nowacka”), a nie numer. Do tego rekord
z listy bez wyniku wracał jako „Nowy”, choć ofertę zapisano już jako szansę w CRM.

Ten moduł odpowiada na dwa pytania:

- czy pod tym numerem, adresem albo osobą był już wynik rozmowy (``called_records``,
  ``earlier_calls``) — bramka importu „Już dzwoniono” i ostrzeżenie na karcie;
- czy rekord kampanii ktoś już przejął w CRM (``crm_opportunity``) — kolejka go
  pomija (``queue_conditions``), a karta mówi, gdzie jest szansa.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import DEFAULT_TZ
from app.models.sales import (
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesOpportunity,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.sales.calling_file import MIN_PHONE_DIGITS, phone_digits, valid_email
from app.services.sales.calls import OUTCOME_LABELS

NEW = schema.CALL_RECORD_NEW
EARLIER_LIMIT = 3


def phone_key(column: Any) -> Any:
    """SQL-owe lustro ``calling_file.phone_digits``: same cyfry bez „00” i prefiksu 48."""

    digits = func.regexp_replace(func.coalesce(column, ""), r"\D", "", "g")
    no_intl = case((digits.like("00%"), func.substr(digits, 3)), else_=digits)
    return case(
        (
            and_(func.length(no_intl) == 11, no_intl.like("48%")),
            func.substr(no_intl, 3),
        ),
        else_=no_intl,
    )


def email_key(column: Any) -> Any:
    return func.lower(func.trim(column))


@dataclass(frozen=True)
class EarlierCall:
    """Rekord z wynikiem pod tym samym numerem, adresem albo osobą."""

    record_id: int
    company_id: int
    company_name: str
    person_name: Optional[str]
    state: str
    at: datetime
    caller_name: Optional[str]
    campaign_name: Optional[str]
    #: Same cyfry numeru i adres: po nich import łączy wiersz z rekordem.
    phone_key: Optional[str] = None
    email_key: Optional[str] = None
    contact_id: Optional[int] = None

    @property
    def label(self) -> str:
        """„11.11 · Osoba Dzwoniąca · Nie zainteresowany (Ewa Nowacka)”."""

        day = self.at.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m")
        outcome = OUTCOME_LABELS.get(self.state, self.state)
        parts = [day, self.caller_name, outcome]
        text = " · ".join(part for part in parts if part)
        return f"{text} ({self.person_name})" if self.person_name else text


@dataclass(frozen=True)
class CrmOpportunity:
    """Otwarta szansa firmy założona po rekordzie z listy."""

    id: int
    title: str
    stage_name: str
    owner_name: Optional[str]
    created_at: datetime


async def called_records(
    db: AsyncSession,
    *,
    phones: Iterable[str] = (),
    emails: Iterable[str] = (),
    contact_ids: Iterable[int] = (),
    exclude_id: Optional[int] = None,
    with_new: bool = False,
) -> list[EarlierCall]:
    """Rekordy pod tymi numerami, adresami albo osobami, od najświeższej zmiany.

    Bez ``with_new`` tylko rekordy z wynikiem (stan inny niż „Nowy”).
    """

    phones, emails, contact_ids = set(phones), set(emails), set(contact_ids)
    matches = []
    if phones:
        matches.append(phone_key(SalesCallRecord.phone).in_(sorted(phones)))
    if emails:
        matches.append(email_key(SalesCallRecord.email).in_(sorted(emails)))
    if contact_ids:
        matches.append(SalesCallRecord.contact_id.in_(sorted(contact_ids)))
    if not matches:
        return []
    happened = func.coalesce(
        SalesCallRecord.last_outcome_at, SalesCallRecord.updated_at
    )
    query = (
        select(
            SalesCallRecord.id,
            SalesCallRecord.company_id,
            SalesCompany.name,
            SalesCallRecord.person_name,
            SalesCallRecord.state,
            happened,
            User.name,
            SalesCallCampaign.name,
            SalesCallRecord.phone,
            SalesCallRecord.email,
            SalesCallRecord.contact_id,
        )
        .join(SalesCompany, SalesCompany.id == SalesCallRecord.company_id)
        .outerjoin(User, User.id == SalesCallRecord.assigned_user_id)
        .outerjoin(
            SalesCallCampaign, SalesCallCampaign.id == SalesCallRecord.campaign_id
        )
        .where(or_(*matches))
        .order_by(happened.desc(), SalesCallRecord.id.desc())
    )
    if not with_new:
        query = query.where(SalesCallRecord.state != NEW)
    if exclude_id is not None:
        query = query.where(SalesCallRecord.id != exclude_id)
    return [
        EarlierCall(
            record_id=row[0],
            company_id=row[1],
            company_name=row[2],
            person_name=row[3],
            state=row[4],
            at=row[5],
            caller_name=row[6],
            campaign_name=row[7],
            phone_key=phone_digits(row[8]),
            email_key=valid_email(row[9]),
            contact_id=row[10],
        )
        for row in (await db.execute(query)).all()
    ]


async def earlier_calls(db: AsyncSession, record: SalesCallRecord) -> list[EarlierCall]:
    """Karta rozmowy: wcześniejsze wyniki pod numerem, adresem albo osobą tego rekordu."""

    phone = phone_digits(record.phone)
    email = valid_email(record.email)
    found = await called_records(
        db,
        phones=[phone] if phone else [],
        emails=[email] if email else [],
        contact_ids=[record.contact_id] if record.contact_id else [],
        exclude_id=record.id,
    )
    return found[:EARLIER_LIMIT]


def _crm_after(record: Any, opportunity: Any) -> list[Any]:
    """Otwarta szansa firmy rekordu, założona po jego ostatnim wyniku albo imporcie."""

    return [
        opportunity.company_id == record.company_id,
        opportunity.status == "open",
        opportunity.archived_at.is_(None),
        opportunity.created_at
        > func.coalesce(record.last_outcome_at, record.created_at),
    ]


async def crm_opportunity(
    db: AsyncSession, record: SalesCallRecord
) -> Optional[CrmOpportunity]:
    """Rekord z listy, którego firmę ktoś już prowadzi w CRM (np. oferta jako szansa)."""

    if record.campaign_id is None:
        return None
    row = (
        await db.execute(
            select(
                SalesOpportunity.id,
                SalesOpportunity.title,
                SalesPipelineStage.name,
                User.name,
                SalesOpportunity.created_at,
            )
            .join(
                SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
            )
            .outerjoin(User, User.id == SalesOpportunity.owner_user_id)
            .where(*_crm_after(record, SalesOpportunity))
            .order_by(SalesOpportunity.created_at.desc())
            .limit(1)
        )
    ).first()
    return CrmOpportunity(*row) if row else None


def queue_conditions(record: Any = SalesCallRecord) -> list[Any]:
    """Warunki kolejki dla rekordów kampanii (17.11.2026).

    - Firma z otwartą szansą założoną po rekordzie jest już w CRM: dzwoni się przez
      szansę, nie drugi raz z listy.
    - Nowy rekord pod numerem, adresem albo osobą, które mają już wynik w innym
      rekordzie, to powtórka z kolejnej listy: tamten rekord wraca w swoim dniu.
    """

    later = aliased(SalesOpportunity)
    other = aliased(SalesCallRecord)
    own_phone = phone_key(record.phone)
    same_person = or_(
        and_(
            func.length(own_phone) >= MIN_PHONE_DIGITS,
            phone_key(other.phone) == own_phone,
        ),
        and_(
            record.email.is_not(None),
            email_key(other.email) == email_key(record.email),
        ),
        and_(record.contact_id.is_not(None), other.contact_id == record.contact_id),
    )
    called_before = exists().where(
        other.id != record.id, other.state != NEW, same_person
    )
    return [
        ~exists().where(*_crm_after(record, later)),
        or_(record.state != NEW, ~called_before),
    ]
