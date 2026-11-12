"""Które firmy idą do bota researchu i z jakim rodzajem punktów do rozmowy.

* **Sygnały:** firmy z tagiem pilota (``SALES_SIGNALS_TAG``), raz w tygodniu.
* **Punkty, nowe:** firma z leadem albo szansą z ostatnich 7 dni, bez punktów.
* **Punkty, odświeżenie w poniedziałek:** otwarta szansa z krokiem albo spotkaniem
  w ciągu 14 dni, punkty starsze niż 6 dni.
* **Punkty przy ofertach „Do decyzji”** (decyzja Artura 12.11.2026): w tym samym
  poniedziałkowym odświeżeniu firmy pozycji z sekcji „Do decyzji” zakładki Oferty,
  z tymi samymi progami. Taka pozycja z definicji nie ma kroku, więc reguła wyżej
  jej nie łapie, a decydujący ma zobaczyć, co się w firmie zmieniło.

Rodzaj punktów: ``ongoing``, gdy z firmą była już rozmowa albo spotkanie albo gdy
firma ma ofertę „Do decyzji”, inaczej ``first_call``. Firma z biegu z ostatnich
24 godzin nie wraca od razu, żeby firma, o której bot nic nie napisał, nie szła
do niego co godzinę.

* **„Warto wrócić” (``winback``), raz w miesiącu:** firma z szansą przegraną
  w ostatnich 14 miesiącach z powodem „wróć później” (``WINBACK_LOST_REASONS``),
  karta poza archiwum, bez otwartej szansy i bez powiązania z klientem NEXUSA
  (``client_gate``), najwyżej ``MAX_WINBACK_FIRMS`` firm od najświeższej przegranej.
  Kopia z 10.11.2026: 31 takich przegranych w 29 firmach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.scheduling import business_date, local_day_start_utc
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyBriefing,
    SalesLead,
    SalesOpportunity,
    SalesSignalRun,
)
from app.services.sales import client_gate, offers
from app.services.sales.task_scope import live_opportunity
from app.services.sales.touch import not_cancelled

NEW_WITHIN = timedelta(days=7)
STEP_WITHIN = timedelta(days=14)
STALE_AFTER = timedelta(days=6)
RESEND_AFTER = timedelta(hours=24)
MAX_BRIEFING_FIRMS = 25
MAX_REFRESH_FIRMS = 100
MAX_PILOT_FIRMS = 100
MAX_WINBACK_FIRMS = 50
WINBACK_MONTHS = 14
#: Powody przegranej, po których warto wrócić (decyzja Artura 12.11.2026);
#: porównanie dokładne (bez spacji na brzegach), jak w ``lost_reason`` z Atlasa.
WINBACK_LOST_REASONS: tuple[str, ...] = (
    "Klient zrezygnował z projektu",
    "Projekt na bliżej nieokreśloną przyszłość",
    "Cena za wysoka",
    "Brak kontaktu z klientem",
)


async def pilot_company_ids(db: AsyncSession) -> list[int]:
    tag = settings.SALES_SIGNALS_TAG.strip()
    if not tag:
        return []
    rows = await db.execute(
        select(SalesCompany.id)
        .where(SalesCompany.tags.contains([tag]), SalesCompany.archived_at.is_(None))
        .order_by(SalesCompany.id)
        .limit(MAX_PILOT_FIRMS)
    )
    return list(rows.scalars())


async def recently_sent(db: AsyncSession, *, now: datetime) -> set[int]:
    runs = await db.execute(
        select(SalesSignalRun.company_ids).where(
            SalesSignalRun.kind == "briefing",
            SalesSignalRun.started_at >= now - RESEND_AFTER,
        )
    )
    return {int(cid) for ids in runs.scalars() for cid in ids}


async def new_company_ids(
    db: AsyncSession, *, now: datetime, exclude: Iterable[int] = ()
) -> list[int]:
    """Firmy wysłane w ostatnich 24 h odpadają w zapytaniu, przed limitem."""

    since = now - NEW_WITHIN
    skip = sorted(set(exclude))
    lead_companies = select(SalesLead.company_id.label("company_id")).where(
        SalesLead.company_id.is_not(None),
        SalesLead.created_at >= since,
        SalesLead.status.in_(("new", "contacted")),
    )
    opportunity_companies = select(
        SalesOpportunity.company_id.label("company_id")
    ).where(SalesOpportunity.created_at >= since, live_opportunity())
    union = lead_companies.union(opportunity_companies).subquery()
    rows = await db.execute(
        select(union.c.company_id)
        .join(SalesCompany, SalesCompany.id == union.c.company_id)
        .outerjoin(
            SalesCompanyBriefing,
            SalesCompanyBriefing.company_id == union.c.company_id,
        )
        .where(
            SalesCompanyBriefing.company_id.is_(None),
            SalesCompany.archived_at.is_(None),
            *([union.c.company_id.notin_(skip)] if skip else []),
        )
        .order_by(union.c.company_id.desc())
        .limit(MAX_BRIEFING_FIRMS * 2)
    )
    return list(rows.scalars())


async def refresh_company_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    activity = SalesActivity
    upcoming = or_(
        and_(
            activity.kind.in_(("task", "call")),
            activity.done_at.is_(None),
            activity.due_at >= now,
            activity.due_at < now + STEP_WITHIN,
        ),
        and_(
            activity.kind == "meeting",
            activity.occurred_at >= now,
            activity.occurred_at < now + STEP_WITHIN,
            *not_cancelled(),
        ),
    )
    rows = await db.execute(
        select(SalesOpportunity.company_id)
        .join(activity, activity.company_id == SalesOpportunity.company_id)
        .outerjoin(
            SalesCompanyBriefing,
            SalesCompanyBriefing.company_id == SalesOpportunity.company_id,
        )
        .where(
            live_opportunity(),
            upcoming,
            or_(
                SalesCompanyBriefing.company_id.is_(None),
                SalesCompanyBriefing.generated_at < now - STALE_AFTER,
            ),
        )
        .distinct()
        .limit(MAX_REFRESH_FIRMS)
    )
    return list(rows.scalars())


def needs_points(
    company_ids: Iterable[int], briefed_at: dict[int, datetime], *, now: datetime
) -> list[int]:
    """Firmy bez punktów albo z punktami starszymi niż ``STALE_AFTER``, bez powtórzeń."""

    chosen: list[int] = []
    for cid in company_ids:
        if cid in chosen:
            continue
        generated = briefed_at.get(cid)
        if generated is not None and generated >= now - STALE_AFTER:
            continue
        chosen.append(cid)
        if len(chosen) >= MAX_REFRESH_FIRMS:
            break
    return chosen


async def to_decide_company_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    """Firmy ofert „Do decyzji” do odświeżenia punktów, od największego MRR.

    Sekcję wyznacza ``offers.load_rows``, ta sama co na ekranie Oferty. Firma
    w archiwum odpada, bo przyjęcie raportu i tak by jej punktów nie zapisało.
    """

    rows = [
        row for row in await offers.load_rows(db, now=now) if row.section == "to_decide"
    ]
    rows.sort(key=lambda row: -(row.opportunity.mrr_value or 0))
    company_ids = [row.opportunity.company_id for row in rows]
    if not company_ids:
        return []
    found = await db.execute(
        select(SalesCompany.id, SalesCompanyBriefing.generated_at)
        .outerjoin(
            SalesCompanyBriefing, SalesCompanyBriefing.company_id == SalesCompany.id
        )
        .where(
            SalesCompany.id.in_(set(company_ids)), SalesCompany.archived_at.is_(None)
        )
    )
    briefed_at: dict[int, datetime] = {}
    live: set[int] = set()
    for cid, generated in found.all():
        live.add(cid)
        if generated is not None:
            briefed_at[cid] = generated
    return needs_points(
        [cid for cid in company_ids if cid in live], briefed_at, now=now
    )


async def modes_for(
    db: AsyncSession,
    company_ids: Iterable[int],
    *,
    now: datetime,
    ongoing: Iterable[int] = (),
) -> dict[int, str]:
    """``ongoing``, gdy była rozmowa albo spotkanie albo firma jest w ``ongoing``
    (oferta „Do decyzji”: ofertę już wysłano); inaczej ``first_call``."""

    ids = sorted(set(company_ids))
    if not ids:
        return {}
    activity = SalesActivity
    talked = await db.execute(
        select(activity.company_id)
        .where(
            activity.company_id.in_(ids),
            or_(
                and_(activity.kind == "call", activity.done_at.is_not(None)),
                and_(
                    activity.kind == "meeting",
                    activity.occurred_at < now,
                    *not_cancelled(),
                ),
            ),
        )
        .distinct()
    )
    talked_ids = set(talked.scalars()) | set(ongoing)
    return {cid: ("ongoing" if cid in talked_ids else "first_call") for cid in ids}


def pick(candidates: Iterable[int], *, skip: set[int], limit: int) -> list[int]:
    chosen: list[int] = []
    for cid in candidates:
        if cid in skip or cid in chosen:
            continue
        chosen.append(cid)
        if len(chosen) >= limit:
            break
    return chosen


# ── „Warto wrócić”: przegrane szanse z powodem „wróć później” ───────────


@dataclass(frozen=True)
class LostDeal:
    """Najświeższa przegrana szansa firmy, która kwalifikuje firmę do powrotu."""

    opportunity_id: int
    company_id: int
    title: str
    lost_reason: str
    lost_at: datetime
    owner_user_id: Optional[int]


def months_before(day: date, months: int) -> date:
    """Ten sam dzień ``months`` miesięcy wcześniej (31.03 − 1 miesiąc = 28/29.02)."""

    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    for candidate in range(day.day, 27, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    return date(year, month, min(day.day, 28))


async def winback_deals(
    db: AsyncSession,
    *,
    now: datetime,
    company_ids: Optional[Iterable[int]] = None,
) -> dict[int, LostDeal]:
    """Firmy do „Warto wrócić”: id firmy → najświeższa kwalifikująca przegrana.

    Kolejność słownika to kolejność biegu: od najświeższej przegranej. Klient
    NEXUSA odpada, bo popyt u klienta prowadzi jego Delivery Lead.
    """

    since = local_day_start_utc(months_before(business_date(now), WINBACK_MONTHS))
    other = aliased(SalesOpportunity)
    has_live = (
        select(other.id)
        .where(
            other.company_id == SalesOpportunity.company_id,
            other.status == "open",
            other.archived_at.is_(None),
        )
        .exists()
    )
    query = (
        select(SalesOpportunity, SalesCompany)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .where(
            SalesOpportunity.status == "lost",
            SalesOpportunity.lost_at >= since,
            SalesOpportunity.lost_at <= now,
            func.btrim(SalesOpportunity.lost_reason).in_(WINBACK_LOST_REASONS),
            SalesCompany.archived_at.is_(None),
            ~has_live,
        )
        .order_by(SalesOpportunity.lost_at.desc(), SalesOpportunity.id.desc())
    )
    if company_ids is not None:
        ids = sorted(set(company_ids))
        if not ids:
            return {}
        query = query.where(SalesOpportunity.company_id.in_(ids))
    deals: dict[int, LostDeal] = {}
    companies: dict[int, SalesCompany] = {}
    for opp, company in (await db.execute(query)).all():
        if company.id in deals:
            continue
        companies[company.id] = company
        deals[company.id] = LostDeal(
            opportunity_id=opp.id,
            company_id=company.id,
            title=opp.title,
            lost_reason=(opp.lost_reason or "").strip(),
            lost_at=opp.lost_at,
            owner_user_id=opp.owner_user_id,
        )
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=cid,
                client_id=company.client_id,
                normalized_name=company.normalized_name,
            )
            for cid, company in companies.items()
        ],
    )
    return {cid: deal for cid, deal in deals.items() if cid not in clients}


async def winback_company_ids(db: AsyncSession, *, now: datetime) -> list[int]:
    deals = await winback_deals(db, now=now)
    return list(deals)[:MAX_WINBACK_FIRMS]
