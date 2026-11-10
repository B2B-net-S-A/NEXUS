"""Które firmy idą do bota researchu i z jakim rodzajem punktów do rozmowy.

* **Sygnały:** firmy z tagiem pilota (``SALES_SIGNALS_TAG``), raz w tygodniu.
* **Punkty, nowe:** firma z leadem albo szansą z ostatnich 7 dni, bez punktów.
* **Punkty, odświeżenie w poniedziałek:** otwarta szansa z krokiem albo spotkaniem
  w ciągu 14 dni, punkty starsze niż 6 dni.

Rodzaj punktów: ``ongoing``, gdy z firmą była już rozmowa albo spotkanie, inaczej
``first_call``. Firma z biegu z ostatnich 24 godzin nie wraca od razu, żeby
firma, o której bot nic nie napisał, nie szła do niego co godzinę.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyBriefing,
    SalesLead,
    SalesOpportunity,
    SalesSignalRun,
)
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


async def modes_for(
    db: AsyncSession, company_ids: Iterable[int], *, now: datetime
) -> dict[int, str]:
    """``ongoing``, gdy była rozmowa albo spotkanie; inaczej ``first_call``."""

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
    ongoing = set(talked.scalars())
    return {cid: ("ongoing" if cid in ongoing else "first_call") for cid in ids}


def pick(candidates: Iterable[int], *, skip: set[int], limit: int) -> list[int]:
    chosen: list[int] = []
    for cid in candidates:
        if cid in skip or cid in chosen:
            continue
        chosen.append(cid)
        if len(chosen) >= limit:
            break
    return chosen
