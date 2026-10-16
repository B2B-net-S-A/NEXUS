"""Wnioski urlopowe — złożenie, akceptacja, odrzucenie, anulowanie, wpis za
pracownika („Ludzie w NEXUSIE”, E1).

Reguły liczą czyste funkcje (``leave_policy``); tu jest kolejność zapisu,
powiadomienia, ślad i kolejka Microsoft 365. Każda decyzja to warunkowy
``UPDATE … WHERE status = …`` — drugi akceptujący dostaje konflikt (409),
a nie drugą decyzję. Dni wniosku (``leave_request_days.active``) zmieniają się
w tej samej transakcji co status.

Powiadomienia nie zdradzają rodzaju nieobecności ani notatki (D6) — dzwonek
osoby może zobaczyć jej zastępca, a zastępca nie należy do kręgu D6.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit, people
from app.services.hr.calendar import load_calendar, years_between
from app.services.hr.leave_balance import pools_for
from app.services.hr.leave_context import (
    busy_user_ids,
    department_absences,
    overlapping_request,
    work_in_period,
)
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.leave_policy import (
    AUTO_APPROVED_TYPES,
    HEALTH_TYPES,
    LEAVE_TYPE_LABELS,
    Actor,
    LeavePolicyError,
    can_decide,
    own_cancel_refusal,
    plan_days,
    requested_days,
    team_cancel_refusal,
    validate_shape,
)
from app.services.hr.m365 import outbox
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

LINK_SELF = "/my-time"
LINK_APPROVALS = "/people/approvals"
LINK_CALENDAR = "/people/calendar"
_ACTIVE_UNIQUE = "uq_leave_request_days_user_day_active"


class LeaveNotFound(LookupError):
    pass


class LeaveForbidden(PermissionError):
    pass


class LeaveConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class LeaveInput:
    leave_type: str
    start_date: date
    end_date: date
    half_day: Optional[str] = None
    note: Optional[str] = None
    substitute_user_id: Optional[int] = None
    forward_mail_consent: bool = False
    oof_internal_message: Optional[str] = None
    oof_external_message: Optional[str] = None


def actor_of(user: User) -> Actor:
    return Actor(
        user_id=user.id,
        is_admin=user.has_role(UserRole.admin),
        is_people_admin=has_permission(user, ProductAction.people_admin),
    )


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def format_range(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d.%m.%Y")
    if start.year == end.year:
        return f"{start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    return f"{start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}"


def days_label(value: Decimal) -> str:
    """„1 dzień”, „5 dni”, „0,5 dnia” — dni robocze w treści powiadomień."""

    if value == 1:
        return "1 dzień"
    text = f"{value.normalize():f}".replace(".", ",")
    return f"{text} dnia" if value != value.to_integral_value() else f"{text} dni"


# ── Odbiorcy ─────────────────────────────────────────────────────────────────


async def people_admin_ids(db: AsyncSession) -> list[int]:
    """Kadry (uprawnienie „Kadry” bez adminów); brak Kadr → admini."""

    from app.services.effective_access import resolve_effective_access

    users = list(await db.scalars(select(User).where(User.is_active.is_(True))))
    await resolve_effective_access(db, users)
    hr = [
        user.id
        for user in users
        if not user.has_role(UserRole.admin)
        and has_permission(user, ProductAction.people_admin)
    ]
    if hr:
        return hr
    return [user.id for user in users if user.has_role(UserRole.admin)]


async def approver_ids(
    db: AsyncSession, profile: Optional[EmployeeProfile]
) -> list[int]:
    """Kto decyduje: przełożony z kartoteki, a bez niego Kadry (albo admini)."""

    if profile is not None and profile.manager_user_id is not None:
        manager = await db.get(User, profile.manager_user_id)
        if manager is not None and manager.is_active:
            return [manager.id]
    subject_id = profile.user_id if profile is not None else None
    return [uid for uid in await people_admin_ids(db) if uid != subject_id]


async def approver_label(db: AsyncSession, profile: Optional[EmployeeProfile]) -> str:
    if profile is not None and profile.manager_user_id is not None:
        manager = await db.get(User, profile.manager_user_id)
        if manager is not None and manager.is_active:
            return manager.name
    return "Kadry"


async def _notify(
    db: AsyncSession,
    recipients: list[int],
    *,
    exclude: set[int],
    title: str,
    message: str,
    ntype: NotificationType,
    link: str,
) -> int:
    sent = 0
    for user_id in dict.fromkeys(recipients):
        if user_id in exclude:
            continue
        try:
            async with db.begin_nested():
                created = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=ntype,
                    related_entity_type="leave_request",
                    related_entity_id=None,
                    link=link,
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje decyzji
            logger.exception(
                "[hr_leave] dzwonek nie wyszedł type=%s user=%s", ntype.value, user_id
            )
    return sent


# ── Pomocnicze ────────────────────────────────────────────────────────────────


async def _subject(db: AsyncSession, user_id: int) -> tuple[User, EmployeeProfile]:
    user = await db.get(User, user_id)
    profile = await people.profile_of(db, user_id)
    if user is None or profile is None:
        raise LeaveNotFound(user_id)
    return user, profile


async def _validate_substitute(
    db: AsyncSession, *, subject_id: int, substitute_id: Optional[int]
) -> Optional[User]:
    if substitute_id is None:
        return None
    if substitute_id == subject_id:
        raise LeavePolicyError("Nie można wybrać siebie na zastępcę.")
    substitute = await db.get(User, substitute_id)
    if substitute is None or not substitute.is_active:
        raise LeavePolicyError("Wybrany zastępca nie ma aktywnego konta.")
    if not await people.has_live_profile(db, substitute_id):
        raise LeavePolicyError(
            "Zastępcą może być osoba z kartoteką pracownika w NEXUSIE."
        )
    return substitute


async def _days_total(db: AsyncSession, request_id: uuid.UUID) -> Decimal:
    total = await db.scalar(
        select(func.sum(LeaveRequestDay.fraction)).where(
            LeaveRequestDay.leave_request_id == request_id
        )
    )
    return Decimal(total or 0)


async def _snapshot(db: AsyncSession, request: LeaveRequest) -> LeaveSnapshot:
    calendar = await load_calendar(db, request.start_date, request.end_date)
    return LeaveSnapshot(
        id=str(request.id),
        user_id=request.user_id,
        start=request.start_date,
        end=request.end_date,
        half_day=request.half_day,
        total_days=await _days_total(db, request.id),
        substitute_user_id=request.substitute_user_id,
        forward_mail_consent=request.forward_mail_consent,
        oof_internal_message=request.oof_internal_message,
        oof_external_message=request.oof_external_message,
        return_on=calendar.next_working_day_after(request.end_date),
    )


async def _forward_revision(db: AsyncSession, request_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count(HrM365Operation.id)).where(
            HrM365Operation.leave_request_id == request_id,
            HrM365Operation.kind.in_(("forward_rule_open", "forward_rule_close")),
        )
    )
    return int(count or 0) + 1


async def _enqueue_m365(
    db: AsyncSession, request: LeaveRequest, event: str, *, today: date
) -> int:
    snapshot = await _snapshot(db, request)
    revision = await _forward_revision(db, request.id)
    created = 0
    for op in plan_operations(event, snapshot, today=today, revision=revision):  # type: ignore[arg-type]
        created += int(
            await outbox.enqueue(
                db,
                user_id=request.user_id,
                kind=op.kind,
                dedupe_key=op.dedupe_key,
                payload=op.payload,
                leave_request_id=request.id,
            )
        )
    return created


def _sensitivity(leave_type: str, note: Optional[str]) -> str:
    return "health" if leave_type in HEALTH_TYPES or note else "general"


def _audit(
    db: AsyncSession,
    *,
    actor_id: Optional[int],
    request: LeaveRequest,
    action: str,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=request.user_id,
        entity_type="leave_request",
        entity_id=request.id,
        action=action,
        details={
            "leave_type": request.leave_type,
            "status": request.status,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "source": request.source,
            "has_note": bool(request.note),
            **(extra or {}),
        },
        sensitivity=_sensitivity(request.leave_type, request.note),  # type: ignore[arg-type]
    )


async def _set_days_active(
    db: AsyncSession, request_id: uuid.UUID, active: bool
) -> None:
    await db.execute(
        update(LeaveRequestDay)
        .where(LeaveRequestDay.leave_request_id == request_id)
        .values(active=active)
    )


# ── Podgląd i złożenie ────────────────────────────────────────────────────────


async def preview(
    db: AsyncSession,
    *,
    subject: User,
    profile: EmployeeProfile,
    data: LeaveInput,
    for_self: bool,
) -> dict[str, Any]:
    """Podział płatne/bezpłatne i ostrzeżenia — bez zapisu.

    Błąd reguły nie jest tu 422: okno pokazuje go na żywo w ``blocking_reason``.
    """

    result: dict[str, Any] = {
        "working_days": [],
        "days_total": "0.0",
        "paid_days": "0.0",
        "unpaid_days": "0.0",
        "years": [],
        "blocking_reason": None,
        "auto_approved": data.leave_type in AUTO_APPROVED_TYPES or not for_self,
        "approver": await approver_label(db, profile),
        "department_absent": [],
        "work": {"total": 0, "by_kind": [], "items": []},
        "substitute_absent": False,
        "return_on": None,
    }
    try:
        validate_shape(
            leave_type=data.leave_type,
            start=data.start_date,
            end=data.end_date,
            half_day=data.half_day,
            employment_type=profile.employment_type,
            for_self=for_self,
        )
    except LeavePolicyError as exc:
        result["blocking_reason"] = str(exc)
        return result
    calendar = await load_calendar(db, data.start_date, data.end_date)
    days = requested_days(calendar, data.start_date, data.end_date, data.half_day)
    result["working_days"] = [day.isoformat() for day, _ in days]
    result["return_on"] = calendar.next_working_day_after(data.end_date).isoformat()
    clash = await overlapping_request(
        db, user_id=subject.id, start=data.start_date, end=data.end_date
    )
    try:
        if clash is not None:
            raise LeavePolicyError(_overlap_message(clash, for_self=for_self))
        pools = await pools_for(
            db, subject.id, years_between(data.start_date, data.end_date)
        )
        plan = plan_days(
            leave_type=data.leave_type,
            employment_type=profile.employment_type,
            days=days,
            pools=pools,
        )
        result.update(
            days_total=f"{plan.total:.1f}",
            paid_days=f"{plan.paid:.1f}",
            unpaid_days=f"{plan.unpaid:.1f}",
            years=[
                {
                    "year": split.year,
                    "requested": f"{split.requested:.1f}",
                    "paid": f"{split.paid:.1f}",
                    "unpaid": f"{split.unpaid:.1f}",
                    "has_pool": split.has_pool,
                    "remaining_before": None
                    if split.remaining_before is None
                    else f"{split.remaining_before:.1f}",
                    "remaining_after": None
                    if split.remaining_after is None
                    else f"{split.remaining_after:.1f}",
                }
                for split in plan.years
            ],
        )
    except LeavePolicyError as exc:
        result["blocking_reason"] = str(exc)
        result["days_total"] = f"{sum((f for _, f in days), Decimal('0')):.1f}"
    result["department_absent"] = await department_absences(
        db,
        user_id=subject.id,
        department=profile.department,
        start=data.start_date,
        end=data.end_date,
    )
    result["work"] = await work_in_period(
        db,
        user_id=subject.id,
        start=data.start_date,
        end=data.end_date,
        with_titles=for_self,
    )
    if data.substitute_user_id is not None:
        busy = await busy_user_ids(db, data.start_date, data.end_date)
        result["substitute_absent"] = data.substitute_user_id in busy
    return result


def _overlap_message(clash: LeaveRequest, *, for_self: bool) -> str:
    state = "zatwierdzony" if clash.status == "approved" else "oczekujący"
    who = "Masz" if for_self else "Ta osoba ma"
    return (
        f"{who} już {state} wniosek na "
        f"{format_range(clash.start_date, clash.end_date)} — "
        "wnioski nie mogą się nakładać."
    )


async def submit(
    db: AsyncSession,
    *,
    actor: User,
    subject: User,
    profile: EmployeeProfile,
    data: LeaveInput,
    on_behalf: bool,
    today: date,
) -> LeaveRequest:
    """Zapisuje wniosek. Wpis za pracownika i L4 są zatwierdzone od razu.

    Zgodę na przekierowanie poczty daje wyłącznie sama osoba: wpis za
    pracownika jej nie przenosi (Compass pozwalał przełożonemu ją włączyć).
    """

    for_self = not on_behalf
    validate_shape(
        leave_type=data.leave_type,
        start=data.start_date,
        end=data.end_date,
        half_day=data.half_day,
        employment_type=profile.employment_type,
        for_self=for_self,
    )
    calendar = await load_calendar(db, data.start_date, data.end_date)
    days = requested_days(calendar, data.start_date, data.end_date, data.half_day)
    # Wnioski jednej osoby po kolei: dwa równoległe wnioski na różne dni
    # przeszłyby oba przez limit puli liczony przed zapisem.
    await db.execute(
        select(EmployeeProfile.id)
        .where(EmployeeProfile.user_id == subject.id)
        .with_for_update()
    )
    clash = await overlapping_request(
        db, user_id=subject.id, start=data.start_date, end=data.end_date
    )
    if clash is not None:
        raise LeaveConflict(_overlap_message(clash, for_self=for_self))
    pools = await pools_for(
        db, subject.id, years_between(data.start_date, data.end_date)
    )
    plan = plan_days(
        leave_type=data.leave_type,
        employment_type=profile.employment_type,
        days=days,
        pools=pools,
    )
    substitute = await _validate_substitute(
        db, subject_id=subject.id, substitute_id=data.substitute_user_id
    )
    approved = on_behalf or data.leave_type in AUTO_APPROVED_TYPES
    now = datetime.now(timezone.utc)
    request = LeaveRequest(
        id=uuid.uuid4(),
        user_id=subject.id,
        leave_type=data.leave_type,
        status="approved" if approved else "pending",
        start_date=data.start_date,
        end_date=data.end_date,
        half_day=data.half_day,
        note=_clean(data.note),
        substitute_user_id=substitute.id if substitute else None,
        forward_mail_consent=bool(
            for_self and substitute is not None and data.forward_mail_consent
        ),
        oof_internal_message=_clean(data.oof_internal_message) if for_self else None,
        oof_external_message=_clean(data.oof_external_message) if for_self else None,
        paid_days=plan.paid,
        unpaid_days=plan.unpaid,
        decided_by=actor.id if on_behalf else None,
        decided_at=now if approved else None,
        created_by=actor.id,
        source="on_behalf" if on_behalf else "self",
    )
    try:
        async with db.begin_nested():
            db.add(request)
            await db.flush()
            db.add_all(
                LeaveRequestDay(
                    leave_request_id=request.id,
                    user_id=subject.id,
                    day=item.day,
                    fraction=item.fraction,
                    paid=item.paid,
                    active=True,
                )
                for item in plan.days
            )
            await db.flush()
    except IntegrityError as exc:
        if _ACTIVE_UNIQUE in str(exc.orig):
            raise LeaveConflict(
                "Ten okres nakłada się na inny wniosek — odśwież listę i sprawdź daty."
            ) from exc
        raise

    span = format_range(request.start_date, request.end_date)
    days_text = days_label(plan.total)
    if on_behalf:
        action = "leave_entered_on_behalf"
    elif approved:
        action = "absence_reported"
    else:
        action = "leave_requested"
    _audit(
        db,
        actor_id=actor.id,
        request=request,
        action=action,
        extra={"days": f"{plan.total:.1f}"},
    )

    if not approved:
        await _notify(
            db,
            await approver_ids(db, profile),
            exclude={subject.id},
            title="Wniosek o nieobecność do akceptacji",
            message=f"{subject.name}: {span} ({days_text}).",
            ntype=NotificationType.hr_leave_requested,
            link=LINK_APPROVALS,
        )
        return request

    if on_behalf:
        await _notify(
            db,
            [subject.id],
            exclude={actor.id},
            title="Wpisano Ci nieobecność",
            message=f"{span} — wpis: {actor.name}.",
            ntype=NotificationType.hr_leave_decided,
            link=LINK_SELF,
        )
    if data.leave_type in AUTO_APPROVED_TYPES:
        recipients = []
        if profile.manager_user_id is not None:
            recipients.append(profile.manager_user_id)
        recipients.extend(await people_admin_ids(db))
        await _notify(
            db,
            recipients,
            exclude={actor.id, subject.id},
            title="Zgłoszona nieobecność",
            message=f"{subject.name}: nieobecność {span}, zatwierdzona od razu.",
            ntype=NotificationType.hr_absence_reported,
            link=LINK_APPROVALS,
        )
    await _after_approval(db, request, subject=subject, actor=actor, today=today)
    return request


async def _after_approval(
    db: AsyncSession, request: LeaveRequest, *, subject: User, actor: User, today: date
) -> None:
    if request.substitute_user_id is not None and request.end_date >= today:
        await _notify(
            db,
            [request.substitute_user_id],
            exclude={actor.id},
            title="Zastępstwo",
            message=(
                f"Zastępujesz: {subject.name}, "
                f"{format_range(request.start_date, request.end_date)}."
            ),
            ntype=NotificationType.hr_leave_substitute,
            link=LINK_CALENDAR,
        )
    await _enqueue_m365(db, request, "approved", today=today)
    # „Mój miesiąc” (E2): godziny wpisane na pełne dni urlopu znikają, płatny
    # urlop B2B/zlecenia dostaje auto-wpisy, hash zaakceptowanego PDF-u się
    # przelicza. Zamknięte w płacach miesiące są tylko raportowane.
    from app.services.hr import time_hooks

    await time_hooks.on_leave_approved(
        db, request.user_id, await _request_days(db, request.id)
    )


async def _request_days(db: AsyncSession, request_id: uuid.UUID) -> list[date]:
    return list(
        await db.scalars(
            select(LeaveRequestDay.day).where(
                LeaveRequestDay.leave_request_id == request_id
            )
        )
    )


# ── Decyzje ───────────────────────────────────────────────────────────────────


async def _decidable(
    db: AsyncSession, actor: User, request_id: uuid.UUID
) -> tuple[LeaveRequest, User, Optional[EmployeeProfile]]:
    request = await db.get(LeaveRequest, request_id)
    if request is None:
        raise LeaveNotFound(request_id)
    profile = await people.profile_of(db, request.user_id)
    if request.user_id == actor.id:
        raise LeaveForbidden("Nie możesz decydować o własnym wniosku.")
    if not can_decide(
        actor_of(actor),
        subject_user_id=request.user_id,
        subject_manager_id=profile.manager_user_id if profile else None,
    ):
        # Wniosek spoza zakresu wygląda jak nieistniejący (bez wycieku dat).
        raise LeaveNotFound(request_id)
    subject = await db.get(User, request.user_id)
    assert subject is not None
    return request, subject, profile


async def _conditional_status(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    from_statuses: tuple[str, ...],
    values: dict[str, Any],
    extra_where: tuple = (),
) -> bool:
    result = await db.execute(
        update(LeaveRequest)
        .where(
            LeaveRequest.id == request_id,
            LeaveRequest.status.in_(from_statuses),
            *extra_where,
        )
        .values(**values, updated_at=func.now())
        .returning(LeaveRequest.id)
    )
    return result.scalar_one_or_none() is not None


async def approve(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    note: Optional[str],
    today: date,
) -> LeaveRequest:
    request, subject, _ = await _decidable(db, actor, request_id)
    changed = await _conditional_status(
        db,
        request_id,
        from_statuses=("pending",),
        values={
            "status": "approved",
            "decided_by": actor.id,
            "decided_at": datetime.now(timezone.utc),
            "decision_note": _clean(note),
        },
    )
    if not changed:
        raise LeaveConflict("Ten wniosek ma już decyzję — odśwież listę.")
    await db.refresh(request)
    _audit(db, actor_id=actor.id, request=request, action="leave_approved")
    await _notify(
        db,
        [subject.id],
        exclude={actor.id},
        title="Wniosek zaakceptowany",
        message=f"{format_range(request.start_date, request.end_date)} — akceptacja: {actor.name}.",
        ntype=NotificationType.hr_leave_decided,
        link=LINK_SELF,
    )
    await _after_approval(db, request, subject=subject, actor=actor, today=today)
    return request


async def reject(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, note: str
) -> LeaveRequest:
    reason = _clean(note)
    if reason is None or len(reason) < 3:
        raise LeavePolicyError(
            "Podaj powód odrzucenia — osoba zobaczy go przy wniosku."
        )
    request, subject, _ = await _decidable(db, actor, request_id)
    changed = await _conditional_status(
        db,
        request_id,
        from_statuses=("pending",),
        values={
            "status": "rejected",
            "decided_by": actor.id,
            "decided_at": datetime.now(timezone.utc),
            "decision_note": reason,
        },
    )
    if not changed:
        raise LeaveConflict("Ten wniosek ma już decyzję — odśwież listę.")
    await _set_days_active(db, request_id, False)
    await db.refresh(request)
    _audit(db, actor_id=actor.id, request=request, action="leave_rejected")
    await _notify(
        db,
        [subject.id],
        exclude={actor.id},
        title="Wniosek odrzucony",
        message=(
            f"{format_range(request.start_date, request.end_date)} — "
            "powód znajdziesz w „Mój czas”."
        ),
        ntype=NotificationType.hr_leave_decided,
        link=LINK_SELF,
    )
    return request


async def _after_cancel(
    db: AsyncSession,
    request: LeaveRequest,
    *,
    previous_status: str,
    actor: User,
    subject: User,
    profile: Optional[EmployeeProfile],
    today: date,
) -> None:
    await _set_days_active(db, request.id, False)
    await db.refresh(request)
    _audit(
        db,
        actor_id=actor.id,
        request=request,
        action="leave_cancelled",
        extra={"previous_status": previous_status},
    )
    recipients = [subject.id, *await approver_ids(db, profile)]
    if previous_status == "approved" and request.substitute_user_id is not None:
        recipients.append(request.substitute_user_id)
    await _notify(
        db,
        recipients,
        exclude={actor.id},
        title="Nieobecność anulowana",
        message=(
            f"{subject.name}: {format_range(request.start_date, request.end_date)} "
            f"— anulowanie: {actor.name}."
        ),
        ntype=NotificationType.hr_leave_cancelled,
        link=LINK_CALENDAR,
    )
    if previous_status == "approved":
        await _enqueue_m365(db, request, "cancelled", today=today)
        from app.services.hr import time_hooks

        await time_hooks.on_leave_cancelled(
            db, request.user_id, await _request_days(db, request.id)
        )


async def cancel_own(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, today: date
) -> LeaveRequest:
    request = await db.get(LeaveRequest, request_id)
    if request is None or request.user_id != actor.id:
        raise LeaveNotFound(request_id)
    refusal = own_cancel_refusal(
        status=request.status, start=request.start_date, today=today
    )
    if refusal is not None:
        if request.status in ("pending", "approved"):
            raise LeavePolicyError(refusal)
        raise LeaveConflict(refusal)
    previous = request.status
    extra = (LeaveRequest.start_date > today,) if previous == "approved" else ()
    changed = await _conditional_status(
        db,
        request_id,
        from_statuses=(previous,),
        values={"status": "cancelled"},
        extra_where=extra,
    )
    if not changed:
        raise LeaveConflict("Ten wniosek zmienił się w międzyczasie — odśwież listę.")
    profile = await people.profile_of(db, actor.id)
    await _after_cancel(
        db,
        request,
        previous_status=previous,
        actor=actor,
        subject=actor,
        profile=profile,
        today=today,
    )
    return request


async def cancel_as_approver(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, today: date
) -> LeaveRequest:
    request, subject, profile = await _decidable(db, actor, request_id)
    refusal = team_cancel_refusal(status=request.status)
    if refusal is not None:
        raise LeaveConflict(refusal)
    previous = request.status
    changed = await _conditional_status(
        db,
        request_id,
        from_statuses=(previous,),
        values={"status": "cancelled"},
    )
    if not changed:
        raise LeaveConflict("Ten wniosek zmienił się w międzyczasie — odśwież listę.")
    await _after_cancel(
        db,
        request,
        previous_status=previous,
        actor=actor,
        subject=subject,
        profile=profile,
        today=today,
    )
    return request


async def set_forward_consent(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    consent: bool,
    today: date,
) -> LeaveRequest:
    """Zgoda na przekierowanie poczty — wyłącznie właściciel wniosku."""

    request = await db.get(LeaveRequest, request_id)
    if request is None or request.user_id != actor.id:
        raise LeaveNotFound(request_id)
    if request.status not in ("pending", "approved"):
        raise LeaveConflict("Ten wniosek jest już zamknięty.")
    if request.end_date < today:
        raise LeavePolicyError("Ta nieobecność już minęła.")
    if consent and request.substitute_user_id is None:
        raise LeavePolicyError("Przekierowanie wymaga zastępcy we wniosku.")
    if request.forward_mail_consent == consent:
        return request
    request.forward_mail_consent = consent
    await db.flush()
    _audit(
        db,
        actor_id=actor.id,
        request=request,
        action="forward_consent_on" if consent else "forward_consent_off",
    )
    if request.status == "approved":
        snapshot = await _snapshot(db, request)
        revision = await _forward_revision(db, request.id)
        event = "forward_on" if consent else "forward_off"
        for op in plan_operations(event, snapshot, today=today, revision=revision):
            await outbox.enqueue(
                db,
                user_id=request.user_id,
                kind=op.kind,
                dedupe_key=op.dedupe_key,
                payload=op.payload,
                leave_request_id=request.id,
            )
    return request


# ── Odczyty ───────────────────────────────────────────────────────────────────


async def names_of(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {uid for uid in ids if uid}
    if not ids:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    )


async def _totals(
    db: AsyncSession, request_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    if not request_ids:
        return {}
    rows = await db.execute(
        select(LeaveRequestDay.leave_request_id, func.sum(LeaveRequestDay.fraction))
        .where(LeaveRequestDay.leave_request_id.in_(request_ids))
        .group_by(LeaveRequestDay.leave_request_id)
    )
    return {rid: Decimal(total or 0) for rid, total in rows.all()}


async def serialize(
    db: AsyncSession,
    requests: list[LeaveRequest],
    *,
    viewer: User,
    today: date,
) -> list[dict[str, Any]]:
    """Pełny wiersz wniosku — tylko dla kręgu D6 (osoba, przełożony, Kadry)."""

    names = await names_of(
        db,
        {r.user_id for r in requests}
        | {r.substitute_user_id for r in requests if r.substitute_user_id}
        | {r.decided_by for r in requests if r.decided_by},
    )
    totals = await _totals(db, [r.id for r in requests])
    items = []
    for r in requests:
        own = r.user_id == viewer.id
        items.append(
            {
                "id": str(r.id),
                "user_id": r.user_id,
                "user_name": names.get(r.user_id),
                "leave_type": r.leave_type,
                "leave_type_label": LEAVE_TYPE_LABELS.get(r.leave_type, r.leave_type),
                "status": r.status,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "half_day": r.half_day,
                "days_total": f"{totals.get(r.id, Decimal('0')):.1f}",
                "paid_days": f"{r.paid_days:.1f}",
                "unpaid_days": f"{r.unpaid_days:.1f}",
                "note": r.note,
                "substitute_user_id": r.substitute_user_id,
                "substitute_name": names.get(r.substitute_user_id)
                if r.substitute_user_id
                else None,
                "forward_mail_consent": r.forward_mail_consent,
                "oof_internal_message": r.oof_internal_message if own else None,
                "oof_external_message": r.oof_external_message if own else None,
                "decided_by_name": names.get(r.decided_by) if r.decided_by else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "decision_note": r.decision_note,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "can_cancel": own
                and own_cancel_refusal(status=r.status, start=r.start_date, today=today)
                is None,
            }
        )
    return items


async def my_requests(
    db: AsyncSession, *, user: User, today: date, limit: int = 200
) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.user_id == user.id)
            .order_by(LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc())
            .limit(limit)
        )
    )
    return await serialize(db, rows, viewer=user, today=today)


async def scope_user_ids(db: AsyncSession, actor: User) -> Optional[set[int]]:
    """Kogo dotyczą akceptacje osoby: ``None`` = wszyscy (Kadry, admin)."""

    if actor_of(actor).sees_everyone:
        return None
    return await people.direct_report_ids(db, actor.id)


async def pending_queue(
    db: AsyncSession, *, actor: User, today: date
) -> list[dict[str, Any]]:
    scope = await scope_user_ids(db, actor)
    statement = select(LeaveRequest).where(
        LeaveRequest.status == "pending", LeaveRequest.user_id != actor.id
    )
    if scope is not None:
        if not scope:
            return []
        statement = statement.where(LeaveRequest.user_id.in_(scope))
    rows = list(
        await db.scalars(statement.order_by(LeaveRequest.start_date).limit(300))
    )
    items = await serialize(db, rows, viewer=actor, today=today)
    profiles = {
        p.user_id: p
        for p in await db.scalars(
            select(EmployeeProfile).where(
                EmployeeProfile.user_id.in_({r.user_id for r in rows} or {-1})
            )
        )
    }
    managers = await names_of(
        db, {p.manager_user_id for p in profiles.values() if p.manager_user_id}
    )
    for item, row in zip(items, rows, strict=True):
        profile = profiles.get(row.user_id)
        item["department"] = profile.department if profile else None
        item["manager_name"] = (
            managers.get(profile.manager_user_id)
            if profile and profile.manager_user_id
            else None
        )
        work = await work_in_period(
            db, user_id=row.user_id, start=row.start_date, end=row.end_date
        )
        item["work_total"] = work["total"]
        item["work_by_kind"] = work["by_kind"]
        item["department_absent"] = await department_absences(
            db,
            user_id=row.user_id,
            department=profile.department if profile else None,
            start=row.start_date,
            end=row.end_date,
        )
    return items


async def history(
    db: AsyncSession,
    *,
    actor: User,
    today: date,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    scope = await scope_user_ids(db, actor)
    statement = select(LeaveRequest)
    if scope is not None:
        if not scope:
            return []
        statement = statement.where(LeaveRequest.user_id.in_(scope))
    if status:
        statement = statement.where(LeaveRequest.status == status)
    if user_id is not None:
        statement = statement.where(LeaveRequest.user_id == user_id)
    if date_from is not None:
        statement = statement.where(LeaveRequest.end_date >= date_from)
    if date_to is not None:
        statement = statement.where(LeaveRequest.start_date <= date_to)
    rows = list(
        await db.scalars(
            statement.order_by(
                LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc()
            ).limit(limit)
        )
    )
    return await serialize(db, rows, viewer=actor, today=today)


async def on_behalf_people(db: AsyncSession, *, actor: User) -> list[dict[str, Any]]:
    """Osoby, którym przełożony (zespół) albo Kadry (wszyscy) wpisują nieobecność."""

    scope = await scope_user_ids(db, actor)
    statement = (
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(
            User.is_active.is_(True),
            User.id != actor.id,
            EmployeeProfile.employment_status != "exited",
        )
        .order_by(User.name, User.id)
    )
    if scope is not None:
        if not scope:
            return []
        statement = statement.where(User.id.in_(scope))
    rows = (await db.execute(statement)).all()
    return [
        {
            "user_id": user.id,
            "name": user.name,
            "employment_type": profile.employment_type,
            "department": profile.department,
        }
        for user, profile in rows
    ]


async def subject_for_on_behalf(
    db: AsyncSession, *, actor: User, user_id: int
) -> tuple[User, EmployeeProfile]:
    """Osoba, której wolno wpisać nieobecność (inaczej 404/403)."""

    subject, profile = await _subject(db, user_id)
    if subject.id == actor.id:
        raise LeaveForbidden(
            "Własną nieobecność składasz w „Mój czas” — akceptuje ją ktoś inny."
        )
    if profile.employment_status == "exited":
        raise LeaveNotFound(user_id)
    if not can_decide(
        actor_of(actor),
        subject_user_id=subject.id,
        subject_manager_id=profile.manager_user_id,
    ):
        raise LeaveForbidden("Nieobecność wpisujesz tylko osobom ze swojego zespołu.")
    return subject, profile
