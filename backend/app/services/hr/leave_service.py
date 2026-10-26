"""Wnioski urlopowe — złożenie, akceptacja, odrzucenie, anulowanie, kolizja,
wpis za pracownika („Ludzie w NEXUSIE”, E1).

Reguły liczą czyste funkcje (``leave_policy``); tu jest kolejność zapisu,
ślad i kolejka Microsoft 365. Każda decyzja to warunkowy
``UPDATE … WHERE status = …`` — drugi akceptujący dostaje konflikt (409),
a nie drugą decyzję. Dni wniosku (``leave_request_days.active``) zmieniają się
w tej samej transakcji co status.

Na B2B i zleceniu (etap 2, D5, 17.10.2026) nieobecność jest ZGŁOSZENIEM, nie
wnioskiem: termin wchodzi od razu (``approved`` bez decydującego, Microsoft 365
i godziny od razu), koordynator dostaje informację i może zgłosić kolizję
(``report_conflict``) — nie akceptuje, nie odrzuca i nie anuluje (to robią
sama osoba albo Kadry). Od 08.07.2026 PIP sam stwierdza stosunek pracy,
a akceptacja urlopu przez przełożonego to sygnał podporządkowania. Słowa
(przerwa, nieobecność, koordynator) daje ``employment_terms``. Umowa o pracę
bez zmian: wniosek i akceptacja przełożonego.

Kto jest przełożonym (decyduje albo przyjmuje zgłoszenie do wiadomości), liczy
jedna reguła ``recipients.supervisor_of``: przełożony z kartoteki, gdy ma
aktywne konto i nie odszedł → head pionu → Kadry. Head pionu decyduje o osobach
swojego pionu bez żywego przełożonego (``recipients.division_charges``).

Moduł jest rdzeniem; obok leżą:

* ``leave_recipients`` — kto i jakimi słowami dowiaduje się o wniosku (bez
  rodzaju nieobecności i notatki, D6), ślad wniosku, zgłoszenie Płacom,
* ``leave_recount`` — przeliczenie dni po dniu wolnym firmy dodanym albo
  usuniętym po złożeniu wniosku,
* ``leave_queries`` — wiersz wniosku, moje wnioski, kolejki i historia.

Nazwy z tych modułów są tu re-eksportowane, żeby dotychczasowe importy
(``leave_service.serialize`` itd.) działały bez zmian.

Zatwierdzenie albo anulowanie urlopu w miesiącu zamkniętym w płacach nie
rusza godzin tego miesiąca (``time_hooks``) — wynik niesie listę takich
miesięcy (ostrzeżenie w odpowiedzi API), Płace dostają dzwonek, a ślad idzie
z ``sensitivity='payroll'``.

Zgłoszenie (B2B, zlecenie) na dzień z miesiąca, którego raport godzin jest
wysłany albo przyjęty, dostaje 409 (podgląd: ``blocking_reason``) — wchodzi
bez niczyjej decyzji, więc nie może przepisać dokumentu, który leży
u koordynatora; najpierw koordynator cofa raport do szkicu (17.10.2026).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today
from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import audit, leave_substitute, people
from app.services.hr.calendar import load_calendar, years_between
from app.services.hr.employment_terms import reports_absence, terms
from app.services.hr.leave_balance import pools_for
from app.services.hr.leave_context import (
    busy_user_ids,
    department_absences,
    overlapping_request,
    work_in_period,
)
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.leave_outlook import SOURCE as OUTLOOK_SOURCE
from app.services.hr.leave_policy import (
    ACTIVE_DAY_UNIQUE,
    AUTO_APPROVED_TYPES,
    FORWARD_OUTSIDE_COMPANY,
    SUBSTITUTE_ACK_ONLY,
    LeavePolicyError,
    actor_of,
    can_decide,
    covering_manager,
    forward_target_allowed,
    own_cancel_refusal,
    plan_days,
    requested_days,
    substitute_sees_type,
    team_cancel_refusal,
    validate_shape,
)
from app.services.hr.leave_queries import (
    CONFLICT_ACTION,
    history,
    my_requests,
    names_of,
    on_behalf_people,
    pending_count,
    pending_queue,
    reported_queue,
    request_splits,
    scope_user_ids,
    serialize,
)
from app.services.hr.leave_recipients import (
    LINK_APPROVALS,
    LINK_CALENDAR,
    LINK_SELF,
    LINK_SELF_LEAVE,
    audit_request,
    days_label,
    format_range,
    notify,
    notify_auto_approved,
    notify_cancelled,
    notify_reported,
    notify_requested,
    payroll_locked_warning,
    report_payroll_locked,
    report_sent_timesheet_changed,
    sent_timesheet_refusal,
)
from app.services.hr.leave_recount import recount_for_company_day_off
from app.services.hr.m365 import outbox
from app.services.hr.recipients import (
    division_charges,
    people_admin_ids,
    supervisor_of,
)

CONFLICT_NOTE_MAX = 1000
REPORT_NOT_DECIDED = (
    "Na B2B i zleceniu nieobecność jest zgłoszeniem — nikt jej nie zatwierdza ani "
    "nie odrzuca. Jeśli termin koliduje z pracą, zgłoś kolizję."
)
REPORT_CANCEL_FORBIDDEN = (
    "Zgłoszenie osoby na B2B albo zleceniu anuluje ona sama albo Kadry — "
    "koordynator może zgłosić kolizję."
)


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


@dataclass(frozen=True)
class LeaveOutcome:
    """Zapisany wniosek i to, czego nie widać w samym wierszu."""

    request: LeaveRequest
    #: Miesiące płac (``RRRR-MM``) zamknięte — ich godzin nie ruszono.
    payroll_locked_months: tuple[str, ...] = ()

    @property
    def payroll_warning(self) -> Optional[str]:
        return payroll_locked_warning(self.payroll_locked_months)


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


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


def _assert_forward_target(substitute: Optional[User]) -> None:
    """Zgoda na przekierowanie tylko przy zastępcy z adresem w domenie firmy."""

    if substitute is not None and not forward_target_allowed(
        substitute.email, settings.sso_allowed_domains_list
    ):
        raise LeavePolicyError(FORWARD_OUTSIDE_COMPANY)


async def _snapshot(db: AsyncSession, request: LeaveRequest) -> LeaveSnapshot:
    calendar = await load_calendar(db, request.start_date, request.end_date)
    return LeaveSnapshot(
        id=str(request.id),
        user_id=request.user_id,
        start=request.start_date,
        end=request.end_date,
        half_day=request.half_day,
        total_days=(await request_splits(db, [request]))[request.id].total,
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
        if request.source == OUTLOOK_SOURCE and not op.kind.startswith("forward_"):
            # Wniosek z autoodpowiedzi w Outlooku: osoba ma już swoją
            # autoodpowiedź — bez naszej i bez wydarzenia (``leave_outlook``).
            # Przekierowanie zostaje: zgodę daje na nie sama osoba.
            continue
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


async def _sent_timesheet_refusal(
    db: AsyncSession,
    *,
    user_id: int,
    employment_type: Optional[str],
    days: list[tuple[date, Decimal]],
    lock: bool,
) -> Optional[str]:
    """Zgłoszenie nie przepisuje raportu godzin, który jest już wysłany albo
    przyjęty — odmowa po polsku albo ``None``."""

    from app.services.hr import time_hooks

    months = await time_hooks.sent_months(
        db, user_id, [day for day, _ in days], lock=lock
    )
    return sent_timesheet_refusal(employment_type, months)


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
    ``flow`` mówi oknu, czy to wniosek do akceptacji (umowa o pracę), czy
    zgłoszenie (B2B, zlecenie — D5); ``approver`` to wtedy koordynator.
    """

    reported = for_self and reports_absence(profile.employment_type)
    result: dict[str, Any] = {
        "working_days": [],
        "days_total": "0.0",
        "paid_days": "0.0",
        "unpaid_days": "0.0",
        "years": [],
        "blocking_reason": None,
        "auto_approved": data.leave_type in AUTO_APPROVED_TYPES
        or not for_self
        or reported,
        "employment_type": profile.employment_type,
        "flow": "report" if reports_absence(profile.employment_type) else "request",
        "approver": (await supervisor_of(db, profile)).label,
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
        refusal = (
            await _sent_timesheet_refusal(
                db,
                user_id=subject.id,
                employment_type=profile.employment_type,
                days=days,
                lock=False,
            )
            if reported
            else None
        )
        if refusal is not None:
            raise LeavePolicyError(refusal)
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
    # Składający widzi tylko zatwierdzone nieobecności kolegów i zastępcy
    # (decyzja Artura 19.10.2026); podgląd wpisu za pracownika — także oczekujące.
    result["department_absent"] = await department_absences(
        db,
        user_id=subject.id,
        department=profile.department,
        start=data.start_date,
        end=data.end_date,
        approved_only=for_self,
    )
    result["work"] = await work_in_period(
        db,
        user_id=subject.id,
        start=data.start_date,
        end=data.end_date,
        with_titles=for_self,
    )
    if data.substitute_user_id is not None:
        busy = await busy_user_ids(
            db, data.start_date, data.end_date, approved_only=for_self
        )
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
) -> LeaveOutcome:
    """Zapisuje wniosek. Wpis za pracownika, L4 i zgłoszenie z B2B albo
    zlecenia (D5) są zatwierdzone od razu — zgłoszenie bez decydującego.

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
    reported = for_self and reports_absence(profile.employment_type)
    if reported:
        refusal = await _sent_timesheet_refusal(
            db,
            user_id=subject.id,
            employment_type=profile.employment_type,
            days=days,
            lock=True,
        )
        if refusal is not None:
            raise LeaveConflict(refusal)
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
    if for_self and data.forward_mail_consent:
        _assert_forward_target(substitute)
    words = terms(profile.employment_type)
    approved = on_behalf or data.leave_type in AUTO_APPROVED_TYPES or reported
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
        if ACTIVE_DAY_UNIQUE in str(exc.orig):
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
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action=action,
        extra={
            "days": f"{plan.total:.1f}",
            **({"flow": "report"} if reported else {}),
        },
    )

    if not approved:
        await notify_requested(
            db,
            subject=subject,
            profile=profile,
            leave_type=data.leave_type,
            span=span,
            days_text=days_text,
            today=today,
            request_id=request.id,
        )
        return LeaveOutcome(request)

    if on_behalf:
        what = (
            words["absence_accusative"]
            if reports_absence(profile.employment_type)
            else "nieobecność"
        )
        await notify(
            db,
            [subject.id],
            exclude={actor.id},
            title=f"Wpisano Ci {what}",
            message=f"{span} — wpis: {actor.name}.",
            ntype=NotificationType.hr_leave_decided,
            link=LINK_SELF,
        )
    if reported:
        await notify_reported(
            db,
            subject=subject,
            profile=profile,
            span=span,
            days_text=days_text,
            today=today,
        )
    elif data.leave_type in AUTO_APPROVED_TYPES:
        await notify_auto_approved(
            db, actor=actor, subject=subject, profile=profile, span=span, today=today
        )
    locked = await _after_approval(
        db, request, subject=subject, actor=actor, today=today
    )
    return LeaveOutcome(request, locked)


async def _after_approval(
    db: AsyncSession, request: LeaveRequest, *, subject: User, actor: User, today: date
) -> tuple[str, ...]:
    if request.substitute_user_id is not None and request.end_date >= today:
        await notify(
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
    # dzień puli B2B dostaje auto-wpisy, hash zaakceptowanego PDF-u się
    # przelicza. Zamknięte w płacach miesiące są tylko raportowane.
    from app.services.hr import time_hooks

    hooked = await time_hooks.on_leave_approved(
        db, request.user_id, await _request_days(db, request.id)
    )
    await report_sent_timesheet_changed(
        db,
        request=request,
        subject=subject,
        actor_id=actor.id,
        months=hooked["sent_changed"],
    )
    return await report_payroll_locked(
        db,
        request=request,
        subject=subject,
        actor_id=actor.id,
        months=hooked["locked_conflicts"],
        event="approved",
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
    request, subject, profile, _ = await _decision_scope(
        db, actor, request_id, cover_on=None
    )
    return request, subject, profile


async def _decision_scope(
    db: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    *,
    cover_on: Optional[date],
) -> tuple[
    LeaveRequest, User, Optional[EmployeeProfile], Optional[leave_substitute.Cover]
]:
    """Wniosek, o którym osoba decyduje, i ewentualne zastępstwo.

    Decyduje przełożony, Kadry, admin i head pionu o osobach swojego pionu bez
    żywego przełożonego (``recipients.division_charges`` — ta sama reguła,
    która kieruje do niego wniosek). ``cover_on`` (dziś) wpuszcza też zastępcę
    przełożonego, który jest tego
    dnia na urlopie — tylko akceptacja i odrzucenie, nie anulowanie ani wpis
    za pracownika. Rodzaj spoza planowych (L4 i pokrewne) zastępca tylko
    przyjmuje do wiadomości (403).
    """

    request = await db.get(LeaveRequest, request_id)
    if request is None:
        raise LeaveNotFound(request_id)
    profile = await people.profile_of(db, request.user_id)
    if request.user_id == actor.id:
        raise LeaveForbidden("Nie możesz decydować o własnym wniosku.")
    manager_id = profile.manager_user_id if profile else None
    cover: Optional[leave_substitute.Cover] = None
    if not can_decide(
        actor_of(actor), subject_user_id=request.user_id, subject_manager_id=manager_id
    ) and request.user_id not in await division_charges(db, actor.id):
        covers = (
            await leave_substitute.covers_of(db, actor.id, cover_on)
            if cover_on is not None
            else []
        )
        covered = covering_manager(
            actor.id,
            subject_user_id=request.user_id,
            subject_manager_id=manager_id,
            covered_manager_ids=[c.manager_user_id for c in covers],
        )
        if covered is None:
            # Wniosek spoza zakresu wygląda jak nieistniejący (bez wycieku dat).
            raise LeaveNotFound(request_id)
        if not substitute_sees_type(request.leave_type):
            raise LeaveForbidden(SUBSTITUTE_ACK_ONLY)
        cover = next(c for c in covers if c.manager_user_id == covered)
    subject = await db.get(User, request.user_id)
    assert subject is not None
    return request, subject, profile, cover


def _cover_extra(cover: Optional[leave_substitute.Cover]) -> dict[str, Any]:
    """Ślad decyzji zastępcy: „w zastępstwie za …”."""

    if cover is None:
        return {}
    return {
        "as_substitute_for_user_id": cover.manager_user_id,
        "as_substitute_for": f"w zastępstwie za {cover.manager_name}",
    }


def _decided_by_text(actor: User, cover: Optional[leave_substitute.Cover]) -> str:
    if cover is None:
        return actor.name
    return f"{actor.name} (w zastępstwie za {cover.manager_name})"


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


def _refuse_report_decision(
    request: LeaveRequest, profile: Optional[EmployeeProfile]
) -> None:
    """Zgłoszenia z B2B i zlecenia nikt nie zatwierdza ani nie odrzuca (D5).

    Czekający wniosek osoby, której forma zmieniła się po złożeniu (z umowy
    o pracę na B2B), dalej można rozstrzygnąć — inaczej utknąłby na zawsze.
    """

    if request.status != "pending" and reports_absence(
        profile.employment_type if profile else None
    ):
        raise LeaveConflict(REPORT_NOT_DECIDED)


async def approve(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    note: Optional[str],
    today: date,
) -> LeaveOutcome:
    request, subject, profile, cover = await _decision_scope(
        db, actor, request_id, cover_on=today
    )
    _refuse_report_decision(request, profile)
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
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action="leave_approved",
        extra=_cover_extra(cover),
    )
    await notify(
        db,
        [subject.id],
        exclude={actor.id},
        title="Wniosek zaakceptowany",
        message=(
            f"{format_range(request.start_date, request.end_date)} — "
            f"akceptacja: {_decided_by_text(actor, cover)}."
        ),
        ntype=NotificationType.hr_leave_decided,
        link=LINK_SELF,
    )
    locked = await _after_approval(
        db, request, subject=subject, actor=actor, today=today
    )
    return LeaveOutcome(request, locked)


async def reject(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    note: str,
    today: Optional[date] = None,
) -> LeaveRequest:
    reason = _clean(note)
    if reason is None or len(reason) < 3:
        raise LeavePolicyError(
            "Podaj powód odrzucenia — osoba zobaczy go przy wniosku."
        )
    request, subject, profile, cover = await _decision_scope(
        db, actor, request_id, cover_on=today or business_today()
    )
    _refuse_report_decision(request, profile)
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
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action="leave_rejected",
        extra=_cover_extra(cover),
    )
    await notify(
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
) -> tuple[str, ...]:
    await _set_days_active(db, request.id, False)
    await db.refresh(request)
    audit_request(
        db,
        actor_id=actor.id,
        request=request,
        action="leave_cancelled",
        extra={"previous_status": previous_status},
    )
    await notify_cancelled(
        db,
        request=request,
        previous_status=previous_status,
        actor=actor,
        subject=subject,
        profile=profile,
    )
    if previous_status != "approved":
        return ()
    await _enqueue_m365(db, request, "cancelled", today=today)
    from app.services.hr import time_hooks

    hooked = await time_hooks.on_leave_cancelled(
        db, request.user_id, await _request_days(db, request.id)
    )
    await report_sent_timesheet_changed(
        db,
        request=request,
        subject=subject,
        actor_id=actor.id,
        months=hooked["sent_changed"],
    )
    return await report_payroll_locked(
        db,
        request=request,
        subject=subject,
        actor_id=actor.id,
        months=hooked["locked_conflicts"],
        event="cancelled",
    )


async def cancel_own(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, today: date
) -> LeaveOutcome:
    request = await db.get(LeaveRequest, request_id)
    if request is None or request.user_id != actor.id:
        raise LeaveNotFound(request_id)
    profile = await people.profile_of(db, actor.id)
    refusal = own_cancel_refusal(
        status=request.status,
        start=request.start_date,
        today=today,
        reported=reports_absence(profile.employment_type if profile else None),
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
    locked = await _after_cancel(
        db,
        request,
        previous_status=previous,
        actor=actor,
        subject=actor,
        profile=profile,
        today=today,
    )
    return LeaveOutcome(request, locked)


async def cancel_as_approver(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, today: date
) -> LeaveOutcome:
    request, subject, profile = await _decidable(db, actor, request_id)
    refusal = team_cancel_refusal(status=request.status)
    if refusal is not None:
        raise LeaveConflict(refusal)
    # Anulowanie zgłoszenia przez koordynatora to odrzucenie pod inną nazwą (D5).
    if (
        reports_absence(profile.employment_type if profile else None)
        and request.status == "approved"
        and not actor_of(actor).sees_everyone
    ):
        raise LeaveForbidden(REPORT_CANCEL_FORBIDDEN)
    previous = request.status
    changed = await _conditional_status(
        db,
        request_id,
        from_statuses=(previous,),
        values={"status": "cancelled"},
    )
    if not changed:
        raise LeaveConflict("Ten wniosek zmienił się w międzyczasie — odśwież listę.")
    locked = await _after_cancel(
        db,
        request,
        previous_status=previous,
        actor=actor,
        subject=subject,
        profile=profile,
        today=today,
    )
    return LeaveOutcome(request, locked)


async def report_conflict(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    note: str,
    today: date,
) -> LeaveRequest:
    """Koordynator zgłasza kolizję terminu z pracą (D5) — powiadomienie osoby.

    Zgłoszenie zostaje zatwierdzone (to nie odrzucenie): osoba sama decyduje,
    czy anulować i zgłosić inny termin. Notatka idzie do powiadomienia i do
    śladu HR; w mailu jej nie ma (``hr_mail``).
    """

    text = _clean(note)
    if text is None or len(text) < 3:
        raise LeavePolicyError(
            "Napisz, z czym koliduje termin — osoba zobaczy to w powiadomieniu."
        )
    if len(text) > CONFLICT_NOTE_MAX:
        raise LeavePolicyError(
            f"Notatka może mieć najwyżej {CONFLICT_NOTE_MAX} znaków."
        )
    # Kto zgłasza kolizję: jak przy decyzjach (przełożony, head pionu osoby bez
    # przełożonego, zastępca nieobecnego przełożonego, Kadry, admin).
    request, subject, profile, cover = await _decision_scope(
        db, actor, request_id, cover_on=today
    )
    form = profile.employment_type if profile else None
    if not reports_absence(form):
        raise LeaveConflict(
            "Kolizję zgłasza się przy nieobecnościach osób na B2B i zleceniu — "
            "wniosek na umowie o pracę akceptujesz albo odrzucasz."
        )
    if request.status != "approved":
        raise LeaveConflict("To zgłoszenie jest już zamknięte — odśwież listę.")
    if request.end_date < today:
        raise LeaveConflict("Ten termin już minął.")
    span = format_range(request.start_date, request.end_date)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.user_id,
        entity_type="leave_request",
        entity_id=request.id,
        action=CONFLICT_ACTION,
        details={
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "note": text,
            **_cover_extra(cover),
        },
    )
    await notify(
        db,
        [subject.id],
        exclude={actor.id},
        title=terms(form)["conflict_title"],
        message=f"{span} — {_decided_by_text(actor, cover)}: {text[:300]}",
        ntype=NotificationType.hr_leave_conflict,
        link=LINK_SELF_LEAVE,
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
    if consent:
        _assert_forward_target(await db.get(User, request.substitute_user_id))
    if request.forward_mail_consent == consent:
        return request
    request.forward_mail_consent = consent
    await db.flush()
    audit_request(
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


ON_BEHALF_REPORT_FORBIDDEN = (
    "Nieobecność osoby na B2B albo zleceniu zgłasza ona sama — wpis za nią robią Kadry."
)


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
    ) and subject.id not in await division_charges(db, actor.id):
        raise LeaveForbidden("Nieobecność wpisujesz tylko osobom ze swojego zespołu.")
    if reports_absence(profile.employment_type) and not actor_of(actor).sees_everyone:
        # D5 (decyzja Artura 19.10.2026): nieobecność osoby na B2B albo
        # zleceniu zgłasza ona sama; wpis za nią — tylko Kadry i admin, jak
        # zmiana i anulowanie zgłoszenia.
        raise LeaveForbidden(ON_BEHALF_REPORT_FORBIDDEN)
    return subject, profile


__all__ = [
    "CONFLICT_ACTION",
    "LINK_APPROVALS",
    "LINK_CALENDAR",
    "LINK_SELF",
    "LINK_SELF_LEAVE",
    "LeaveConflict",
    "LeaveForbidden",
    "LeaveInput",
    "LeaveNotFound",
    "LeaveOutcome",
    "actor_of",
    "approve",
    "cancel_as_approver",
    "cancel_own",
    "days_label",
    "format_range",
    "history",
    "my_requests",
    "names_of",
    "on_behalf_people",
    "payroll_locked_warning",
    "pending_count",
    "pending_queue",
    "people_admin_ids",
    "preview",
    "recount_for_company_day_off",
    "reject",
    "report_conflict",
    "reported_queue",
    "scope_user_ids",
    "serialize",
    "set_forward_consent",
    "subject_for_on_behalf",
    "submit",
]
