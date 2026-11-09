"""Terminy: wolne godziny, rezerwacja i wpis w kalendarzu właściciela."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.own_hiring import (
    OwnHiringApplication,
    OwnHiringBooking,
    OwnHiringProcess,
)
from app.models.user import User
from app.services import prep_availability, prep_meetings
from app.services.m365 import teams_prep_graph
from app.services.m365.calendar import _build_event_payload, event_transaction_id
from app.services.own_hiring import mail as mail_text
from app.services.own_hiring.service import (
    ENTITY_APPLICATION,
    Context,
    OwnHiringError,
    close,
    current_token,
    log_event,
    merged_settings,
    notify,
    now_utc,
    public_link,
    set_stage,
    token_digest,
)
from app.services.own_hiring.slots import SlotRules, compute_slots, group_by_day

logger = logging.getLogger(__name__)

BOOKABLE_STAGES = frozenset({"invited", "no_response", "assistant", "teams"})
_LOOKBEHIND = timedelta(hours=1)
MSG_CALENDAR_DOWN = "Chwilowo nie możemy pokazać terminów. Spróbuj za kilka minut."
MSG_SLOT_TAKEN = "Ten termin został właśnie zajęty. Wybierz inny."


async def _taken(
    db: AsyncSession, process_id: int, now: datetime
) -> list[tuple[datetime, datetime]]:
    rows = await db.execute(
        select(OwnHiringBooking.start_at, OwnHiringBooking.end_at).where(
            OwnHiringBooking.process_id == process_id,
            OwnHiringBooking.status == "active",
            OwnHiringBooking.end_at >= now - _LOOKBEHIND,
        )
    )
    return [(start, end) for start, end in rows]


async def free_slots(
    db: AsyncSession, process: OwnHiringProcess, *, kind: str
) -> Optional[list[datetime]]:
    """Wolne terminy albo ``None``, gdy nie da się odczytać kalendarza.

    Bez kalendarza nie pokazujemy godzin: rezerwacja mogłaby trafić na zajęty termin.
    """
    owner = await db.get(User, process.owner_user_id)
    if owner is None or not owner.email:
        return None
    now = now_utc()
    rules = SlotRules.from_settings(merged_settings(process), kind=kind)
    calendars = await prep_availability.busy_blocks(
        [owner.email], start=now, end=now + timedelta(days=rules.horizon_days + 1)
    )
    outlook = calendars.get(owner.email.strip().lower())
    if outlook is None:
        return None
    return compute_slots(
        rules, now=now, busy=[*outlook, *await _taken(db, process.id, now)]
    )


async def slots_payload(
    db: AsyncSession, process: OwnHiringProcess, *, kind: str
) -> dict[str, Any]:
    slots = await free_slots(db, process, kind=kind)
    return {
        "calendar_available": slots is not None,
        "days": group_by_day(slots or []),
    }


async def _assert_free(
    db: AsyncSession, process: OwnHiringProcess, start: datetime, kind: str
) -> None:
    slots = await free_slots(db, process, kind=kind)
    if slots is None:
        raise OwnHiringError(503, "calendar_unavailable", MSG_CALENDAR_DOWN)
    if start not in slots:
        raise OwnHiringError(409, "slot_taken", MSG_SLOT_TAKEN)


async def release_active(
    db: AsyncSession, application: OwnHiringApplication, now: datetime
) -> list[OwnHiringBooking]:
    """Anuluje aktywne rezerwacje osoby. Odwołanie w kalendarzu robi wołający po commicie."""
    rows = list(
        await db.scalars(
            select(OwnHiringBooking).where(
                OwnHiringBooking.application_id == application.id,
                OwnHiringBooking.status == "active",
            )
        )
    )
    for row in rows:
        row.status = "cancelled"
    return rows


async def finish_active(db: AsyncSession, application: OwnHiringApplication) -> None:
    rows = await db.scalars(
        select(OwnHiringBooking).where(
            OwnHiringBooking.application_id == application.id,
            OwnHiringBooking.status == "active",
        )
    )
    for row in rows:
        row.status = "done"


async def cancel_in_calendar(
    db: AsyncSession, process: OwnHiringProcess, bookings: list[OwnHiringBooking]
) -> None:
    """Odwołanie spotkań. Awaria Microsoftu nie cofa decyzji, tylko zostawia ślad w logu."""
    owner = await db.get(User, process.owner_user_id)
    if owner is None or not prep_meetings.app_only_ready():
        return
    for booking in bookings:
        if not booking.graph_event_id:
            continue
        try:
            await teams_prep_graph.cancel_event(
                owner.email, booking.graph_event_id, "Rozmowa została odwołana."
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "own_hiring.calendar_cancel_failed booking=%s error=%s",
                booking.id,
                type(exc).__name__,
            )


async def _insert(
    db: AsyncSession,
    application: OwnHiringApplication,
    *,
    kind: str,
    start: datetime,
    minutes: int,
    via: str,
    actor_id: Optional[int],
) -> OwnHiringBooking:
    booking = OwnHiringBooking(
        process_id=application.process_id,
        application_id=application.id,
        kind=kind,
        booked_via=via,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        created_by=actor_id,
    )
    try:
        async with db.begin_nested():
            db.add(booking)
            await db.flush()
    except IntegrityError as exc:
        raise OwnHiringError(409, "slot_taken", MSG_SLOT_TAKEN) from exc
    return booking


async def book_teams(
    db: AsyncSession,
    application: OwnHiringApplication,
    process: OwnHiringProcess,
    *,
    start: datetime,
    via: str,
    actor_id: Optional[int],
) -> OwnHiringBooking:
    """Rezerwuje rozmowę Teams. Wołający trzyma blokadę wiersza zgłoszenia."""
    if application.stage not in BOOKABLE_STAGES:
        raise OwnHiringError(409, "wrong_stage", "Tego terminu nie można już zmienić.")
    await _assert_free(db, process, start, "teams")
    now = now_utc()
    previous = await release_active(db, application, now)
    settings = merged_settings(process)
    booking = await _insert(
        db,
        application,
        kind="teams",
        start=start,
        minutes=int(settings["slot_minutes"]),
        via=via,
        actor_id=actor_id,
    )
    set_stage(application, "teams", now)
    application.callback_at = None
    log_event(
        db, application, "booked", actor_id=actor_id, via=via, start=start.isoformat()
    )
    await db.commit()
    await cancel_in_calendar(db, process, previous)
    await sync_to_calendar(db, booking.id)
    return booking


async def create_office(
    db: AsyncSession,
    ctx: Context,
    application: OwnHiringApplication,
    start: datetime,
    now: datetime,
) -> OwnHiringBooking:
    if start <= now:
        raise OwnHiringError(
            422, "office_start_past", "Termin w biurze musi być w przyszłości."
        )
    settings = merged_settings(ctx.process)
    booking = await _insert(
        db,
        application,
        kind="office",
        start=start,
        minutes=int(settings["office_minutes"]),
        via="owner",
        actor_id=ctx.user.id,
    )
    set_stage(application, "office", now)
    log_event(
        db, application, "office_booked", actor_id=ctx.user.id, start=start.isoformat()
    )
    return booking


async def book_from_queue(
    db: AsyncSession, ctx: Context, application_id: int, *, start: datetime
) -> None:
    application = await db.scalar(
        select(OwnHiringApplication)
        .where(
            OwnHiringApplication.id == application_id,
            OwnHiringApplication.process_id == ctx.process.id,
        )
        .with_for_update()
    )
    if application is None:
        raise OwnHiringError(404, "not_found", "Nie ma takiej osoby w tym procesie.")
    via = "assistant" if ctx.role == "assistant" else "owner"
    await book_teams(
        db, application, ctx.process, start=start, via=via, actor_id=ctx.user.id
    )


async def sync_to_calendar(db: AsyncSession, booking_id: int) -> None:
    """Zakłada spotkanie. Nigdy nie rzuca: termin jest już zapisany, pętla ponowi."""
    booking = await db.get(OwnHiringBooking, booking_id)
    if booking is None or booking.status != "active" or booking.graph_event_id:
        return
    process = await db.get(OwnHiringProcess, booking.process_id)
    application = await db.get(OwnHiringApplication, booking.application_id)
    if process is None or application is None:
        return
    candidate = await db.get(Candidate, application.candidate_id)
    owner = await db.get(User, process.owner_user_id)
    if candidate is None or owner is None:
        return
    booking.sync_attempts += 1
    try:
        if not prep_meetings.app_only_ready():
            raise RuntimeError("teams app-only not configured")
        payload = _meeting_payload(process, application, candidate, booking, owner)
        created = await teams_prep_graph.create_event(owner.email, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "own_hiring.calendar_sync_failed booking=%s error=%s",
            booking.id,
            type(exc).__name__,
        )
        booking.sync_status = "failed"
        await notify(
            db,
            user_id=process.owner_user_id,
            title="Nie udało się założyć spotkania",
            message="Termin jest zapisany. NEXUS ponowi założenie spotkania w kalendarzu.",
            entity_type=ENTITY_APPLICATION,
            entity_id=application.id,
        )
        await db.commit()
        return
    booking.graph_event_id = created.graph_event_id
    booking.join_url = created.join_url
    booking.sync_status = "ok"
    await db.commit()


def _meeting_payload(
    process: OwnHiringProcess,
    application: OwnHiringApplication,
    candidate: Candidate,
    booking: OwnHiringBooking,
    owner: User,
) -> dict[str, Any]:
    name = " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()
    attendees = [candidate.email] if candidate.email else []
    token = current_token(application)
    online = booking.kind == "teams"
    address = str(merged_settings(process).get("office_address") or "")
    title = (
        f"{'Rozmowa Teams' if online else 'Rozmowa w biurze'}: {process.title}, {name}"
    )
    description = (
        mail_text.meeting_description(
            role_title=process.title, link=public_link(token) if token else ""
        )
        if online
        else mail_text.office_description(role_title=process.title, address=address)
    )
    payload = _build_event_payload(
        title=title,
        description=description,
        start=booking.start_at,
        end=booking.end_at,
        attendee_emails=attendees,
        want_teams=online,
        transaction_id=event_transaction_id(
            owner_user_id=owner.id,
            title=title,
            start=booking.start_at,
            end=booking.end_at,
            attendee_emails=attendees,
            intent_id=f"own-hiring|{booking.id}",
        ),
    )
    if not online and address:
        payload["location"] = {"displayName": address}
    return payload


# ── Strona publiczna ───────────────────────────────────────────────


async def load_public(
    db: AsyncSession, token: str, *, lock: bool = False
) -> tuple[OwnHiringApplication, OwnHiringProcess]:
    query = select(OwnHiringApplication).where(
        OwnHiringApplication.token_sha256 == token_digest(token)
    )
    if lock:
        query = query.with_for_update()
    application = await db.scalar(query)
    if application is None:
        raise OwnHiringError(404, "not_found", "Ten link jest nieprawidłowy.")
    process = await db.get(OwnHiringProcess, application.process_id)
    expired = application.token_expires_at is not None and (
        application.token_expires_at <= now_utc()
    )
    if process is None or not process.is_active or expired:
        raise OwnHiringError(410, "expired", "Ten link wygasł.")
    return application, process


async def _active(db: AsyncSession, application_id: int) -> Optional[OwnHiringBooking]:
    return await db.scalar(
        select(OwnHiringBooking)
        .where(
            OwnHiringBooking.application_id == application_id,
            OwnHiringBooking.status == "active",
        )
        .limit(1)
    )


async def public_view(db: AsyncSession, token: str) -> dict[str, Any]:
    """Odpowiedź publiczna z jawnej listy pól, bez danych osoby."""
    application, process = await load_public(db, token)
    owner = await db.get(User, process.owner_user_id)
    settings = merged_settings(process)
    booking = await _active(db, application.id)
    if application.stage == "closed":
        state = "closed"
    elif application.stage in ("office", "contract", "signed"):
        state = "finished"
    elif booking is not None:
        state = "booked"
    else:
        state = "open"
    days: list[dict[str, Any]] = []
    calendar_available = True
    if state in ("open", "booked"):
        slots = await free_slots(db, process, kind="teams")
        calendar_available = slots is not None
        days = group_by_day(slots or [])
    return {
        "state": state,
        "role_title": process.title,
        "owner_name": owner.name if owner else "",
        "minutes": int(settings["slot_minutes"]),
        "calendar_available": calendar_available,
        "days": days,
        "booking": (
            {
                "start": booking.start_at,
                "end": booking.end_at,
                "join_url": booking.join_url,
            }
            if booking is not None
            else None
        ),
    }


async def public_book(db: AsyncSession, token: str, start: datetime) -> dict[str, Any]:
    application, process = await load_public(db, token, lock=True)
    was_booked = application.stage == "teams"
    await book_teams(db, application, process, start=start, via="link", actor_id=None)
    await notify(
        db,
        user_id=process.owner_user_id,
        title="Zmieniony termin rozmowy" if was_booked else "Kandydat wybrał termin",
        message=mail_text.when_label(start),
        entity_type=ENTITY_APPLICATION,
        entity_id=application.id,
    )
    await db.commit()
    return await public_view(db, token)


async def public_cancel(db: AsyncSession, token: str) -> dict[str, Any]:
    application, process = await load_public(db, token, lock=True)
    if application.stage != "teams":
        raise OwnHiringError(409, "wrong_stage", "Nie ma terminu do odwołania.")
    now = now_utc()
    released = await release_active(db, application, now)
    set_stage(application, "no_response", now)
    log_event(db, application, "cancelled_by_candidate")
    await notify(
        db,
        user_id=process.owner_user_id,
        title="Kandydat odwołał termin",
        message=process.title,
        entity_type=ENTITY_APPLICATION,
        entity_id=application.id,
    )
    await db.commit()
    await cancel_in_calendar(db, process, released)
    return await public_view(db, token)


async def public_no_fit(
    db: AsyncSession, token: str, note: Optional[str]
) -> dict[str, Any]:
    application, process = await load_public(db, token, lock=True)
    if application.stage not in ("invited", "no_response", "assistant"):
        raise OwnHiringError(409, "wrong_stage", "Tego kroku nie można już wykonać.")
    now = now_utc()
    application.replied_at = now
    if application.stage == "invited":
        set_stage(application, "no_response", now)
    log_event(db, application, "no_slot_fits", note=(note or "")[:500])
    await notify(
        db,
        user_id=process.owner_user_id,
        title="Żaden termin nie pasuje kandydatowi",
        message=(note or process.title)[:200],
        entity_type=ENTITY_APPLICATION,
        entity_id=application.id,
    )
    await db.commit()
    return await public_view(db, token)


async def public_withdraw(db: AsyncSession, token: str) -> dict[str, Any]:
    application, process = await load_public(db, token, lock=True)
    if application.stage in ("signed", "closed"):
        raise OwnHiringError(409, "wrong_stage", "Tego kroku nie można już wykonać.")
    now = now_utc()
    released = await release_active(db, application, now)
    close(application, "withdrawn", now)
    log_event(db, application, "withdrawn_by_candidate")
    await notify(
        db,
        user_id=process.owner_user_id,
        title="Kandydat zrezygnował",
        message=process.title,
        entity_type=ENTITY_APPLICATION,
        entity_id=application.id,
    )
    await db.commit()
    await cancel_in_calendar(db, process, released)
    return await public_view(db, token)
