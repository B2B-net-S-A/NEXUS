"""Które firmy idą do bota researchu i z jakim rodzajem punktów do rozmowy.

* **Sygnały:** firmy z tagiem pilota (``SALES_SIGNALS_TAG``), raz w tygodniu.
* **Punkty, nowe:** firma z leadem albo szansą z ostatnich 7 dni, bez punktów.
* **Punkty, odświeżenie w poniedziałek:** otwarta szansa z krokiem albo spotkaniem
  w ciągu 14 dni, punkty starsze niż 6 dni.
* **Punkty przy ofertach „Do decyzji”** (decyzja Artura 12.11.2026): w tym samym
  poniedziałkowym odświeżeniu firmy pozycji z sekcji „Do decyzji” zakładki Oferty,
  z tymi samymi progami. Taka pozycja z definicji nie ma kroku, więc reguła wyżej
  jej nie łapie, a decydujący ma zobaczyć, co się w firmie zmieniło.
* **Mapy decydentów (``people``):** w poniedziałek konta Fabryk IT z mapą poniżej
  3 osób, najwyżej 20 firm (``docs/claude/sprzedaz/mapy-decydentow-od-bota.md``).

Rodzaj punktów: ``ongoing``, gdy z firmą była już rozmowa albo spotkanie albo gdy
firma ma ofertę „Do decyzji”, inaczej ``first_call``. Firma z biegu z ostatnich
24 godzin nie wraca od razu, żeby firma, o której bot nic nie napisał, nie szła
do niego co godzinę.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.sales import (
    SalesActivity,
    SalesBotResult,
    SalesCompany,
    SalesCompanyBriefing,
    SalesLead,
    SalesOpportunity,
    SalesPipeline,
    SalesSignalRun,
)
from app.services.sales import client_gate, company_aliases
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY, decision_entries
from app.services.sales.factories import COMPANY_DO_NOT_CONTACT
from app.services.sales import offers
from app.services.sales.task_scope import live_opportunity
from app.services.sales.touch import not_cancelled

NEW_WITHIN = timedelta(days=7)
STEP_WITHIN = timedelta(days=14)
STALE_AFTER = timedelta(days=6)
RESEND_AFTER = timedelta(hours=24)
MAX_BRIEFING_FIRMS = 25
MAX_REFRESH_FIRMS = 100
MAX_PILOT_FIRMS = 100


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


# ── Mapy decydentów od bota (``people``, decyzja Artura 12.11.2026) ──────

#: Mapa z mniej niż tylu osobami idzie do tygodniowego przeglądu (panel: „min. 3”).
PEOPLE_MIN_MAP = 3
#: Firma z biegiem ``people`` z ostatnich 7 dni nie wraca w tygodniowym przeglądzie.
PEOPLE_RESEND_AFTER = timedelta(days=7)


async def people_recently_sent(
    db: AsyncSession, *, now: datetime, within: timedelta
) -> set[int]:
    """Firmy z biegiem ``people`` (ręcznym albo tygodniowym) w oknie; bez nieudanych."""

    runs = await db.execute(
        select(SalesSignalRun.company_ids).where(
            SalesSignalRun.kind == "people",
            SalesSignalRun.status != "failed",
            SalesSignalRun.started_at >= now - within,
        )
    )
    return {int(cid) for ids in runs.scalars() for cid in ids}


async def people_company_ids(
    db: AsyncSession, *, now: datetime, limit: int
) -> list[int]:
    """Konta Fabryk IT z mapą poniżej 3 osób; najpierw najuboższe mapy.

    Bez klienta NEXUSA (temat prowadzi Delivery Lead, przegląd i tak nie doda
    osoby), bez „Nie kontaktować”, naszej firmy, firm z otwartym wynikiem
    ``people`` do przeglądu i firm z biegiem z ostatnich 7 dni.
    """

    rows = (
        await db.execute(
            select(
                SalesCompany.id,
                SalesCompany.client_id,
                SalesCompany.normalized_name,
                SalesOpportunity.custom_fields,
            )
            .join(SalesOpportunity, SalesOpportunity.company_id == SalesCompany.id)
            .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
            .where(
                SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
                live_opportunity(),
                SalesCompany.archived_at.is_(None),
                or_(
                    SalesCompany.status.is_(None),
                    SalesCompany.status != COMPANY_DO_NOT_CONTACT,
                ),
            )
            .order_by(SalesCompany.id)
        )
    ).all()
    sizes: dict[int, int] = {}
    identities: dict[int, client_gate.CompanyIdentity] = {}
    for row in rows:
        if company_aliases.is_own_company(row.normalized_name or ""):
            continue
        size = len(decision_entries(row.custom_fields))
        sizes[row.id] = min(size, sizes.get(row.id, size))
        identities[row.id] = client_gate.CompanyIdentity(
            company_id=row.id,
            client_id=row.client_id,
            normalized_name=row.normalized_name,
        )
    small = [cid for cid, size in sizes.items() if size < PEOPLE_MIN_MAP]
    if not small:
        return []
    clients = await client_gate.match_companies(db, [identities[c] for c in small])
    pending = set(
        (
            await db.execute(
                select(SalesBotResult.company_id).where(
                    SalesBotResult.kind == "people",
                    SalesBotResult.status.in_(("new", "partial")),
                    SalesBotResult.company_id.in_(small),
                )
            )
        ).scalars()
    )
    skip = (
        await people_recently_sent(db, now=now, within=PEOPLE_RESEND_AFTER)
        | pending
        | set(clients)
    )
    ordered = sorted(small, key=lambda cid: (sizes[cid], cid))
    return pick(ordered, skip=skip, limit=limit)
