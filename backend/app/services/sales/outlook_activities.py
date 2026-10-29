"""Sprzedaż ← Outlook: maile i spotkania handlowców przy firmach.

Decyzja Artura z 28.10.2026 („tak, jak w Atlasie”): poczta i kalendarz
właściciela skrzynki z „Sprzedaż: podgląd” trafiają na oś firmy jako
aktywności ``email`` / ``meeting`` i widzi je każdy z podglądem Sprzedaży.
Na karcie szansy pokazuje je ``with_company_mail`` (``api/sales_activities``).

Dopasowanie (Atlas: ``ms_graph_matching.resolve_contacts``) — po adresach
spoza firmy (``matcher.external_addresses``):

1. adres kontaktu sprzedaży (``sales_contacts.email``) → jego firma główna
   i firmy z ``sales_company_contacts`` (bieżące);
2. adres bez kontaktu → domena firmy (``sales_companies.domain``, zapisana
   bywa jako adres strony). Atlas tego nie robił; tu jest na życzenie Artura,
   ale bez darmowych skrzynek (``PUBLIC_EMAIL_DOMAINS``), a domena wspólna dla
   więcej niż ``MAX_DOMAIN_COMPANIES`` firm jest za mało pewna.

Jedna aktywność na firmę (Atlas INT-03). Klucz deduplikacji jak w Atlasie:
``internetMessageId`` maila, ``iCalUId`` spotkania — ten sam mail w dwóch
skrzynkach handlowców i historia z importu Atlasa to jedna aktywność.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, delete, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
)
from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS, external_addresses

logger = logging.getLogger(__name__)

EMAIL_SOURCE = "msgraph-mail"
EVENT_SOURCE = "msgraph-event"
#: Domena wspólna dla większej liczby firm (grupa, duplikaty) nie wskazuje firmy.
MAX_DOMAIN_COMPANIES = 3
_BODY_LIMIT = 2000

#: Domena z pola, które bywa adresem strony („https://www.firma.pl/”). To samo
#: wyrażenie stoi w indeksie ``ix_sales_companies_mail_domain`` — dlatego tekst,
#: nie parametry (indeks wyrażenia pasuje tylko do identycznego wyrażenia).
COMPANY_DOMAIN_SQL = (
    "regexp_replace(lower(btrim(domain)), '^([a-z]+://)?(www\\.)?([^/:?#]+).*$', '\\3')"
)


@dataclass(frozen=True)
class OutlookItem:
    """Mail albo spotkanie z Outlooka gotowe do zapisu przy firmie."""

    source: str
    external_id: str
    owner_user_id: int
    owner_address: Optional[str]
    addresses: Sequence[str]
    subject: Optional[str]
    preview: Optional[str]
    occurred_at: Optional[datetime]
    web_link: Optional[str] = None
    direction: Optional[str] = None
    duration_minutes: Optional[int] = None

    @property
    def kind(self) -> str:
        return "meeting" if self.source == EVENT_SOURCE else "email"


def _domain(address: str) -> Optional[str]:
    return address.rsplit("@", 1)[1] if "@" in address else None


def _domain_candidates(domain: str) -> list[str]:
    """``eu.mail.firma.pl`` → ta domena i nadrzędne, najdokładniejsza pierwsza."""

    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


async def _companies_by_contact(
    db: AsyncSession, addresses: Sequence[str]
) -> tuple[dict[int, int], set[str]]:
    """Firma → kontakt dla adresów kontaktów sprzedaży; drugi wynik: trafione adresy."""

    if not addresses:
        return {}, set()
    email_sql = func.lower(func.btrim(SalesContact.email))
    rows = (
        await db.execute(
            select(SalesContact.id, SalesContact.company_id, email_sql)
            .where(
                SalesContact.email.is_not(None),
                email_sql.in_(list(addresses)),
                SalesContact.archived_at.is_(None),
            )
            .order_by(SalesContact.id)
        )
    ).all()
    if not rows:
        return {}, set()
    contact_ids = [row[0] for row in rows]
    links = (
        await db.execute(
            select(SalesCompanyContact.contact_id, SalesCompanyContact.company_id)
            .where(
                SalesCompanyContact.contact_id.in_(contact_ids),
                SalesCompanyContact.is_current.is_(True),
            )
            .order_by(SalesCompanyContact.company_id)
        )
    ).all()
    pairs = [(row[1], row[0]) for row in rows if row[1] is not None]
    pairs += [(company_id, contact_id) for contact_id, company_id in links]
    live = set(
        (
            await db.scalars(
                select(SalesCompany.id).where(
                    SalesCompany.id.in_({company_id for company_id, _ in pairs}),
                    SalesCompany.archived_at.is_(None),
                )
            )
        ).all()
    )
    companies: dict[int, int] = {}
    for company_id, contact_id in pairs:
        if company_id in live:
            companies.setdefault(company_id, contact_id)
    return companies, {row[2] for row in rows}


async def _companies_by_domain(db: AsyncSession, addresses: Iterable[str]) -> set[int]:
    wanted: dict[str, list[str]] = {}
    for address in addresses:
        domain = _domain(address)
        if domain and domain not in PUBLIC_EMAIL_DOMAINS:
            wanted[address] = [
                d for d in _domain_candidates(domain) if d not in PUBLIC_EMAIL_DOMAINS
            ]
    all_domains = {d for candidates in wanted.values() for d in candidates}
    if not all_domains:
        return set()
    domain_sql = literal_column(COMPANY_DOMAIN_SQL)
    rows = (
        await db.execute(
            select(SalesCompany.id, domain_sql)
            .where(
                SalesCompany.domain.is_not(None),
                domain_sql.in_(sorted(all_domains)),
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesCompany.id)
        )
    ).all()
    by_domain: dict[str, list[int]] = {}
    for company_id, domain in rows:
        by_domain.setdefault(domain, []).append(company_id)
    companies: set[int] = set()
    for candidates in wanted.values():
        for domain in candidates:
            hits = by_domain.get(domain)
            if not hits:
                continue
            # Najdokładniejsza domena rozstrzyga; za wiele firm = brak pewności.
            if len(hits) <= MAX_DOMAIN_COMPANIES:
                companies.update(hits)
            break
    return companies


async def match_companies(
    db: AsyncSession, addresses: Sequence[str], owner_address: Optional[str]
) -> dict[int, Optional[int]]:
    """Firma sprzedaży → kontakt (``None`` przy dopasowaniu po domenie)."""

    external = external_addresses(list(addresses), owner_address)
    by_contact, matched = await _companies_by_contact(db, external)
    companies: dict[int, Optional[int]] = dict(by_contact)
    for company_id in await _companies_by_domain(
        db, [a for a in external if a not in matched]
    ):
        companies.setdefault(company_id, None)
    return companies


def _done_at(item: OutlookItem, now: datetime) -> Optional[datetime]:
    """Mail to historia; spotkanie jest „zrobione”, gdy już się zaczęło."""

    if item.kind == "email":
        return item.occurred_at
    if item.occurred_at is not None and item.occurred_at <= now:
        return item.occurred_at
    return None


async def record(db: AsyncSession, item: OutlookItem) -> int:
    """Zapisz albo odśwież aktywność przy każdej dopasowanej firmie. Zwraca ich liczbę."""

    companies = await match_companies(db, item.addresses, item.owner_address)
    if not companies:
        return 0
    now = datetime.now(timezone.utc)
    subject = (item.subject or "").strip()[:500] or None
    body = (item.preview or "").strip()[:_BODY_LIMIT] or None
    done_at = _done_at(item, now)
    existing = {
        row.company_id: row
        for row in (
            await db.scalars(
                select(SalesActivity)
                .where(
                    SalesActivity.external_source == item.source,
                    SalesActivity.external_id == item.external_id,
                    SalesActivity.company_id.in_(list(companies)),
                )
                .order_by(SalesActivity.id.desc())
            )
        ).all()
    }
    for company_id, contact_id in companies.items():
        row = existing.get(company_id)
        if row is None:
            await db.execute(
                pg_insert(SalesActivity)
                .values(
                    company_id=company_id,
                    contact_id=contact_id,
                    kind=item.kind,
                    subject=subject,
                    body=body,
                    occurred_at=item.occurred_at,
                    done_at=done_at,
                    created_by_user_id=item.owner_user_id,
                    external_source=item.source,
                    external_id=item.external_id,
                    web_link=item.web_link,
                    direction=item.direction,
                    duration_minutes=item.duration_minutes,
                )
                .on_conflict_do_nothing(
                    index_elements=["external_source", "external_id", "company_id"],
                    index_where=and_(
                        SalesActivity.external_id.is_not(None),
                        SalesActivity.external_ref.is_(None),
                    ),
                )
            )
            continue
        # Historia z importu Atlasa (``external_ref``) — tylko luki.
        row.web_link = row.web_link or item.web_link
        row.direction = row.direction or item.direction
        if row.external_ref is not None:
            if row.duration_minutes is None:
                row.duration_minutes = item.duration_minutes
            continue
        row.subject = subject
        row.body = body
        row.occurred_at = item.occurred_at
        row.done_at = done_at
        row.duration_minutes = item.duration_minutes
        if row.contact_id is None:
            row.contact_id = contact_id
    return len(companies)


async def forget(
    db: AsyncSession,
    source: str,
    external_id: str,
    *,
    upcoming_only: bool,
) -> int:
    """Usuń aktywności zsynchronizowane z Outlooka dla tej wiadomości / spotkania.

    ``upcoming_only`` — odwołane spotkanie znika z osi tylko, gdy jeszcze się
    nie odbyło (przeszłe zostaje historią). Bez tej flagi (wiadomość albo
    spotkanie oznaczone w Outlooku jako prywatne) znika też przeszłe, ale tylko
    to, co zapisała synchronizacja NEXUSA — historii z Atlasa nie ruszamy.
    """

    conditions = [
        SalesActivity.external_source == source,
        SalesActivity.external_id == external_id,
    ]
    if upcoming_only:
        conditions.append(
            or_(
                SalesActivity.occurred_at.is_(None),
                SalesActivity.occurred_at > datetime.now(timezone.utc),
            )
        )
    else:
        conditions.append(SalesActivity.external_ref.is_(None))
    result = await db.execute(delete(SalesActivity).where(*conditions))
    return int(result.rowcount or 0)
