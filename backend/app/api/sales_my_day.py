"""Sprzedaż → „Mój dzień”: kolejka zalogowanej osoby (prefiks ``/api/sales/my-day``)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesLead
from app.services.sales import signals as sales_signals
from app.services.sales.my_day import DayPerson, DayRow, MeetingPrep, MyDay, load_my_day

router = APIRouter()


class Ref(BaseModel):
    id: int
    name: str


class OpportunityRef(BaseModel):
    id: int
    title: str


class PersonOut(BaseModel):
    id: int
    name: str
    title: Optional[str]
    phone: Optional[str]
    email: Optional[str]


class RowOut(BaseModel):
    key: str
    section: str
    company: Ref
    opportunity: Optional[OpportunityRef]
    activity_id: Optional[int]
    kind: Optional[str]
    subject: Optional[str]
    at: datetime
    days: int
    amount: Optional[Decimal]
    currency: str
    open_opportunities: int
    duration_minutes: Optional[int]
    web_link: Optional[str]
    do_not_contact: bool
    person: Optional[PersonOut]
    people_without_phone: list[PersonOut]


class HistoryOut(BaseModel):
    kind: str
    direction: Optional[str]
    at: datetime
    subject: Optional[str]
    days: int


class PrepOut(BaseModel):
    activity_id: int
    company: Ref
    subject: Optional[str]
    at: datetime
    duration_minutes: Optional[int]
    open_opportunities: int
    can_create_opportunity: bool
    history: list[HistoryOut]
    contacts: list[PersonOut]


class CountsOut(BaseModel):
    meetings: int
    reply: int
    overdue: int
    offers: int
    older_tasks: int
    signals: int = 0


class SignalOut(BaseModel):
    """Nowy sygnał z bota researchu (``services/sales/signals.py``)."""

    lead_id: int
    company: Ref
    title: str
    strength: Optional[str]
    type: Optional[str]
    signal_at: Optional[datetime]


class MyDayOut(BaseModel):
    today: date
    counts: CountsOut
    meetings: list[RowOut]
    reply: list[RowOut]
    overdue: list[RowOut]
    offers: list[RowOut]
    prep: Optional[PrepOut]
    signals: list[SignalOut] = []


def _signal(lead: SalesLead) -> SignalOut:
    payload = lead.payload or {}
    return SignalOut(
        lead_id=lead.id,
        company=Ref(id=lead.company_id or 0, name=lead.company_name or ""),
        title=lead.title,
        strength=payload.get("strength"),
        type=payload.get("type"),
        signal_at=lead.signal_at,
    )


def _person(person: DayPerson) -> PersonOut:
    return PersonOut(
        id=person.id,
        name=person.name,
        title=person.title,
        phone=person.phone,
        email=person.email,
    )


def _row(row: DayRow) -> RowOut:
    return RowOut(
        key=row.key,
        section=row.section,
        company=Ref(id=row.company_id, name=row.company_name),
        opportunity=(
            OpportunityRef(id=row.opportunity.id, title=row.opportunity.title)
            if row.opportunity
            else None
        ),
        activity_id=row.activity_id,
        kind=row.kind,
        subject=row.subject,
        at=row.at,
        days=row.days,
        amount=row.amount,
        currency=row.currency,
        open_opportunities=row.open_opportunities,
        duration_minutes=row.duration_minutes,
        web_link=row.web_link,
        do_not_contact=row.do_not_contact,
        person=_person(row.person) if row.person else None,
        people_without_phone=[_person(item) for item in row.people_without_phone],
    )


def _prep(prep: Optional[MeetingPrep]) -> Optional[PrepOut]:
    if prep is None:
        return None
    return PrepOut(
        activity_id=prep.activity_id,
        company=Ref(id=prep.company_id, name=prep.company_name),
        subject=prep.subject,
        at=prep.at,
        duration_minutes=prep.duration_minutes,
        open_opportunities=prep.open_opportunities,
        can_create_opportunity=prep.can_create_opportunity,
        history=[
            HistoryOut(
                kind=item.kind,
                direction=item.direction,
                at=item.at,
                subject=item.subject,
                days=item.days,
            )
            for item in prep.history
        ],
        contacts=[_person(item) for item in prep.contacts],
    )


def _out(day: MyDay, signals: list[SalesLead]) -> MyDayOut:
    return MyDayOut(
        today=day.today,
        counts=CountsOut(
            meetings=len(day.meetings),
            reply=len(day.reply),
            overdue=len(day.overdue),
            offers=len(day.offers),
            older_tasks=day.older_tasks,
            signals=len(signals),
        ),
        meetings=[_row(row) for row in day.meetings],
        reply=[_row(row) for row in day.reply],
        overdue=[_row(row) for row in day.overdue],
        offers=[_row(row) for row in day.offers],
        prep=_prep(day.prep),
        signals=[_signal(lead) for lead in signals],
    )


@router.get("", response_model=MyDayOut)
async def my_day(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> MyDayOut:
    """Kolejka dnia zalogowanej osoby; przełącznika osoby nie ma z założenia."""

    now = datetime.now(timezone.utc)
    day = await load_my_day(db, current_user.id, now=now)
    return _out(day, await sales_signals.my_day_signals(db, current_user.id, now=now))
