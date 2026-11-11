"""Import listy do kampanii dzwonienia: los każdego wiersza przed zapisem.

Ekran najpierw pokazuje, co stanie się z każdym wierszem, a zapis liczy to samo
jeszcze raz pod blokadą importu, więc drugi klik „Dodaj” niczego nie dubluje.
To nie jest silnik leadów: listę przygotowuje człowiek i podaje, skąd ma kontakty.

Bramki, od najważniejszej (pierwsza pasująca decyduje):

1. ``do_not_contact``: firma albo osoba ma zapisany sprzeciw (także ten sam numer
   albo adres przy innej firmie);
2. ``client``: klient NEXUSA (reguła ``client_gate``, jak przy leadach i szansach)
   albo nasza spółka. Popyt u klienta idzie do jego Delivery Leada;
3. ``already_in_campaign``: ta firma z tą osobą albo numerem jest już w kampanii,
   wiersz powtarza się w pliku albo dzwoniący ma już otwartą szansę tej firmy;
4. ``other_caller``: firmę ma w kolejce albo w otwartej szansie ktoś inny;
5. ``no_phone``: wiersz bez numeru nie ma po co wchodzić do kolejki dzwonienia;
6. ``linked`` (karta firmy istnieje) albo ``new_company`` (import ją założy).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesCompanyAlias,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.company_names import normalize_company_name
from app.services.sales import client_gate
from app.services.sales.calling import OPEN_STATES
from app.services.sales.calling_file import (
    ListFile,
    ListRow,
    person_key,
    phone_digits,
    row_domain,
    valid_email,
)
from app.services.sales.calls import DO_NOT_CONTACT
from app.services.sales.companies import http_url, nip_digits
from app.services.sales.outlook_activities import COMPANY_DOMAIN_SQL

logger = logging.getLogger(__name__)

NEW_COMPANY = "new_company"
LINKED = "linked"
ALREADY = "already_in_campaign"
OTHER_CALLER = "other_caller"
CLIENT = "client"
NO_PHONE = "no_phone"
FATES: tuple[str, ...] = (
    NEW_COMPANY,
    LINKED,
    ALREADY,
    OTHER_CALLER,
    CLIENT,
    DO_NOT_CONTACT,
    NO_PHONE,
)
#: Wiersze, które „Dodaj N do kolejki” zapisze.
ADDABLE: frozenset[str] = frozenset({NEW_COMPANY, LINKED})
#: Wiersze, których import nie doda i na które ktoś powinien spojrzeć.
TO_DECIDE: frozenset[str] = frozenset({OTHER_CALLER, CLIENT, DO_NOT_CONTACT, NO_PHONE})
CONTACT_SOURCE = "call_campaign"
LOCK_KEY = "sales_calling_import"
NIP_LENGTH = 10

OBJECTION_DETAIL = "Osoba albo firma ma zapisany sprzeciw wobec kontaktu."
REPEATED_DETAIL = "Powtórzony wiersz w pliku."
IN_CAMPAIGN_DETAIL = "Ten rekord jest już w tej kampanii."
NO_PHONE_DETAIL = "Brak numeru telefonu w wierszu."


@dataclass(frozen=True)
class RecordOverride:
    """Stan rekordu przeniesiony z Excela dzwoniących zamiast „nowy” (11.11.2026)."""

    state: str
    callback_on: Optional[date] = None
    attempts: int = 0


@dataclass(frozen=True)
class RowPlan:
    row: ListRow
    fate: str
    detail: str
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    domain: Optional[str] = None


@dataclass(frozen=True)
class ImportPlan:
    rows: list[RowPlan]
    without_company: int

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(FATES, 0)
        for plan in self.rows:
            counts[plan.fate] += 1
        return counts

    @property
    def addable(self) -> int:
        return sum(1 for plan in self.rows if plan.fate in ADDABLE)


@dataclass
class _Known:
    """To, co NEXUS wie o firmach z pliku; wczytane kilkoma zapytaniami na cały plik."""

    by_domain: dict[str, list[SalesCompany]] = field(default_factory=dict)
    by_nip: dict[str, list[SalesCompany]] = field(default_factory=dict)
    by_name: dict[str, list[SalesCompany]] = field(default_factory=dict)
    clients: dict[int, client_gate.ClientMatch] = field(default_factory=dict)
    client_names: dict[str, client_gate.ClientMatch] = field(default_factory=dict)
    contacts: dict[int, list[SalesContact]] = field(default_factory=dict)
    records: dict[int, list[SalesCallRecord]] = field(default_factory=dict)
    opportunities: dict[int, list[tuple[Optional[int], str]]] = field(
        default_factory=dict
    )
    users: dict[int, str] = field(default_factory=dict)
    objected_phones: set[str] = field(default_factory=set)
    objected_emails: set[str] = field(default_factory=set)


def _row_nip(row: ListRow) -> Optional[str]:
    digits = nip_digits(row.nip)
    return digits if digits and len(digits) == NIP_LENGTH else None


async def _companies(db: AsyncSession, rows: list[ListRow], known: _Known) -> None:
    names = {name for row in rows if (name := normalize_company_name(row.company))}
    domains = {domain for row in rows if (domain := row_domain(row))}
    nips = {nip for row in rows if (nip := _row_nip(row))}
    domain_sql = literal_column(COMPANY_DOMAIN_SQL)
    alias_ids = select(SalesCompanyAlias.company_id).where(
        SalesCompanyAlias.status == "joined",
        SalesCompanyAlias.normalized_alias.in_(names),
    )
    conditions = [
        SalesCompany.normalized_name.in_(names),
        SalesCompany.id.in_(alias_ids),
    ]
    if domains:
        conditions.append(domain_sql.in_(domains))
    if nips:
        conditions.append(SalesCompany.nip.in_(nips))
    found = (
        await db.execute(
            select(SalesCompany, domain_sql.label("mail_domain"))
            .where(SalesCompany.archived_at.is_(None), or_(*conditions))
            .order_by(SalesCompany.id)
        )
    ).all()
    aliases = (
        await db.execute(
            select(
                SalesCompanyAlias.company_id, SalesCompanyAlias.normalized_alias
            ).where(
                SalesCompanyAlias.status == "joined",
                SalesCompanyAlias.normalized_alias.in_(names),
            )
        )
    ).all()
    alias_names: dict[int, list[str]] = {}
    for company_id, alias in aliases:
        alias_names.setdefault(company_id, []).append(alias)
    for company, mail_domain in found:
        if mail_domain:
            known.by_domain.setdefault(mail_domain, []).append(company)
        if company.nip:
            known.by_nip.setdefault(company.nip, []).append(company)
        for name in (company.normalized_name, *alias_names.get(company.id, ())):
            known.by_name.setdefault(name, []).append(company)


def _cards(known: _Known) -> dict[int, SalesCompany]:
    return {
        company.id: company
        for group in (known.by_domain, known.by_nip, known.by_name)
        for companies in group.values()
        for company in companies
    }


async def _clients(db: AsyncSession, rows: list[ListRow], known: _Known) -> None:
    """Klienci NEXUSA wśród kart i wśród samych nazw z pliku (firma bez karty)."""

    names = sorted(
        {name for row in rows if (name := normalize_company_name(row.company))}
    )
    matches = await client_gate.match_companies(
        db,
        [
            *(
                client_gate.CompanyIdentity(
                    company_id=company.id,
                    client_id=company.client_id,
                    normalized_name=company.normalized_name,
                )
                for company in _cards(known).values()
            ),
            # Nazwa bez karty dostaje ujemny numer, żeby nie zderzyć się z id firmy.
            *(
                client_gate.CompanyIdentity(
                    company_id=-index, client_id=None, normalized_name=name
                )
                for index, name in enumerate(names, start=1)
            ),
        ],
    )
    for key, match in matches.items():
        if key > 0:
            known.clients[key] = match
        else:
            known.client_names[names[-key - 1]] = match


async def _company_state(db: AsyncSession, known: _Known) -> None:
    ids = sorted(_cards(known))
    if not ids:
        return
    linked = (
        select(SalesContact, SalesCompanyContact.company_id)
        .join(SalesCompanyContact, SalesCompanyContact.contact_id == SalesContact.id)
        .where(
            SalesCompanyContact.company_id.in_(ids),
            SalesContact.archived_at.is_(None),
        )
    )
    primary = select(SalesContact, SalesContact.company_id).where(
        SalesContact.company_id.in_(ids), SalesContact.archived_at.is_(None)
    )
    for query in (linked, primary):
        for contact, company_id in (await db.execute(query)).all():
            bucket = known.contacts.setdefault(company_id, [])
            if all(existing.id != contact.id for existing in bucket):
                bucket.append(contact)
    records = select(SalesCallRecord).where(SalesCallRecord.company_id.in_(ids))
    for record in (await db.execute(records)).scalars():
        known.records.setdefault(record.company_id, []).append(record)
    open_opportunities = (
        select(
            SalesOpportunity.company_id,
            SalesOpportunity.owner_user_id,
            SalesPipelineStage.name,
        )
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .where(
            SalesOpportunity.company_id.in_(ids),
            SalesOpportunity.status == "open",
            SalesOpportunity.archived_at.is_(None),
        )
        .order_by(SalesOpportunity.id)
    )
    for company_id, owner_id, stage in (await db.execute(open_opportunities)).all():
        known.opportunities.setdefault(company_id, []).append((owner_id, stage))


async def _objections(db: AsyncSession, known: _Known) -> None:
    """Sprzeciwy z całej kartoteki: ta sama osoba bywa na liście pod inną firmą."""

    contacts = select(
        SalesContact.email, SalesContact.phone, SalesContact.mobile_phone
    ).where(SalesContact.do_not_contact_at.is_not(None))
    for email, phone, mobile in (await db.execute(contacts)).all():
        if valid_email(email):
            known.objected_emails.add(valid_email(email))
        known.objected_phones.update(
            digits for value in (phone, mobile) if (digits := phone_digits(value))
        )
    records = select(SalesCallRecord.email, SalesCallRecord.phone).where(
        SalesCallRecord.state == DO_NOT_CONTACT
    )
    for email, phone in (await db.execute(records)).all():
        if valid_email(email):
            known.objected_emails.add(valid_email(email))
        if digits := phone_digits(phone):
            known.objected_phones.add(digits)


async def _user_names(db: AsyncSession, known: _Known) -> None:
    ids = {
        owner_id
        for items in known.opportunities.values()
        for owner_id, _stage in items
        if owner_id is not None
    } | {
        record.assigned_user_id
        for items in known.records.values()
        for record in items
        if record.assigned_user_id is not None
    }
    if not ids:
        return
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(sorted(ids))))
    known.users = {user_id: name for user_id, name in rows.all()}


def _pick_company(
    row: ListRow, known: _Known
) -> tuple[Optional[SalesCompany], str, Optional[str]]:
    """Karta firmy dla wiersza: domena, potem NIP, potem nazwa (najstarsza karta)."""

    domain = row_domain(row)
    for how, bucket in (
        ("po domenie", known.by_domain.get(domain or "")),
        ("po NIP-ie", known.by_nip.get(_row_nip(row) or "")),
        ("po nazwie", known.by_name.get(normalize_company_name(row.company))),
    ):
        if bucket:
            extra = ", kilka kart, wybrano najstarszą" if len(bucket) > 1 else ""
            return bucket[0], f"{how}{extra}", domain
    return None, "", domain


def _match_contact(
    row: ListRow, contacts: list[SalesContact]
) -> Optional[SalesContact]:
    email = valid_email(row.email)
    digits = phone_digits(row.phone)
    name = person_key(row.person)
    for contact in contacts:
        if email and valid_email(contact.email) == email:
            return contact
    for contact in contacts:
        if digits and digits in (
            phone_digits(contact.phone),
            phone_digits(contact.mobile_phone),
        ):
            return contact
    for contact in contacts:
        if name and person_key(contact.full_name) == name:
            return contact
    return None


def _same_entry(row: ListRow, record: SalesCallRecord) -> bool:
    """Ten sam wpis co rekord: ta sama osoba, a bez nazwisk ten sam numer."""

    name = person_key(row.person)
    other = person_key(record.person_name)
    if name and other:
        return name == other
    digits = phone_digits(row.phone)
    return digits is not None and digits == phone_digits(record.phone)


def _client_detail(match: client_gate.ClientMatch) -> str:
    lead = match.delivery_lead or client_gate.NO_LEAD_LABEL
    return f"{match.client_name} to klient NEXUSA. Sprawa dla Delivery Leada: {lead}."


def _name(known: _Known, user_id: Optional[int]) -> str:
    if user_id is None:
        return "nikt (szansa bez opiekuna)"
    return known.users.get(user_id, "inna osoba")


def _plan_row(
    row: ListRow,
    known: _Known,
    *,
    campaign_id: int,
    assignee_id: int,
    seen: set[tuple[Any, ...]],
) -> RowPlan:
    company, how, domain = _pick_company(row, known)
    company_id = company.id if company else None
    contacts = known.contacts.get(company_id or 0, [])
    contact = _match_contact(row, contacts)
    digits = phone_digits(row.phone)
    email = valid_email(row.email)

    def plan(fate: str, detail: str) -> RowPlan:
        return RowPlan(
            row=row,
            fate=fate,
            detail=detail,
            company_id=company_id,
            contact_id=contact.id if contact else None,
            domain=domain,
        )

    records = known.records.get(company_id or 0, [])
    objected = (
        (company is not None and company.status == schema.CompanyStatus.do_not_contact)
        or (contact is not None and contact.do_not_contact_at is not None)
        or (digits is not None and digits in known.objected_phones)
        or (email is not None and email in known.objected_emails)
        or any(
            record.state == DO_NOT_CONTACT and _same_entry(row, record)
            for record in records
        )
    )
    if objected:
        return plan(DO_NOT_CONTACT, OBJECTION_DETAIL)

    canonical = normalize_company_name(row.company)
    if canonical == client_gate.OWN_COMPANY_KEY or (
        company is not None and company.normalized_name == client_gate.OWN_COMPANY_KEY
    ):
        return plan(CLIENT, "To nasza firma, do kolejki nie trafia.")
    client = known.clients.get(company_id or 0) or known.client_names.get(canonical)
    if client is not None:
        return plan(CLIENT, _client_detail(client))

    key = (company_id or canonical, person_key(row.person) or digits or "")
    if key in seen:
        return plan(ALREADY, REPEATED_DETAIL)
    seen.add(key)
    if any(
        record.campaign_id == campaign_id and _same_entry(row, record)
        for record in records
    ):
        return plan(ALREADY, IN_CAMPAIGN_DETAIL)
    opportunities = known.opportunities.get(company_id or 0, [])
    own = next((stage for owner, stage in opportunities if owner == assignee_id), None)
    if own is not None:
        return plan(ALREADY, f"Otwarta szansa tej firmy na etapie „{own}”.")

    busy = next(
        (
            record
            for record in records
            # Rekord bez kampanii żyje razem ze swoją szansą: otwartą łapie bramka
            # niżej, a zamkniętej nikt już nie obdzwania.
            if record.campaign_id is not None
            and record.state in OPEN_STATES
            and record.assigned_user_id not in (None, assignee_id)
        ),
        None,
    )
    if busy is not None:
        return plan(
            OTHER_CALLER, f"W kolejce ma ją {_name(known, busy.assigned_user_id)}."
        )
    other = next(
        ((owner, stage) for owner, stage in opportunities if owner != assignee_id),
        None,
    )
    if other is not None:
        return plan(
            OTHER_CALLER,
            f"Otwarta szansa na etapie „{other[1]}”, prowadzi {_name(known, other[0])}.",
        )

    if digits is None:
        return plan(NO_PHONE, NO_PHONE_DETAIL)
    person = (
        "osoba jest już w kontaktach"
        if contact
        else "dojdzie nowa osoba"
        if row.person
        else "bez osoby"
    )
    if company is not None:
        return plan(LINKED, f"Karta firmy istnieje ({how}), {person}.")
    with_domain = f" z domeną {domain}" if domain else ""
    return plan(NEW_COMPANY, f"Założy kartę firmy{with_domain}, {person}.")


async def plan_import(
    db: AsyncSession,
    campaign: SalesCallCampaign,
    listing: ListFile,
    *,
    assignee_id: int,
) -> ImportPlan:
    """Los każdego wiersza; niczego nie zapisuje."""

    known = _Known()
    await _companies(db, listing.rows, known)
    await _clients(db, listing.rows, known)
    await _company_state(db, known)
    await _objections(db, known)
    await _user_names(db, known)
    seen: set[tuple[Any, ...]] = set()
    return ImportPlan(
        rows=[
            _plan_row(
                row,
                known,
                campaign_id=campaign.id,
                assignee_id=assignee_id,
                seen=seen,
            )
            for row in listing.rows
        ],
        without_company=listing.without_company,
    )


def _website(value: Optional[str]) -> Optional[str]:
    try:
        return http_url(value)
    except ValueError:
        return None


async def _new_company(
    db: AsyncSession, plan: RowPlan, *, user_id: int
) -> SalesCompany:
    row = plan.row
    company = SalesCompany(
        name=row.company,
        normalized_name=normalize_company_name(row.company) or row.company,
        domain=plan.domain,
        website_url=_website(row.website),
        nip=_row_nip(row),
        industry=row.industry,
        source=CONTACT_SOURCE,
        created_by_user_id=user_id,
    )
    db.add(company)
    await db.flush()
    return company


async def _new_contact(
    db: AsyncSession, plan: RowPlan, company_id: int, *, user_id: int
) -> SalesContact:
    row = plan.row
    contact = SalesContact(
        company_id=company_id,
        full_name=row.person,
        title=row.title,
        email=valid_email(row.email),
        phone=row.phone,
        linkedin_url=row.linkedin,
        source=CONTACT_SOURCE,
        created_by_user_id=user_id,
    )
    db.add(contact)
    await db.flush()
    await db.execute(
        insert(SalesCompanyContact)
        .values(
            company_id=company_id,
            contact_id=contact.id,
            title=row.title,
            is_primary=True,
        )
        .on_conflict_do_nothing()
    )
    return contact


async def apply_import(
    db: AsyncSession,
    campaign_id: int,
    listing: ListFile,
    *,
    contact_source: str,
    assignee_id: int,
    user_id: int,
    overrides: Optional[Mapping[int, RecordOverride]] = None,
) -> tuple[ImportPlan, int]:
    """Zapisuje wiersze ``ADDABLE``; bez commita. Zwraca plan i liczbę dodanych."""

    # Jedna blokada na wszystkie importy list: drugi import tej samej listy, także do
    # innej kampanii, zobaczy rekordy i karty firm pierwszego zamiast je zdublować.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LOCK_KEY}
    )
    campaign = (
        await db.execute(
            select(SalesCallCampaign).where(SalesCallCampaign.id == campaign_id)
        )
    ).scalar_one()
    plan = await plan_import(db, campaign, listing, assignee_id=assignee_id)
    created: dict[str, SalesCompany] = {}
    added = 0
    for row_plan in plan.rows:
        if row_plan.fate not in ADDABLE:
            continue
        row = row_plan.row
        if row_plan.company_id is not None:
            company = await db.get(SalesCompany, row_plan.company_id)
            if not company.domain and row_plan.domain:
                # Domena z adresu osoby: bez niej nie działa dopasowanie poczty
                # i punkty z researchu. Uzupełniamy pustą, nigdy nie nadpisujemy.
                company.domain = row_plan.domain
        else:
            canonical = normalize_company_name(row.company) or row.company
            company = created.get(canonical)
            if company is None:
                company = await _new_company(db, row_plan, user_id=user_id)
                created[canonical] = company
        contact_id = row_plan.contact_id
        if contact_id is not None and row.linkedin:
            known = await db.get(SalesContact, contact_id)
            # Pusty profil uzupełniamy, istniejącego nie nadpisujemy (jak domeny).
            if known is not None and not known.linkedin_url:
                known.linkedin_url = row.linkedin
        if contact_id is None and row.person:
            contact_id = (
                await _new_contact(db, row_plan, company.id, user_id=user_id)
            ).id
        override = (overrides or {}).get(row.line)
        db.add(
            SalesCallRecord(
                campaign_id=campaign.id,
                company_id=company.id,
                contact_id=contact_id,
                person_name=row.person,
                person_title=row.title,
                phone=row.phone,
                email=valid_email(row.email),
                contact_source=contact_source,
                note=row.note,
                state=override.state if override else schema.CALL_RECORD_NEW,
                callback_on=override.callback_on if override else None,
                attempts=override.attempts if override else 0,
                assigned_user_id=assignee_id,
                created_by_user_id=user_id,
            )
        )
        added += 1
    await db.flush()
    # Logi są publiczne: same liczby, bez nazw firm i osób.
    logger.info(
        "sales_calling import campaign=%s rows=%d added=%d new_companies=%d",
        campaign.id,
        len(plan.rows),
        added,
        len(created),
    )
    return plan, added


async def campaign_or_none(
    db: AsyncSession, campaign_id: int
) -> Optional[SalesCallCampaign]:
    campaign = await db.get(SalesCallCampaign, campaign_id)
    if campaign is None or campaign.archived_at is not None:
        return None
    return campaign
