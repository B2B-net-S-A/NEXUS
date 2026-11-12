"""Kartoteka firm sprzedaży: wyszukiwanie, duplikaty, liczby szans przy firmie.

Firma sprzedaży jest osobna od ``clients`` (D2, 26.10.2026). Duplikat
rozpoznajemy po NIP (cyfry) albo po nazwie kanonicznej ``normalize_company_name``
— ta sama, którą liczy dopasowanie osób z bazy, więc „mBank S.A.” i „mBank”
to jedna firma. Duplikat nie jest blokadą: handlowiec widzi istniejącą firmę
i może założyć drugą świadomie (dwie spółki o tej samej nazwie istnieją).

Tożsamość firmy przy zakładaniu (10.11.2026): ``identity`` podpowiada istniejące
karty po nazwie i domenie oraz domenę z adresu strony albo maila osoby. Bez
domeny nie działa dopasowanie poczty, kalendarza ani punktów z researchu, a z 93
firm dotkniętych przez dzwoniących miało ją 6. To podpowiedź, nie bramka.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Select, and_, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompany, SalesOpportunity
from app.services.company_names import normalize_company_name
from app.services.m365.matcher import PUBLIC_EMAIL_DOMAINS
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales.outlook_activities import COMPANY_DOMAIN_SQL

#: Ile kart podpowiadamy przy wpisywaniu nazwy.
IDENTITY_MATCHES = 6
_IDENTITY_MIN_CHARS = 2
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")


def nip_digits(nip: Optional[str]) -> Optional[str]:
    """NIP bez kresek, spacji i prefiksu ``PL``; ``None`` dla pustego."""

    if not nip:
        return None
    digits = re.sub(r"\D", "", nip)
    return digits or None


@dataclass(frozen=True)
class OpenPipeline:
    count: int
    value: Decimal


def open_pipeline_subquery():
    """Liczba i suma wartości otwartych, niezarchiwizowanych szans per firma."""

    return (
        select(
            SalesOpportunity.company_id.label("company_id"),
            func.count(SalesOpportunity.id).label("open_count"),
            func.coalesce(func.sum(SalesOpportunity.value), 0).label("open_value"),
        )
        .where(
            SalesOpportunity.status == "open",
            SalesOpportunity.archived_at.is_(None),
        )
        .group_by(SalesOpportunity.company_id)
        .subquery()
    )


def apply_search(query: Select, q: Optional[str]) -> Select:
    """Szukaj po nazwie (bez polskich znaków i wielkości liter), NIP-ie i domenie."""

    text = (q or "").strip()
    if not text:
        return query
    conditions = [
        polish_folded_ilike(SalesCompany.name, text),
        polish_folded_ilike(func.coalesce(SalesCompany.legal_name, ""), text),
        func.coalesce(SalesCompany.domain, "").ilike(f"%{text.lower()}%"),
    ]
    digits = nip_digits(text)
    if digits and len(digits) >= 4:
        conditions.append(SalesCompany.nip.like(f"%{digits}%"))
    return query.where(or_(*conditions))


async def find_duplicates(
    db: AsyncSession,
    *,
    name: str,
    nip: Optional[str],
    exclude_id: Optional[int] = None,
) -> list[SalesCompany]:
    """Niezarchiwizowane firmy o tym samym NIP-ie albo tej samej nazwie kanonicznej."""

    canonical = normalize_company_name(name)
    digits = nip_digits(nip)
    matches = []
    if canonical:
        matches.append(SalesCompany.normalized_name == canonical)
    if digits:
        matches.append(SalesCompany.nip == digits)
    if not matches:
        return []
    query = select(SalesCompany).where(
        and_(SalesCompany.archived_at.is_(None), or_(*matches))
    )
    if exclude_id is not None:
        query = query.where(SalesCompany.id != exclude_id)
    return list((await db.execute(query.order_by(SalesCompany.id).limit(5))).scalars())


def apply_fields(company: SalesCompany, fields: dict[str, Any]) -> None:
    """Zapis pól karty firmy: ekran Firmy i przyjęcie propozycji bota (G-A)."""

    for key, value in fields.items():
        if key == "nip":
            value = nip_digits(value)
        elif key == "tags":
            value = value or []
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(company, key, value)
    if fields.get("owner_user_id") is not None:
        # Opiekun z konta zastępuje etykietę opiekuna z Atlasa.
        company.owner_label = None
    if "name" in fields:
        company.normalized_name = normalize_company_name(company.name) or company.name
    if "domain" not in fields and not company.domain and fields.get("website_url"):
        # Bez domeny nie działa dopasowanie poczty i kalendarza (10.11.2026).
        # Domena wysłana jawnie, także pusta, jest decyzją człowieka.
        company.domain = mail_domain(company.website_url)


async def open_pipeline(db: AsyncSession, company_id: int) -> OpenPipeline:
    row = (
        await db.execute(
            select(
                func.count(SalesOpportunity.id),
                func.coalesce(func.sum(SalesOpportunity.value), 0),
            ).where(
                SalesOpportunity.company_id == company_id,
                SalesOpportunity.status == "open",
                SalesOpportunity.archived_at.is_(None),
            )
        )
    ).one()
    return OpenPipeline(count=int(row[0]), value=Decimal(row[1]))


def http_url(value: Optional[str]) -> Optional[str]:
    """Adres strony albo profilu: tylko ``http(s)://`` (bez ``javascript:``, ``data:``).

    Gołą domenę („firma.pl”) uzupełniamy o ``https://`` — tak wpisują handlowcy.
    """

    text = (value or "").strip()
    if not text:
        return None
    scheme = _SCHEME.match(text)
    if scheme is None:
        text = f"https://{text}"
    elif scheme.group(1).lower() not in (
        "http",
        "https",
    ) or not text.lower().startswith(("http://", "https://")):
        # „javascript:…”, „data:…”, „ftp://…” — także bez „//”.
        raise ValueError("Adres musi zaczynać się od http:// albo https://.")
    if any(char.isspace() for char in text):
        raise ValueError("Adres nie może zawierać spacji.")
    return text


_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def mail_domain(value: Optional[str]) -> Optional[str]:
    """Domena firmy z adresu strony, adresu e-mail albo samej domeny.

    Darmowa skrzynka (gmail.com) nie wskazuje firmy, więc daje ``None``, tak samo
    jak tekst, który domeną nie jest.
    """

    text = (value or "").strip().lower()
    if not text or any(char.isspace() for char in text):
        return None
    text = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", text)
    text = re.split(r"[/?#]", text, maxsplit=1)[0]
    text = text.rsplit("@", 1)[-1].split(":", 1)[0].strip(".")
    if text.startswith("www."):
        text = text[4:]
    if not _DOMAIN.fullmatch(text) or text in PUBLIC_EMAIL_DOMAINS:
        return None
    return text[:255]


@dataclass(frozen=True)
class IdentityMatch:
    company: SalesCompany
    #: ``name`` ta sama nazwa kanoniczna, ``domain`` ta sama domena, ``similar`` podobna nazwa.
    reason: str
    open_opportunities: int


@dataclass(frozen=True)
class CompanyIdentity:
    domain: Optional[str]
    #: Skąd podpowiedź domeny: ``website`` albo ``email``.
    domain_source: Optional[str]
    matches: list[IdentityMatch]


async def identity(
    db: AsyncSession,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    website: Optional[str] = None,
    exclude_id: Optional[int] = None,
) -> CompanyIdentity:
    """Podpowiedź przy zakładaniu karty: domena i karty, które już mogą nią być."""

    from_website = mail_domain(website)
    domain = from_website or mail_domain(email)
    source = ("website" if from_website else "email") if domain else None
    text = (name or "").strip()
    canonical = normalize_company_name(text) if len(text) >= _IDENTITY_MIN_CHARS else ""

    reasons: list[tuple[str, Any]] = []
    if canonical:
        reasons.append(("name", SalesCompany.normalized_name == canonical))
    if domain:
        reasons.append(
            (
                "domain",
                and_(
                    SalesCompany.domain.is_not(None),
                    literal_column(COMPANY_DOMAIN_SQL) == domain,
                ),
            )
        )
    if canonical:
        reasons.append(
            (
                "similar",
                or_(
                    polish_folded_ilike(SalesCompany.name, text),
                    SalesCompany.normalized_name.like(f"{canonical}%"),
                ),
            )
        )

    pipeline = open_pipeline_subquery()
    matches: list[IdentityMatch] = []
    seen: set[int] = set()
    for reason, condition in reasons:
        if len(matches) >= IDENTITY_MATCHES:
            break
        query = (
            select(SalesCompany, func.coalesce(pipeline.c.open_count, 0))
            .outerjoin(pipeline, pipeline.c.company_id == SalesCompany.id)
            .where(SalesCompany.archived_at.is_(None), condition)
            .order_by(
                func.coalesce(pipeline.c.open_count, 0).desc(),
                SalesCompany.name,
                SalesCompany.id,
            )
            .limit(IDENTITY_MATCHES)
        )
        if exclude_id is not None:
            query = query.where(SalesCompany.id != exclude_id)
        for company, open_count in (await db.execute(query)).all():
            if company.id in seen or len(matches) >= IDENTITY_MATCHES:
                continue
            seen.add(company.id)
            matches.append(IdentityMatch(company, reason, int(open_count)))
    return CompanyIdentity(domain=domain, domain_source=source, matches=matches)
