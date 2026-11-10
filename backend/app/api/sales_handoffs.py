"""Sprzedaż → przekazanie spotkania i werdykt (prefiks ``/api/sales/handoffs``).

„Umów spotkanie” zakłada szansę u prowadzącego, „Przekazane do Ciebie” pokazuje mu
umówione spotkania, a werdykt po spotkaniu wraca do osoby, która je umówiła. Reguły
są w ``services/sales/handoff.py`` (zapis) i ``handoff_views.py`` (listy). Odczyt: „Sprzedaż: podgląd”, zapis: „Sprzedaż:
edycja”; werdykt daje opiekun szansy albo administrator. Listy są zawsze dla
zalogowanej osoby: przełącznika osoby, celu ani rankingu tu nie ma.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.scheduling import business_date
from app.services.sales import (
    company_dates,
    handoff,
    handoff_hosts,
    handoff_invite,
    handoff_state,
    handoff_views,
)

router = APIRouter()


class Ref(BaseModel):
    id: int
    name: str


class PersonOut(BaseModel):
    id: int
    name: str
    title: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    do_not_contact: bool


class HandoffOut(BaseModel):
    opportunity: Ref
    company: Ref
    status: str
    stage_key: str
    stage_name: str
    host: Optional[Ref]
    booked_by: Optional[Ref]
    booked_at: Optional[datetime]
    meeting_at: Optional[datetime]
    duration_minutes: int
    #: Termin czytany z kalendarza Outlook; zmienia się go w Outlooku.
    from_calendar: bool
    service: Optional[str]
    problem: Optional[str]
    decision_maker: Optional[str]
    timing: Optional[str]
    contact: Optional[PersonOut]
    confirmed_at: Optional[datetime]
    verdict: Optional[handoff_state.VerdictKind]
    verdict_at: Optional[datetime]
    verdict_reason: Optional[str]
    return_on: Optional[date]
    phase: handoff_state.Phase
    clash: bool
    #: Kiedy prowadzący wysłał zaproszenie z Outlooka; ``null``, gdy nie wyszło.
    invite_sent_at: Optional[datetime] = None


class WeekOut(BaseModel):
    week_start: date
    booked: int
    held: int
    qualified: int


class HandoffsOut(BaseModel):
    to_me: list[HandoffOut]
    booked_by_me: list[HandoffOut]
    #: Tygodnie osoby, która umawia, od bieżącego; puste, gdy nic nie umówiła.
    weeks: list[WeekOut]


class FormOut(BaseModel):
    hosts: list[Ref]
    default_host_id: Optional[int]


class BusySpan(BaseModel):
    start: datetime
    end: datetime


class InviteRecipientOut(BaseModel):
    address: str
    name: Optional[str]
    blocked: Optional[Literal["candidate"]] = None


class InviteDraftOut(BaseModel):
    mailbox: Literal["ok", "missing", "no_calendar_scope"]
    subject: str
    recipients: list[InviteRecipientOut]
    meeting_at: Optional[datetime]
    duration_minutes: int
    sent_at: Optional[datetime]


class HostBusyOut(BaseModel):
    #: ``ok`` kalendarz ze skrzynki prowadzącego; ``unavailable`` skrzynka nie jest
    #: połączona i widać tylko spotkania zapisane w Sprzedaży.
    calendar: str
    busy: list[BusySpan]


def _ref(id_: Optional[int], name: Optional[str]) -> Optional[Ref]:
    return Ref(id=id_, name=name or "") if id_ is not None else None


def _out(view: handoff_views.HandoffView) -> HandoffOut:
    return HandoffOut(
        opportunity=Ref(id=view.opportunity_id, name=view.title),
        company=Ref(id=view.company_id, name=view.company_name),
        status=view.status,
        stage_key=view.stage_key,
        stage_name=view.stage_name,
        host=_ref(view.host_id, view.host_name),
        booked_by=_ref(view.booked_by_id, view.booked_by_name),
        booked_at=view.booked_at,
        meeting_at=view.meeting_at,
        duration_minutes=view.duration_minutes,
        from_calendar=view.from_calendar,
        service=view.service,
        problem=view.problem,
        decision_maker=view.decision_maker,
        timing=view.timing,
        contact=(
            PersonOut(
                id=view.contact.id,
                name=view.contact.name,
                title=view.contact.title,
                phone=view.contact.phone,
                email=view.contact.email,
                do_not_contact=view.contact.do_not_contact,
            )
            if view.contact is not None
            else None
        ),
        confirmed_at=view.confirmed_at,
        verdict=view.verdict,
        verdict_at=view.verdict_at,
        verdict_reason=view.verdict_reason,
        return_on=view.return_on,
        phase=view.phase,
        clash=view.clash,
        invite_sent_at=view.invite_sent_at,
    )


async def _one(db: AsyncSession, opportunity_id: int) -> HandoffOut:
    view = await handoff_views.for_opportunity(
        db, opportunity_id, datetime.now(timezone.utc)
    )
    assert view is not None  # zapis właśnie zostawił blok przekazania
    return _out(view)


@router.get("", response_model=HandoffsOut)
async def my_handoffs(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffsOut:
    """Spotkania przekazane zalogowanej osobie i te, które sama umówiła."""

    now = datetime.now(timezone.utc)
    booked = await handoff_views.for_booker(db, current_user.id, now)
    weeks = await handoff_views.weeks_for_booker(
        db, current_user.id, business_date(now)
    )
    has_numbers = any(week.booked or week.held for week in weeks)
    return HandoffsOut(
        to_me=[
            _out(view)
            for view in await handoff_views.for_host(db, current_user.id, now)
        ],
        booked_by_me=[_out(view) for view in booked],
        weeks=(
            [
                WeekOut(
                    week_start=week.week_start,
                    booked=week.booked,
                    held=week.held,
                    qualified=week.qualified,
                )
                for week in weeks
            ]
            if has_numbers or booked
            else []
        ),
    )


@router.get("/form", response_model=FormOut)
async def booking_form(
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> FormOut:
    """Komu można przekazać spotkanie i kto był prowadzącym ostatnio."""

    hosts = await handoff_hosts.sales_editors(db)
    return FormOut(
        hosts=[Ref(id=user.id, name=user.name) for user in hosts],
        default_host_id=await handoff_hosts.default_host_id(
            db, current_user.id, {user.id for user in hosts}
        ),
    )


@router.get("/host-busy", response_model=HostBusyOut)
async def host_busy(
    current_user: SalesEditUser,
    host_id: int = Query(...),
    day: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> HostBusyOut:
    """Zajęte godziny prowadzącego w dniu firmy: same przedziały, bez tytułów spotkań.

    Tylko dla kont, którym można przekazać spotkanie, żeby trasa nie była
    podglądem cudzych kalendarzy.
    """

    await handoff_hosts.ensure_host(db, host_id)
    connected, spans = await handoff_hosts.host_busy(db, host_id, day)
    return HostBusyOut(
        calendar="ok" if connected else "unavailable",
        busy=[BusySpan(start=start, end=end) for start, end in spans],
    )


@router.get("/by-opportunity/{opportunity_id}", response_model=Optional[HandoffOut])
async def opportunity_handoff(
    opportunity_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> Optional[HandoffOut]:
    """Przekazanie na karcie szansy; ``null``, gdy szansa go nie ma."""

    view = await handoff_views.for_opportunity(
        db, opportunity_id, datetime.now(timezone.utc)
    )
    return _out(view) if view is not None else None


@router.post("", response_model=HandoffOut, status_code=status.HTTP_201_CREATED)
async def book_meeting(
    payload: handoff.BookRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    """„Umów spotkanie”: szansa u prowadzącego, osoba jako kontakt, termin przy szansie."""

    now = datetime.now(timezone.utc)
    booked = await handoff.book(
        db, payload, user_id=current_user.id, admin=is_admin(current_user), now=now
    )
    opportunity_id, company_id = booked.opportunity.id, booked.company.id
    backfill = booked.created and company_dates.needs_run(
        booked.company.dates_backfill, now=now
    )
    await db.commit()
    if backfill:
        # Pierwsza szansa w firmie: daty osób z tej firmy uzupełniamy w tle (D3).
        company_dates.schedule_company_dates(company_id)
    return await _one(db, opportunity_id)


@router.put("/{opportunity_id}/term", response_model=HandoffOut)
async def set_term(
    opportunity_id: int,
    payload: handoff.TermRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    opportunity = await handoff.lock(db, opportunity_id)
    handoff.ensure_can_set_term(
        opportunity, current_user.id, admin=is_admin(current_user)
    )
    await handoff.set_term(
        db,
        opportunity,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await _one(db, opportunity_id)


@router.post("/{opportunity_id}/confirm", response_model=HandoffOut)
async def confirm_term(
    opportunity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    """Klient potwierdził termin; NEXUS niczego do klienta nie wysyła."""

    opportunity = await handoff.lock(db, opportunity_id)
    handoff.ensure_can_set_term(
        opportunity, current_user.id, admin=is_admin(current_user)
    )
    await handoff.confirm(
        db, opportunity, user_id=current_user.id, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return await _one(db, opportunity_id)


@router.post("/{opportunity_id}/verdict", response_model=HandoffOut)
async def give_verdict(
    opportunity_id: int,
    payload: handoff.VerdictRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    opportunity = await handoff.lock(db, opportunity_id)
    handoff.ensure_can_give_verdict(
        opportunity, current_user.id, admin=is_admin(current_user)
    )
    await handoff.give_verdict(
        db,
        opportunity,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await _one(db, opportunity_id)


@router.get("/{opportunity_id}/invite", response_model=InviteDraftOut)
async def invite_draft(
    opportunity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> InviteDraftOut:
    """Okno „Wyślij zaproszenie”: stan skrzynki, temat i adresat. Tylko dla prowadzącego,
    bo odpowiedź mówi, czy adres osoby jest w bazie kandydatów."""

    opportunity = await handoff.fetch(db, opportunity_id)
    handoff_invite.ensure_host(opportunity, current_user.id)
    found = await handoff_invite.draft(db, opportunity, user_id=current_user.id)
    return InviteDraftOut(
        mailbox=found.mailbox,
        subject=found.subject,
        recipients=[
            InviteRecipientOut(
                address=item.address, name=item.name, blocked=item.blocked
            )
            for item in found.recipients
        ],
        meeting_at=found.meeting_at,
        duration_minutes=found.duration_minutes,
        sent_at=found.sent_at,
    )


@router.post("/{opportunity_id}/invite", response_model=HandoffOut)
async def send_invite(
    opportunity_id: int,
    payload: handoff_invite.InviteRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    """Zaproszenie Teams ze skrzynki prowadzącego, po jego kliknięciu."""

    # Najpierw prowadzący: odpowiedź o adresach kandydatów nie może trafić do kogoś,
    # kto tego zaproszenia nie wysyła.
    opportunity = await handoff.lock(db, opportunity_id)
    handoff_invite.ensure_host(opportunity, current_user.id)
    subject = payload.subject.strip()
    if not subject:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Zaproszenie musi mieć temat."
        )
    addresses = handoff_invite.clean_addresses(payload.to)
    # Bez wymieniania adresów, żeby wpisywanie nie sprawdzało, kto jest w bazie.
    if await handoff_invite.candidate_addresses(db, addresses):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=handoff_invite.CANDIDATE_DETAIL,
        )
    connection = await handoff_invite.own_connection(db, current_user.id)
    mailbox = handoff_invite.mailbox_state(connection)
    if mailbox != "ok" or connection is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                handoff_invite.NO_MAILBOX_DETAIL
                if mailbox == "missing"
                else handoff_invite.NO_SCOPE_DETAIL
            ),
        )
    start, minutes = await handoff_invite.reserve(
        db, opportunity, payload, now=datetime.now(timezone.utc)
    )
    await db.commit()  # klucz widzi drugie żądanie, zanim zaproszenie wyjdzie

    try:
        event = await handoff_invite.deliver(
            db,
            connection,
            opportunity_id=opportunity_id,
            subject=subject,
            message=payload.message,
            start=start,
            minutes=minutes,
            to=addresses,
        )
    except handoff_invite.Undelivered:
        await db.rollback()
        await handoff_invite.release(db, opportunity_id, payload.request_id)
        await db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=handoff_invite.UNDELIVERED_DETAIL
        )
    except handoff_invite.Uncertain:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=handoff_invite.UNCERTAIN_DETAIL
        )

    opportunity = await handoff.lock(db, opportunity_id)
    await handoff_invite.record_sent(
        db,
        opportunity,
        event,
        request_id=payload.request_id,
        subject=subject,
        start=start,
        minutes=minutes,
        attendees=len(addresses),
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return await _one(db, opportunity_id)
