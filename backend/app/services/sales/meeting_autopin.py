"""Spotkanie z kalendarza przypina się samo (decyzja Artura 10.11.2026).

Synchronizacja przypina spotkanie do firmy, a do szansy przypinał je handlowiec.
Prowadzący ma 4–9 spotkań tygodniowo i od 26.10 nie przypiął żadnego z 15, więc
gdy nie ma czego wybierać, robi to automat:

* firma ma **dokładnie jedną otwartą szansę**, a spotkanie nie jest starsze od niej
  (spotkanie sprzed dnia jej założenia zostaje wpisem firmy);
* albo spotkanie trafia w termin przekazania z formularza „Umów spotkanie”
  (``handoff.ADOPT_WINDOW``): wtedy wiadomo, której szansy dotyczy, także gdy firma
  ma ich kilka, a wpis terminu z formularza zastępuje spotkanie z kalendarza.

Kilka szans bez takiego terminu to nadal wybór człowieka w zakładce Spotkania. Poza
automatem zostają też nasza spółka i klient NEXUSA (tam decyzją jest przekazanie do
Delivery Leada) oraz jedno wydarzenie, które wskazywałoby szanse w kilku firmach.

Przypięcie da się cofnąć zwykłym „Cofnij przypięcie”, a cofnięte nie wraca:
historia szansy ma wtedy wiersz odpięcia tej aktywności. Automat zapisuje przypięcie
bez osoby (``user_id`` puste), po tym ekran poznaje „przypięte samo”.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, and_, cast, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services.sales import client_gate, handoff, meeting_decisions
from app.services.sales.outlook_activities import EVENT_SOURCE


def _open_opportunity(*conditions):
    return (
        SalesOpportunity.status == "open",
        SalesOpportunity.archived_at.is_(None),
        *conditions,
    )


def auto_pinned(activity_id_column):
    """Warunek: tę aktywność do jej obecnej szansy przypiął automat, nie człowiek.

    Po ręcznym odpięciu automat już nie przypina, więc każde późniejsze przypięcie
    jest decyzją człowieka.
    """

    as_text = cast(activity_id_column, String)
    return and_(
        exists().where(
            SalesOpportunityEvent.field == meeting_decisions.OUTLOOK_FIELD,
            SalesOpportunityEvent.user_id.is_(None),
            SalesOpportunityEvent.new_value == as_text,
            SalesOpportunityEvent.opportunity_id == SalesActivity.opportunity_id,
        ),
        ~exists().where(
            SalesOpportunityEvent.field == meeting_decisions.OUTLOOK_FIELD,
            SalesOpportunityEvent.new_value.is_(None),
            SalesOpportunityEvent.old_value == as_text,
        ),
    )


def _target(
    activity: SalesActivity, opportunities: list[SalesOpportunity]
) -> tuple[Optional[SalesOpportunity], bool]:
    """Szansa, której dotyczy spotkanie, i czy wskazał ją termin przekazania."""

    booked = [
        opportunity
        for opportunity in opportunities
        if (term := handoff.planned_term(opportunity)) is not None
        and abs(term - activity.occurred_at) <= handoff.ADOPT_WINDOW
    ]
    if len(booked) == 1:
        return booked[0], True
    if len(opportunities) == 1 and business_date(activity.occurred_at) >= business_date(
        opportunities[0].created_at
    ):
        # Liczy się dzień firmy: szansę zakłada się też w trakcie spotkania albo tuż po nim.
        return opportunities[0], False
    return None, False


async def pin_obvious_meetings(db: AsyncSession, *, now: datetime) -> int:
    """Przypnij spotkania, przy których nie ma czego wybierać. Wywołujący robi commit."""

    was_unpinned = exists().where(
        SalesOpportunityEvent.field == meeting_decisions.OUTLOOK_FIELD,
        SalesOpportunityEvent.new_value.is_(None),
        SalesOpportunityEvent.old_value == cast(SalesActivity.id, String),
    )
    company_has_open = exists().where(
        *_open_opportunity(SalesOpportunity.company_id == SalesActivity.company_id)
    )
    activities = (
        await db.scalars(
            select(SalesActivity)
            .where(
                SalesActivity.kind == "meeting",
                SalesActivity.external_source == EVENT_SOURCE,
                SalesActivity.external_ref.is_(None),
                SalesActivity.opportunity_id.is_(None),
                SalesActivity.occurred_at.is_not(None),
                company_has_open,
                ~was_unpinned,
            )
            .order_by(SalesActivity.id)
            .with_for_update(skip_locked=True, of=SalesActivity)
        )
    ).all()
    if not activities:
        return 0

    company_ids = {activity.company_id for activity in activities}
    companies = (
        await db.execute(
            select(
                SalesCompany.id, SalesCompany.client_id, SalesCompany.normalized_name
            ).where(SalesCompany.id.in_(company_ids))
        )
    ).all()
    handed_to_delivery = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=company_id, client_id=client_id, normalized_name=key
            )
            for company_id, client_id, key in companies
        ],
    )
    skipped = set(handed_to_delivery) | {
        company_id
        for company_id, _, key in companies
        if key == client_gate.OWN_COMPANY_KEY
    }
    open_by_company: dict[int, list[SalesOpportunity]] = {}
    for opportunity in (
        await db.scalars(
            select(SalesOpportunity)
            .where(*_open_opportunity(SalesOpportunity.company_id.in_(company_ids)))
            .order_by(SalesOpportunity.id)
        )
    ).all():
        open_by_company.setdefault(opportunity.company_id, []).append(opportunity)

    # Jedno wydarzenie bywa przy kilku firmach: przypinamy tylko, gdy wskazuje jedną szansę.
    candidates: dict[str, list[tuple[SalesActivity, SalesOpportunity, bool]]] = {}
    for activity in activities:
        if activity.company_id in skipped:
            continue
        target, booked = _target(activity, open_by_company.get(activity.company_id, []))
        if target is not None:
            key = activity.external_id or f"id:{activity.id}"
            candidates.setdefault(key, []).append((activity, target, booked))

    pinned = 0
    for copies in candidates.values():
        booked_copies = [copy for copy in copies if copy[2]]
        chosen = booked_copies or copies
        if len(chosen) != 1:
            continue
        activity, target, _ = chosen[0]
        opportunity = await db.scalar(
            select(SalesOpportunity)
            .where(*_open_opportunity(SalesOpportunity.id == target.id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if opportunity is None:
            continue
        meeting_decisions.attach(db, activity, opportunity, user_id=None, now=now)
        await handoff.adopt_calendar_meeting(db, opportunity, activity)
        pinned += 1
    return pinned
