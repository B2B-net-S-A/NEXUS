"""Krok szansy i ostatni kontakt: jedna definicja dla listy, kafelka i karty.

**Krok** to najbliższa z dwóch rzeczy:

* otwarte zadanie albo telefon z terminem od początku dzisiejszego dnia firmy, przy
  tej szansie albo przy jej firmie bez przypisania do szansy;
* przyszłe, nieodwołane spotkanie firmy.

**Po terminie** to osobny stan: otwarte zadanie albo telefon tej szansy z terminem
sprzed dzisiaj. Telefon bez terminu (tak wygląda import historii) krokiem nie jest.

**Ostatni kontakt** bierze chwilę dotyku z ``touch.py``, bez zadań (rodzaj i kierunek
mają być kontaktem, a zadanie nim nie jest) i bez wpisów systemowych Pipedrive.

Zapytania idą po stronie wierszy listy, nie jako podzapytania w SELECT: tablica
wczytuje do 2000 szans, a liczenie i sortowanie listy tych kolumn nie potrzebuje.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, local_day_bounds
from app.models.sales import (
    SalesActivity,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
)
from app.services import sales_schema as schema
from app.services.sales.touch import not_cancelled, touched_at

#: Czerwień „brak kroku” działa tylko w tym lejku (Fabryki IT i Przetargi to inny rytm).
ALARM_PIPELINE_KEY = "sales"
PIPEDRIVE_NOTE_SOURCE = "pipedrive_note"
#: Notatki, które Pipedrive pisał sam: przeniesienie do leada, wizyta na stronie.
PIPEDRIVE_SYSTEM_PATTERNS: tuple[str, ...] = (
    "This deal was converted to a lead%",
    "%visited the website on:%",
)


@dataclass(frozen=True)
class Step:
    kind: str
    at: datetime
    subject: Optional[str]
    #: Zadanie albo telefon do odhaczenia; spotkanie z kalendarza go nie ma.
    activity_id: Optional[int] = None


@dataclass(frozen=True)
class LastContact:
    kind: str
    direction: Optional[str]
    at: datetime


@dataclass(frozen=True)
class StepSignals:
    next_step: Optional[Step] = None
    overdue_step: Optional[Step] = None
    last_contact: Optional[LastContact] = None
    waiting_for_reply: bool = False
    step_alarm: bool = False


def not_system_entry() -> ColumnElement[bool]:
    """Odsiewa notatki napisane przez automat Pipedrive; ludzkie z importu zostają."""

    text = func.coalesce(SalesActivity.body, SalesActivity.subject, "")
    return or_(
        SalesActivity.external_source.is_(None),
        SalesActivity.external_source != PIPEDRIVE_NOTE_SOURCE,
        and_(*(text.not_ilike(pattern) for pattern in PIPEDRIVE_SYSTEM_PATTERNS)),
    )


def rules_since_utc() -> datetime:
    """Początek dnia wdrożenia zasad w kalendarzu firmy, jako chwila UTC."""

    start = datetime.combine(
        settings.SALES_STEP_RULES_SINCE, time.min, tzinfo=ZoneInfo(DEFAULT_TZ)
    )
    return start.astimezone(timezone.utc)


async def _open_items(
    db: AsyncSession, opportunity_ids: set[int], company_ids: set[int]
) -> Sequence[Any]:
    return (
        await db.execute(
            select(
                SalesActivity.kind,
                func.coalesce(
                    SalesActivity.subject, func.left(SalesActivity.body, 200)
                ).label("subject"),
                SalesActivity.due_at,
                SalesActivity.opportunity_id,
                SalesActivity.company_id,
                SalesActivity.id,
            )
            .where(
                SalesActivity.kind.in_(schema.TASK_KINDS),
                SalesActivity.done_at.is_(None),
                SalesActivity.due_at.is_not(None),
                or_(
                    SalesActivity.opportunity_id.in_(opportunity_ids),
                    and_(
                        SalesActivity.opportunity_id.is_(None),
                        SalesActivity.company_id.in_(company_ids),
                    ),
                ),
            )
            .order_by(SalesActivity.due_at, SalesActivity.id)
        )
    ).all()


async def _next_meetings(
    db: AsyncSession, company_ids: set[int], now: datetime
) -> dict[int, Step]:
    rows = (
        await db.execute(
            select(
                SalesActivity.company_id,
                SalesActivity.subject,
                SalesActivity.occurred_at,
            )
            .where(
                SalesActivity.kind == "meeting",
                SalesActivity.company_id.in_(company_ids),
                SalesActivity.occurred_at >= now,
                *not_cancelled(),
            )
            .order_by(SalesActivity.occurred_at, SalesActivity.id)
        )
    ).all()
    meetings: dict[int, Step] = {}
    for company_id, subject, occurred_at in rows:
        meetings.setdefault(company_id, Step("meeting", occurred_at, subject))
    return meetings


async def _latest_contacts(
    db: AsyncSession, group: Any, ids: set[int], now: datetime
) -> dict[int, LastContact]:
    touched = touched_at()
    rows = (
        await db.execute(
            select(
                group.label("key"),
                SalesActivity.kind,
                SalesActivity.direction,
                touched.label("at"),
            )
            .where(
                group.in_(ids),
                SalesActivity.kind != "task",
                touched < now,
                not_system_entry(),
            )
            .distinct(group)
            .order_by(group, touched.desc(), SalesActivity.id.desc())
        )
    ).all()
    return {row.key: LastContact(row.kind, row.direction, row.at) for row in rows}


async def _moved_since(
    db: AsyncSession, opportunity_ids: set[int], since: datetime
) -> set[int]:
    """Szanse z własnym ruchem od ``since``; mail do samej firmy szansy nie rusza."""

    activities = select(SalesActivity.opportunity_id).where(
        SalesActivity.opportunity_id.in_(opportunity_ids),
        func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at) >= since,
    )
    events = select(SalesOpportunityEvent.opportunity_id).where(
        SalesOpportunityEvent.opportunity_id.in_(opportunity_ids),
        SalesOpportunityEvent.created_at >= since,
    )
    return set((await db.scalars(activities.union(events))).all())


def _later(
    first: Optional[LastContact], second: Optional[LastContact]
) -> Optional[LastContact]:
    if first is None or second is None:
        return first or second
    return first if first.at >= second.at else second


def _earlier(first: Optional[Step], second: Optional[Step]) -> Optional[Step]:
    if first is None or second is None:
        return first or second
    return first if first.at <= second.at else second


async def load_signals(
    db: AsyncSession, opportunities: Iterable[SalesOpportunity], *, now: datetime
) -> dict[int, StepSignals]:
    """Krok, zaległość i ostatni kontakt dla podanych szans, po ``id`` szansy."""

    items = list(opportunities)
    if not items:
        return {}
    opportunity_ids = {opp.id for opp in items}
    company_ids = {opp.company_id for opp in items}
    day_start = local_day_bounds(now).start_utc
    since = rules_since_utc()

    next_by_opportunity: dict[int, Step] = {}
    next_by_company: dict[int, Step] = {}
    overdue: dict[int, Step] = {}
    for (
        kind,
        subject,
        due_at,
        opportunity_id,
        company_id,
        activity_id,
    ) in await _open_items(db, opportunity_ids, company_ids):
        step = Step(kind, due_at, subject, activity_id)
        if due_at >= day_start:
            if opportunity_id is not None:
                next_by_opportunity.setdefault(opportunity_id, step)
            else:
                next_by_company.setdefault(company_id, step)
        elif opportunity_id is not None:
            # Wiersze idą rosnąco po terminie: zostaje najpóźniejsza zaległość.
            overdue[opportunity_id] = step

    meetings = await _next_meetings(db, company_ids, now)
    by_opportunity = await _latest_contacts(
        db, SalesActivity.opportunity_id, opportunity_ids, now
    )
    by_company = await _latest_contacts(db, SalesActivity.company_id, company_ids, now)
    moved = await _moved_since(db, opportunity_ids, since) if since <= now else set()
    alarm_pipeline_id = await db.scalar(
        select(SalesPipeline.id).where(SalesPipeline.key == ALARM_PIPELINE_KEY)
    )

    signals: dict[int, StepSignals] = {}
    for opp in items:
        next_step = _earlier(
            _earlier(
                next_by_opportunity.get(opp.id), next_by_company.get(opp.company_id)
            ),
            meetings.get(opp.company_id),
        )
        overdue_step = overdue.get(opp.id)
        last_contact = _later(
            by_opportunity.get(opp.id), by_company.get(opp.company_id)
        )
        no_step = next_step is None and overdue_step is None
        signals[opp.id] = StepSignals(
            next_step=next_step,
            overdue_step=overdue_step,
            last_contact=last_contact,
            waiting_for_reply=(
                no_step
                and last_contact is not None
                and last_contact.kind == "email"
                and last_contact.direction == "in"
            ),
            step_alarm=(
                no_step
                and opp.status == "open"
                and opp.pipeline_id == alarm_pipeline_id
                and since <= now
                and (opp.created_at >= since or opp.id in moved)
            ),
        )
    return signals
