"""Przejścia timesheetu i powiadomienia.

* szkic → wysłany (co najmniej jeden wpis),
* wysłany → zaakceptowany (zapis ``pdf_hash``),
* wysłany → szkic ze zwrotem (``return_note``; bez martwego ``rejected``),
* zaakceptowany → wysłany (cofnięcie akceptacji — wiedzą o tym Płace).

Każde przejście to warunkowy UPDATE pod blokadą wiersza — drugi akceptujący
dostaje 409, a nie nadpisuje decyzji. ``payroll_locked`` blokuje wszystko.
Nikt nie akceptuje własnego timesheetu (pilnuje też CHECK w bazie).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.notification import NotificationType
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import audit, people
from app.services.hr.time_access import (
    Actor,
    approval_recipients,
    users_with_permission,
)
from app.services.hr.time_entries import (
    CHANGED_DETAIL,
    TimeConflict,
    TimeError,
    TimeForbidden,
    assert_not_locked,
    entries_of,
    hash_of,
    lock_timesheet,
    sync_leave_paid,
)

logger = logging.getLogger(__name__)

MONTH_NAMES = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
MAX_RETURN_NOTE = 2000


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def my_month_link(year: int, month: int) -> str:
    return f"/my-time?tab=month&year={year}&month={month}"


def approvals_link(year: int, month: int, user_id: int) -> str:
    return f"/people/approvals?kind=timesheet&year={year}&month={month}&user={user_id}"


def payroll_link(year: int, month: int) -> str:
    # Trasa miesiąca płac to `/people/payroll/RRRR-MM` (lista miesięcy parametrów nie czyta).
    return f"/people/payroll/{year}-{month:02d}"


async def _notify(
    db: AsyncSession,
    *,
    user_ids: list[int],
    title: str,
    message: str,
    ntype: NotificationType,
    link: str,
) -> int:
    from app.services.notification_triggers import emit

    sent = 0
    for user_id in dict.fromkeys(user_ids):
        try:
            async with db.begin_nested():
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=ntype,
                    related_entity_type="timesheet",
                    # Bez id encji: dedup dobowy połknąłby drugą decyzję tego dnia
                    # (zwrot rano, akceptacja po poprawce).
                    related_entity_id=None,
                    link=link,
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
            logger.exception("[hr_time] powiadomienie nie wyszło user=%s", user_id)
    return sent


async def _name(db: AsyncSession, user_id: int) -> str:
    return await db.scalar(select(User.name).where(User.id == user_id)) or "Pracownik"


async def _locked_subject(
    db: AsyncSession, timesheet_id: int, actor: Actor, *, deciding: bool
) -> Timesheet:
    timesheet = await lock_timesheet(db, timesheet_id)
    if deciding:
        if timesheet.user_id == actor.user_id:
            raise TimeForbidden("Własnego timesheetu nie akceptuje się samemu.")
        subject = await people.profile_of(db, timesheet.user_id)
        if subject is None or not actor.can_approve(subject):
            raise TimeForbidden("Decydujesz tylko o timesheetach swojego zespołu.")
    assert_not_locked(timesheet)
    return timesheet


async def submit(db: AsyncSession, *, timesheet_id: int, actor: Actor) -> Timesheet:
    timesheet = await lock_timesheet(db, timesheet_id)
    if timesheet.user_id != actor.user_id:
        raise TimeForbidden("Wysyłasz tylko własny timesheet.")
    assert_not_locked(timesheet)
    if timesheet.status != "draft":
        raise TimeConflict("Ten timesheet jest już wysłany.")
    profile = await people.profile_of(db, timesheet.user_id)
    await sync_leave_paid(
        db,
        timesheet=timesheet,
        employment_type=profile.employment_type if profile else None,
    )
    count = await db.scalar(
        select(func.count(TimesheetEntry.id)).where(
            TimesheetEntry.timesheet_id == timesheet.id
        )
    )
    if not count:
        raise TimeError("Timesheet musi mieć co najmniej jeden wpis.")
    done = await db.scalar(
        update(Timesheet)
        .where(
            Timesheet.id == timesheet.id,
            Timesheet.status == "draft",
            Timesheet.payroll_locked.is_(False),
        )
        .values(
            status="submitted",
            submitted_at=func.now(),
            return_note=None,
            returned_at=None,
        )
        .returning(Timesheet.id)
    )
    if done is None:
        raise TimeConflict(CHANGED_DETAIL)
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action="timesheet_submitted",
        details={"year": timesheet.year, "month": timesheet.month},
    )
    recipients = await approval_recipients(db, timesheet.user_id)
    who = await _name(db, timesheet.user_id)
    await _notify(
        db,
        user_ids=recipients,
        title="Timesheet do akceptacji",
        message=f"{who}: {month_label(timesheet.year, timesheet.month)}.",
        ntype=NotificationType.hr_timesheet_submitted,
        link=approvals_link(timesheet.year, timesheet.month, timesheet.user_id),
    )
    return await lock_timesheet(db, timesheet.id)


async def approve(db: AsyncSession, *, timesheet_id: int, actor: Actor) -> Timesheet:
    timesheet = await _locked_subject(db, timesheet_id, actor, deciding=True)
    if timesheet.status != "submitted":
        raise TimeConflict(
            "Timesheet został już rozpatrzony albo nie czeka na akceptację. "
            "Odśwież listę."
        )
    pdf_hash = hash_of(await entries_of(db, timesheet.id))
    done = await db.scalar(
        update(Timesheet)
        .where(
            Timesheet.id == timesheet.id,
            Timesheet.status == "submitted",
            Timesheet.payroll_locked.is_(False),
            Timesheet.user_id != actor.user_id,
        )
        .values(
            status="approved",
            approved_by=actor.user_id,
            approved_at=func.now(),
            pdf_hash=pdf_hash,
            return_note=None,
        )
        .returning(Timesheet.id)
    )
    if done is None:
        raise TimeConflict(CHANGED_DETAIL)
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action="timesheet_approved",
        details={"year": timesheet.year, "month": timesheet.month},
    )
    await _notify(
        db,
        user_ids=[timesheet.user_id],
        title="Timesheet zaakceptowany",
        message=f"Timesheet za {month_label(timesheet.year, timesheet.month)} "
        "jest zaakceptowany. PDF jest do pobrania w „Moim miesiącu”.",
        ntype=NotificationType.hr_timesheet_decided,
        link=my_month_link(timesheet.year, timesheet.month),
    )
    return await lock_timesheet(db, timesheet.id)


def clean_return_note(raw: Optional[str]) -> str:
    note = (raw or "").strip()
    if not note:
        raise TimeError("Napisz, co trzeba poprawić.")
    if len(note) > MAX_RETURN_NOTE:
        raise TimeError(f"Notatka może mieć najwyżej {MAX_RETURN_NOTE} znaków.")
    return note


async def return_for_fix(
    db: AsyncSession, *, timesheet_id: int, actor: Actor, note: str
) -> Timesheet:
    note = clean_return_note(note)
    timesheet = await _locked_subject(db, timesheet_id, actor, deciding=True)
    if timesheet.status != "submitted":
        raise TimeConflict(
            "Zwrócić można tylko timesheet, który czeka na akceptację. Odśwież listę."
        )
    done = await db.scalar(
        update(Timesheet)
        .where(
            Timesheet.id == timesheet.id,
            Timesheet.status == "submitted",
            Timesheet.payroll_locked.is_(False),
        )
        .values(
            status="draft",
            return_note=note,
            returned_at=func.now(),
            submitted_at=None,
            approved_by=None,
            approved_at=None,
            pdf_hash=None,
        )
        .returning(Timesheet.id)
    )
    if done is None:
        raise TimeConflict(CHANGED_DETAIL)
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action="timesheet_returned",
        details={"year": timesheet.year, "month": timesheet.month},
    )
    await _notify(
        db,
        user_ids=[timesheet.user_id],
        title="Timesheet zwrócony do poprawy",
        message=f"{month_label(timesheet.year, timesheet.month)}: {note[:200]}",
        ntype=NotificationType.hr_timesheet_decided,
        link=my_month_link(timesheet.year, timesheet.month),
    )
    return await lock_timesheet(db, timesheet.id)


async def revoke(db: AsyncSession, *, timesheet_id: int, actor: Actor) -> Timesheet:
    """Cofnięcie akceptacji: wraca do „wysłany”; wiedzą o tym osoba i Płace."""

    timesheet = await _locked_subject(db, timesheet_id, actor, deciding=True)
    if timesheet.status != "approved":
        raise TimeConflict("Cofnąć można tylko zaakceptowany timesheet. Odśwież listę.")
    done = await db.scalar(
        update(Timesheet)
        .where(
            Timesheet.id == timesheet.id,
            Timesheet.status == "approved",
            Timesheet.payroll_locked.is_(False),
        )
        .values(status="submitted", approved_by=None, approved_at=None, pdf_hash=None)
        .returning(Timesheet.id)
    )
    if done is None:
        raise TimeConflict(CHANGED_DETAIL)
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action="timesheet_approval_revoked",
        details={"year": timesheet.year, "month": timesheet.month},
    )
    label = month_label(timesheet.year, timesheet.month)
    who = await _name(db, timesheet.user_id)
    await _notify(
        db,
        user_ids=[timesheet.user_id],
        title="Cofnięto akceptację timesheetu",
        message=f"Timesheet za {label} wrócił do akceptującego do poprawy.",
        ntype=NotificationType.hr_timesheet_decided,
        link=my_month_link(timesheet.year, timesheet.month),
    )
    payroll = [
        user.id
        for user in await users_with_permission(db, ProductAction.payroll)
        if user.id not in (actor.user_id, timesheet.user_id)
    ]
    await _notify(
        db,
        user_ids=payroll,
        title="Cofnięto akceptację timesheetu",
        message=f"{who}: {label}. Timesheet czeka na ponowną akceptację.",
        ntype=NotificationType.hr_timesheet_decided,
        link=payroll_link(timesheet.year, timesheet.month),
    )
    return await lock_timesheet(db, timesheet.id)
