"""Kartoteka firm sprzedaży: wyszukiwanie, duplikaty, liczby szans przy firmie.

Firma sprzedaży jest osobna od ``clients`` (D2, 26.10.2026). Duplikat
rozpoznajemy po NIP (cyfry) albo po nazwie kanonicznej ``normalize_company_name``
— ta sama, którą liczy dopasowanie osób z bazy, więc „mBank S.A.” i „mBank”
to jedna firma. Duplikat nie jest blokadą: handlowiec widzi istniejącą firmę
i może założyć drugą świadomie (dwie spółki o tej samej nazwie istnieją).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompany, SalesOpportunity
from app.services.company_names import normalize_company_name
from app.services.polish_ilike import polish_folded_ilike


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
