"""Zmiany cudzego wniosku przez przełożonego i Kadry (Compass ``updateTeamLeave``).

* ``edit_request`` — rodzaj, daty, pół dnia i zastępca wniosku oczekującego
  albo zatwierdzonego. Dni i pula liczą się tą samą drogą co przy złożeniu
  (``requested_days`` → ``plan_days`` → ``leave_request_days``), reguły formy
  (``validate_shape``) i kolizje też. Zatwierdzony wniosek przesuwa godziny
  w „Moim miesiącu” (``time_hooks``) i operacje Microsoft 365
  (``leave_m365.plan_edit``: stara autoodpowiedź zdjęta, nowa ustawiona,
  wydarzenie przesunięte, reguła przekierowania zamknięta albo przepięta na
  nowe daty). Własny tekst autoodpowiedzi zostaje; zgoda na przekierowanie
  zostaje tylko przy tym samym zastępcy — zgodę osoba dała na konkretną osobę,
  więc zmiana albo usunięcie zastępcy ją zdejmuje (powiadomienie mówi, że może
  ją włączyć ponownie). Zmiana idzie pod blokadą wiersza wniosku — równoległa
  akceptacja albo anulowanie nie rozjedzie dni i statusu.
* ``forward_off_by_hr`` — Kadry (i admin) wyłączają przekierowanie poczty
  cudzego wniosku z powodem zapisanym w śladzie; regułę zamyka kolejka M365.
  Włączyć przekierowanie może dalej tylko sama osoba.

Kto zmienia: ta sama reguła co przy decyzji (``leave_service._decision_scope``:
przełożony, head pionu osoby bez przełożonego, Kadry, admin — nikt własnego
wniosku, zastępca nieobecnego przełożonego nie). Zgłoszenie z B2B i zlecenia
(D5) zmieniają tylko Kadry i admin — dla koordynatora zmiana terminu byłaby
decyzją o cudzej nieobecności, której D5 mu nie daje.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import leave_service as core
from app.services.hr.calendar import load_calendar, years_between
from app.services.hr.employment_terms import reports_absence
from app.services.hr.leave_balance import pools_for
from app.services.hr.leave_m365 import LeaveSnapshot, plan_edit
from app.services.hr.leave_policy import (
    ACTIVE_DAY_UNIQUE,
    LeavePolicyError,
    actor_of,
    plan_days,
    requested_days,
    validate_shape,
)
from app.services.hr.leave_recipients import (
    LINK_CALENDAR,
    LINK_SELF_LEAVE,
    audit_request,
    format_range,
    notify,
    report_payroll_locked,
)
from app.services.hr.m365 import outbox

#: Pole nie przyszło w żądaniu (``None`` znaczy „wyczyść” — pół dnia, zastępca).
UNSET: Any = object()

FORWARD_REASON_MIN = 3
FORWARD_REASON_MAX = 500
REPORT_EDIT_FORBIDDEN = (
    "Zgłoszenie osoby na B2B albo zleceniu zmieniają ona sama (anulowanie "
    "i nowe zgłoszenie) albo Kadry — koordynator może zgłosić kolizję."
)
FORWARD_OFF_FORBIDDEN = "Przekierowanie cudzej poczty wyłączają Kadry."


@dataclass(frozen=True)
class LeaveChanges:
    leave_type: Any = UNSET
    start_date: Any = UNSET
    end_date: Any = UNSET
    half_day: Any = UNSET
    substitute_user_id: Any = UNSET


def _pick(value: Any, current: Any) -> Any:
    return current if value is UNSET else value


async def _edit_revision(db: AsyncSession, request_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count(HrM365Operation.id)).where(
            HrM365Operation.leave_request_id == request_id
        )
    )
    return int(count or 0) + 1


async def edit_request(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    changes: LeaveChanges,
    today: date,
) -> core.LeaveOutcome:
    request, subject, profile, _ = await core._decision_scope(
        db, actor, request_id, cover_on=None
    )
    if request.status not in ("pending", "approved"):
        raise core.LeaveConflict("Ten wniosek jest już zamknięty — odśwież listę.")
    form = profile.employment_type if profile else None
    if reports_absence(form) and not actor_of(actor).sees_everyone:
        raise core.LeaveForbidden(REPORT_EDIT_FORBIDDEN)
    if profile is None:
        raise core.LeaveNotFound(request_id)
    # Blokady PRZED odczytem wartości: równoległa edycja tego wniosku czeka,
    # a potem liczymy z jej wyniku (wcześniej druga edycja zapisywała stare
    # daty i gubiła zmianę pierwszej; audyt 19.10.2026).
    await db.execute(
        select(EmployeeProfile.id)
        .where(EmployeeProfile.user_id == request.user_id)
        .with_for_update()
    )
    # Wiersz wniosku pod blokadą: równoległa akceptacja albo anulowanie
    # (warunkowy UPDATE) czeka na tę zmianę albo ją wyprzedza — wtedy 409.
    seen_status = request.status
    await _lock_request(db, request.id)
    if request.status != seen_status:
        raise core.LeaveConflict(
            "Ten wniosek zmienił się w międzyczasie — odśwież listę."
        )

    leave_type = _pick(changes.leave_type, request.leave_type)
    start = _pick(changes.start_date, request.start_date)
    end = _pick(changes.end_date, request.end_date)
    half_day = _pick(changes.half_day, request.half_day)
    if half_day is not None and start != end:
        # Pół dnia ma sens tylko przy jednym dniu (jak w Compassie): zmiana dat
        # na kilka dni zdejmuje „pół dnia”, zamiast odrzucać zmianę.
        half_day = None if changes.half_day is UNSET else half_day
    substitute_id = _pick(changes.substitute_user_id, request.substitute_user_id)
    before_state = {
        "leave_type": request.leave_type,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "half_day": request.half_day,
        "substitute_user_id": request.substitute_user_id,
    }
    after_state = {
        "leave_type": leave_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "half_day": half_day,
        "substitute_user_id": substitute_id,
    }
    if before_state == after_state:
        return core.LeaveOutcome(request)

    validate_shape(
        leave_type=leave_type,
        start=start,
        end=end,
        half_day=half_day,
        employment_type=form,
        for_self=False,
    )
    calendar = await load_calendar(db, start, end)
    days = requested_days(calendar, start, end, half_day)
    clash = await db.scalar(
        select(LeaveRequest)
        .where(
            LeaveRequest.user_id == request.user_id,
            LeaveRequest.id != request.id,
            LeaveRequest.status.in_(("pending", "approved")),
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
        .order_by(LeaveRequest.start_date)
        .limit(1)
    )
    if clash is not None:
        raise core.LeaveConflict(core._overlap_message(clash, for_self=False))
    approved = request.status == "approved"
    if approved and reports_absence(form):
        refusal = await core._sent_timesheet_refusal(
            db,
            user_id=request.user_id,
            employment_type=form,
            days=days,
            lock=True,
        )
        if refusal is not None:
            raise core.LeaveConflict(refusal)
    pools = await pools_for(
        db,
        request.user_id,
        years_between(start, end),
        exclude_request_id=request.id,
    )
    plan = plan_days(
        leave_type=leave_type, employment_type=form, days=days, pools=pools
    )
    if substitute_id != request.substitute_user_id:
        await core._validate_substitute(
            db, subject_id=request.user_id, substitute_id=substitute_id
        )
    before_consent = request.forward_mail_consent
    # Zgodę osoba dała na konkretnego zastępcę: inny zastępca albo brak
    # zastępcy ją zdejmuje — włączyć z powrotem może tylko sama osoba.
    consent = before_consent and substitute_id == request.substitute_user_id

    before = await core._snapshot(db, request) if approved else None
    old_days = await core._request_days(db, request.id)
    try:
        async with db.begin_nested():
            await db.execute(
                delete(LeaveRequestDay).where(
                    LeaveRequestDay.leave_request_id == request.id
                )
            )
            request.leave_type = leave_type
            request.start_date = start
            request.end_date = end
            request.half_day = half_day
            request.substitute_user_id = substitute_id
            request.forward_mail_consent = consent
            request.paid_days = plan.paid
            request.unpaid_days = plan.unpaid
            await db.flush()
            db.add_all(
                LeaveRequestDay(
                    leave_request_id=request.id,
                    user_id=request.user_id,
                    day=item.day,
                    fraction=item.fraction,
                    paid=item.paid,
                    active=True,
                )
                for item in plan.days
            )
            await db.flush()
    except IntegrityError as exc:
        if ACTIVE_DAY_UNIQUE in str(exc.orig):
            raise core.LeaveConflict(
                "Ten okres nakłada się na inny wniosek — odśwież listę i sprawdź daty."
            ) from exc
        raise
    await db.refresh(request)

    changed = sorted(
        key for key in after_state if after_state[key] != before_state[key]
    )
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action="leave_edited",
        extra={
            "changed": changed,
            "before": before_state,
            "days": f"{plan.total:.1f}",
            **(
                {"forward_consent_dropped": True}
                if before_consent and not consent
                else {}
            ),
        },
    )
    span = format_range(start, end)
    await notify(
        db,
        [subject.id],
        exclude={actor.id},
        title="Zmieniono Twoje zgłoszenie"
        if reports_absence(form)
        else "Zmieniono Twój wniosek",
        message=f"{span} — zmiana: {actor.name}."
        + (
            " Przekierowanie poczty do zastępcy wyłączone — możesz je włączyć"
            " przy wniosku w „Mój czas”."
            if before_consent and not consent
            else ""
        ),
        ntype=NotificationType.hr_leave_decided,
        link=LINK_SELF_LEAVE,
    )
    locked: tuple[str, ...] = ()
    if approved:
        if (
            substitute_id is not None
            and substitute_id != before_state["substitute_user_id"]
            and end >= today
        ):
            await notify(
                db,
                [substitute_id],
                exclude={actor.id},
                title="Zastępstwo",
                message=f"Zastępujesz: {subject.name}, {span}.",
                ntype=NotificationType.hr_leave_substitute,
                link=LINK_CALENDAR,
            )
        await _enqueue_edit(db, request, before, today=today)  # type: ignore[arg-type]
        from app.services.hr import time_hooks

        new_days = [item.day for item in plan.days]
        hooked = await time_hooks.on_leave_approved(db, request.user_id, new_days)
        removed = sorted(set(old_days) - set(new_days))
        cancelled = (
            await time_hooks.on_leave_cancelled(db, request.user_id, removed)
            if removed
            else {"locked_conflicts": [], "sent_changed": []}
        )
        await core.report_sent_timesheet_changed(
            db,
            request=request,
            subject=subject,
            actor_id=actor.id,
            months=[*hooked["sent_changed"], *cancelled["sent_changed"]],
        )
        locked = await report_payroll_locked(
            db,
            request=request,
            subject=subject,
            actor_id=actor.id,
            months=[*hooked["locked_conflicts"], *cancelled["locked_conflicts"]],
            event="edited",
        )
    return core.LeaveOutcome(request, locked)


async def _lock_request(
    db: AsyncSession, request_id: uuid.UUID
) -> Optional[LeaveRequest]:
    """Wniosek ``FOR UPDATE`` ze świeżym stanem z bazy (nie z mapy tożsamości)."""

    return await db.scalar(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _enqueue_edit(
    db: AsyncSession, request: LeaveRequest, before: LeaveSnapshot, *, today: date
) -> None:
    after = await core._snapshot(db, request)
    revision = await _edit_revision(db, request.id)
    for op in plan_edit(before, after, today=today, revision=revision):
        if request.source == core.OUTLOOK_SOURCE and not op.kind.startswith("forward_"):
            continue  # wniosek z Outlooka: osoba ma własną autoodpowiedź
        await outbox.enqueue(
            db,
            user_id=request.user_id,
            kind=op.kind,
            dedupe_key=op.dedupe_key,
            payload=op.payload,
            leave_request_id=request.id,
        )


async def forward_off_by_hr(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    reason: str,
    today: date,
) -> LeaveRequest:
    """Kadry wyłączają przekierowanie cudzego wniosku; powód idzie do śladu."""

    if not actor_of(actor).sees_everyone:
        raise core.LeaveForbidden(FORWARD_OFF_FORBIDDEN)
    text = (reason or "").strip()
    if len(text) < FORWARD_REASON_MIN:
        raise LeavePolicyError(
            "Podaj powód wyłączenia przekierowania — zostanie w historii wniosku."
        )
    if len(text) > FORWARD_REASON_MAX:
        raise LeavePolicyError(f"Powód może mieć najwyżej {FORWARD_REASON_MAX} znaków.")
    request = await _lock_request(db, request_id)
    if request is None:
        raise core.LeaveNotFound(request_id)
    if request.user_id == actor.id:
        raise core.LeaveForbidden(
            "Własne przekierowanie wyłączasz w „Mój czas” przy wniosku."
        )
    if not request.forward_mail_consent:
        raise core.LeaveConflict("To przekierowanie jest już wyłączone.")
    request.forward_mail_consent = False
    await db.flush()
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action="forward_consent_off",
        extra={"by": "people_admin", "reason": text},
    )
    if request.status == "approved":
        snapshot = await core._snapshot(db, request)
        revision = await core._forward_revision(db, request.id)
        for op in core.plan_operations(
            "forward_off", snapshot, today=today, revision=revision
        ):
            await outbox.enqueue(
                db,
                user_id=request.user_id,
                kind=op.kind,
                dedupe_key=op.dedupe_key,
                payload=op.payload,
                leave_request_id=request.id,
            )
    await notify(
        db,
        [request.user_id],
        exclude={actor.id},
        title="Przekierowanie poczty wyłączone",
        message=(
            f"{format_range(request.start_date, request.end_date)} — Kadry "
            "wyłączyły przekierowanie poczty do zastępcy. Szczegóły u Kadr."
        ),
        ntype=NotificationType.hr_leave_decided,
        link=LINK_SELF_LEAVE,
    )
    return request


__all__ = [
    "UNSET",
    "LeaveChanges",
    "edit_request",
    "forward_off_by_hr",
]
