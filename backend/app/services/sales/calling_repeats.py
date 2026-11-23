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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import DEFAULT_TZ
from app.models.sales import (
    SalesActivity,
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.sales.calling_file import MIN_PHONE_DIGITS, phone_digits, valid_email
from app.services.sales.calls import OUTCOME_LABELS

NEW = schema.CALL_RECORD_NEW
#: „Zły numer / brak danych” blokuje sam numer: ta osoba może wrócić z nowym numerem.
BAD_CONTACT = "bad_contact"
#: Lejek kolejki dzwonienia: szansa z innego lejka (np. botów) nie zdejmuje rekordu.
QUEUE_PIPELINE_KEY = schema.DEFAULT_PIPELINE_KEY
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

    queue_pipeline = select(SalesPipeline.id).where(
        SalesPipeline.key == QUEUE_PIPELINE_KEY
    )
    return [
        opportunity.company_id == record.company_id,
        opportunity.status == "open",
        opportunity.archived_at.is_(None),
        opportunity.pipeline_id.in_(queue_pipeline.scalar_subquery()),
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

    # Zbiory liczone raz na zapytanie (hashed subplan): zależny EXISTS w OR liczył się
    # osobno dla każdego „Nowego” rekordu, ok. 13 s na kolejkę przy 700 rekordach.
    later = aliased(SalesOpportunity)
    other = aliased(SalesCallRecord)
    called = other.state != NEW
    person_called = and_(called, other.state != BAD_CONTACT)
    own_phone = phone_key(record.phone)
    called_phones = select(phone_key(other.phone)).where(called)
    called_emails = select(email_key(other.email)).where(
        person_called, other.email.is_not(None)
    )
    called_contacts = select(other.contact_id).where(
        person_called, other.contact_id.is_not(None)
    )
    not_repeat = and_(
        or_(
            func.length(own_phone) < MIN_PHONE_DIGITS,
            own_phone.not_in(called_phones),
        ),
        or_(
            record.email.is_(None),
            email_key(record.email).not_in(called_emails),
        ),
        or_(
            record.contact_id.is_(None),
            record.contact_id.not_in(called_contacts),
        ),
    )
    return [
        ~exists().where(*_crm_after(record, later)),
        or_(record.state != NEW, not_repeat),
    ]


def not_a_repeat(record: Any = SalesCallRecord) -> Any:
    """Rekord, który nie jest powtórką: warunek kolejki użyty też w Tabeli (23.11.2026).

    Tabela pokazywała 542 „Nowe” powtórki sprzed bramki z 17.11 i osoby dzwoniące brały
    je za duplikaty. Decyzja Artura z 23.11.2026: ukryć je po stronie serwera, bez
    kasowania, z przełącznikiem „Powtórki” (``dzwonienie-duplikaty-instrukcja.md``).
    """

    return queue_conditions(record)[1]


#: „To duplikat” na karcie rozmowy (23.11.2026): zgłoszenie duplikatu, którego bramki nie
#: złapały. Notatka na osi firmy, jedna na osobę i rekord; listę daje raport powtórek
#: (``scripts.calling_repeats_report --reported``).
DUPLICATE_SOURCE = "call_duplicate"
DUPLICATE_SUBJECT = "Zgłoszony duplikat na liście dzwonienia"


async def report_duplicate(
    db: AsyncSession,
    record: SalesCallRecord,
    *,
    user_id: int,
    note: Optional[str],
    now: datetime,
) -> bool:
    """Zapisuje zgłoszenie; ``False``, gdy ta osoba już zgłosiła ten rekord."""

    statement = (
        pg_insert(SalesActivity)
        .values(
            kind="note",
            subject=DUPLICATE_SUBJECT,
            body=(note or "").strip() or None,
            company_id=record.company_id,
            contact_id=record.contact_id,
            created_by_user_id=user_id,
            occurred_at=now,
            external_source=DUPLICATE_SOURCE,
            external_id=f"{record.id}:{user_id}",
        )
        .on_conflict_do_nothing(
            index_elements=["external_source", "external_id", "company_id"],
            index_where=and_(
                SalesActivity.external_id.is_not(None),
                SalesActivity.external_ref.is_(None),
            ),
        )
        .returning(SalesActivity.id)
    )
    return (await db.execute(statement)).scalar_one_or_none() is not None
