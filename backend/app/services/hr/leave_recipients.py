"""Kto i jakimi słowami dowiaduje się o wniosku urlopowym.

Przełożonego (kto decyduje albo przyjmuje zgłoszenie do wiadomości) liczy
jedna reguła ``recipients.supervisor_of``: przełożony z kartoteki, gdy ma
aktywne konto i nie odszedł → head pionu → Kadry. Zastępca przełożonego,
który jest dziś na urlopie, dostaje to samo do wiadomości albo do decyzji
(rodzaje planowe).

Powiadomienia nie zdradzają rodzaju nieobecności ani notatki (D6) — dzwonek
osoby może zobaczyć jej zastępca, a zastępca nie należy do kręgu D6. Jeden
odbiorca nie blokuje decyzji ani reszty (``notify.notify_each``). Tu jest też
ślad wniosku (``audit_request``) i zgłoszenie Płacom zmiany w zamkniętym
miesiącu — wołają je złożenie, decyzje i przeliczenie po dniu wolnym firmy.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import audit
from app.services.hr.employment_terms import form_of, terms
from app.services.hr.leave_policy import HEALTH_TYPES, substitute_sees_type
from app.services.hr.notify import notify_each
from app.services.hr.recipients import (
    people_admin_ids,
    supervisor_of,
    users_with_permission,
)

LINK_SELF = "/my-time"
LINK_SELF_LEAVE = "/my-time?tab=leave"
LINK_APPROVALS = "/people/approvals"
LINK_CALENDAR = "/people/calendar"


# ── Słowa ─────────────────────────────────────────────────────────────────────


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


def _month_label(key: str) -> str:
    from app.services.hr.payroll_periods import label

    return label(int(key[:4]), int(key[5:7]))


def payroll_locked_warning(months: tuple[str, ...] | list[str]) -> Optional[str]:
    """Tekst ostrzeżenia dla osoby, która zatwierdziła albo anulowała urlop."""

    if not months:
        return None
    labels = ", ".join(_month_label(key) for key in months)
    if len(months) == 1:
        head = f"Miesiąc płac {labels} jest już zamknięty"
    else:
        head = f"Miesiące płac {labels} są już zamknięte"
    return (
        f"{head} — godziny w nim zostały bez zmian. "
        "Korektę zrobią Płace, dostały powiadomienie."
    )


#: Stan raportu godzin w odmowie zgłoszenia — w rodzaju gramatycznym nazwy
#: dokumentu ze słownika formy („raport godzin”, „potwierdzenie godzin”).
_SENT_STATE: dict[str, dict[str, str]] = {
    "uop": {"submitted": "wysłana", "approved": "zaakceptowana"},
    "b2b": {"submitted": "wysłany", "approved": "potwierdzony"},
    "zlecenie": {"submitted": "wysłane", "approved": "przyjęte"},
}


def sent_timesheet_refusal(
    employment_type: Optional[str], months: list[tuple[str, str]]
) -> Optional[str]:
    """Odmowa zgłoszenia na dni z raportu godzin, który jest już wysłany albo
    przyjęty (``months``: ``RRRR-MM`` i status) — najpierw koordynator cofa
    raport do szkicu. ``None`` = nic nie blokuje."""

    if not months:
        return None
    words = terms(employment_type)
    states = _SENT_STATE[form_of(employment_type)]
    parts = ", a ".join(
        f"za {_month_label(key)} jest już {states[status]}" for key, status in months
    )
    where = "w tym miesiącu" if len(months) == 1 else "w tych miesiącach"
    return (
        f"{words['timesheet']} {parts}. Żeby zgłosić {words['absence_accusative']} "
        f"{where}, {words['coordinator']} musi najpierw cofnąć "
        f"{words['timesheet_accusative']} do szkicu."
    )


# ── Ślad ──────────────────────────────────────────────────────────────────────


def _sensitivity(leave_type: str, note: Optional[str]) -> str:
    return "health" if leave_type in HEALTH_TYPES or note else "general"


def audit_request(
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


# ── Powiadomienia ─────────────────────────────────────────────────────────────


async def notify(
    db: AsyncSession,
    user_ids: Iterable[Optional[int]],
    *,
    title: str,
    message: str,
    ntype: NotificationType,
    link: str,
    exclude: Iterable[Optional[int]] = (),
) -> int:
    return await notify_each(
        db,
        user_ids,
        title=title,
        message=message,
        ntype=ntype,
        link=link,
        related_entity_type="leave_request",
        exclude=exclude,
        log_tag="hr_leave",
    )


async def notify_requested(
    db: AsyncSession,
    *,
    subject: User,
    profile: EmployeeProfile,
    leave_type: str,
    span: str,
    days_text: str,
    today: date,
    request_id: Optional[uuid.UUID] = None,
) -> None:
    """Wniosek z umowy o pracę czeka na decyzję przełożonego.

    Link niesie numer wniosku (`?leave=`): przyciski maila „Zatwierdź”
    i „Odrzuć” otwierają ten wniosek z oknem potwierdzenia (26.10.2026).
    """

    link = f"{LINK_APPROVALS}?leave={request_id}" if request_id else LINK_APPROVALS
    supervisor = await supervisor_of(db, profile, today)
    recipients = list(supervisor.user_ids)
    stand_in = supervisor.stand_in
    decides = substitute_sees_type(leave_type)
    if stand_in is not None and not decides:
        # Zastępca L4 i pokrewnych tylko przyjmuje do wiadomości — wniosek
        # nie może czekać do powrotu przełożonego, więc decydują też Kadry.
        recipients = [*recipients, *await people_admin_ids(db)]
    await notify(
        db,
        recipients,
        exclude={subject.id},
        title="Wniosek o nieobecność do akceptacji",
        message=f"{subject.name}: {span} ({days_text}).",
        ntype=NotificationType.hr_leave_requested,
        link=link,
    )
    if stand_in is not None:
        await notify(
            db,
            [stand_in.user_id],
            exclude={subject.id, *recipients},
            title=(
                "Wniosek o nieobecność do akceptacji"
                if decides
                else "Wniosek o nieobecność do wiadomości"
            ),
            message=(
                f"{subject.name}: {span} ({days_text}) — w zastępstwie za "
                f"{stand_in.manager_name}." + ("" if decides else " Decydują Kadry.")
            ),
            ntype=NotificationType.hr_leave_requested,
            link=link,
        )


async def notify_reported(
    db: AsyncSession,
    *,
    subject: User,
    profile: EmployeeProfile,
    span: str,
    days_text: str,
    today: date,
) -> None:
    """Zgłoszenie z B2B albo zlecenia (D5) — informacja dla koordynatora.

    Bez rodzaju i notatki (D6); zastępca nieobecnego przełożonego dostaje to
    samo do wiadomości. Kadry nie dostają kopii — zgłoszenie to nie L4.
    """

    words = terms(profile.employment_type)
    supervisor = await supervisor_of(db, profile, today)
    await notify(
        db,
        supervisor.user_ids,
        exclude={subject.id},
        title=words["reported_title"],
        message=(
            f"{subject.name}: {span} ({days_text}). Termin jest już w kalendarzu — "
            "jeśli koliduje z pracą, zgłoś kolizję w „Akceptacjach”."
        ),
        ntype=NotificationType.hr_absence_reported,
        link=LINK_APPROVALS,
    )
    if supervisor.stand_in is not None:
        await notify(
            db,
            [supervisor.stand_in.user_id],
            exclude={subject.id, *supervisor.user_ids},
            title=words["reported_title"],
            message=(
                f"{subject.name}: {span} ({days_text}) — do wiadomości, "
                f"w zastępstwie za {supervisor.stand_in.manager_name}."
            ),
            ntype=NotificationType.hr_absence_reported,
            link=LINK_APPROVALS,
        )


async def notify_auto_approved(
    db: AsyncSession,
    *,
    actor: User,
    subject: User,
    profile: EmployeeProfile,
    span: str,
    today: date,
) -> None:
    """L4 i pokrewne wchodzą od razu — przełożony i Kadry do wiadomości."""

    supervisor = await supervisor_of(db, profile, today)
    recipients = [*supervisor.user_ids, *await people_admin_ids(db)]
    await notify(
        db,
        recipients,
        exclude={actor.id, subject.id},
        title="Zgłoszona nieobecność",
        message=f"{subject.name}: nieobecność {span}, zatwierdzona od razu.",
        ntype=NotificationType.hr_absence_reported,
        link=LINK_APPROVALS,
    )
    # Zastępca nieobecnego przełożonego przyjmuje do wiadomości (bez rodzaju).
    if supervisor.stand_in is not None:
        await notify(
            db,
            [supervisor.stand_in.user_id],
            exclude={actor.id, subject.id, *recipients},
            title="Zgłoszona nieobecność",
            message=(
                f"{subject.name}: nieobecność {span}, zatwierdzona od razu — "
                f"do wiadomości, w zastępstwie za {supervisor.stand_in.manager_name}."
            ),
            ntype=NotificationType.hr_absence_reported,
            link=LINK_CALENDAR,
        )


async def notify_cancelled(
    db: AsyncSession,
    *,
    request: LeaveRequest,
    previous_status: str,
    actor: User,
    subject: User,
    profile: Optional[EmployeeProfile],
) -> None:
    """Anulowanie: osoba, jej przełożony i zastępca z zatwierdzonego wniosku."""

    supervisor = await supervisor_of(db, profile)
    recipients = [subject.id, *supervisor.user_ids]
    if previous_status == "approved" and request.substitute_user_id is not None:
        recipients.append(request.substitute_user_id)
    form = profile.employment_type if profile else None
    await notify(
        db,
        recipients,
        exclude={actor.id},
        title=terms(form)["cancelled_title"],
        message=(
            f"{subject.name}: {format_range(request.start_date, request.end_date)} "
            f"— anulowanie: {actor.name}."
        ),
        ntype=NotificationType.hr_leave_cancelled,
        link=LINK_CALENDAR,
    )


async def report_payroll_locked(
    db: AsyncSession,
    *,
    request: LeaveRequest,
    subject: User,
    actor_id: Optional[int],
    months: list[str],
    event: str,
) -> tuple[str, ...]:
    """Urlop w zamkniętym miesiącu płac: ślad i dzwonek dla Płac (bez rodzaju)."""

    if not months:
        return ()
    found = tuple(sorted(set(months)))
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=request.user_id,
        entity_type="leave_request",
        entity_id=request.id,
        action="leave_in_closed_payroll_month",
        details={
            "months": list(found),
            "event": event,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
        },
        sensitivity="payroll",
    )
    from app.services.hr.time_flow import payroll_link

    payroll = [
        user.id for user in await users_with_permission(db, ProductAction.payroll)
    ]
    first = found[0]
    await notify(
        db,
        payroll,
        exclude={actor_id},
        title="Nieobecność w zamkniętym miesiącu płac",
        message=(
            f"{subject.name}: {', '.join(_month_label(key) for key in found)}. "
            "Godziny w zamkniętym miesiącu czekają na korektę."
        ),
        ntype=NotificationType.hr_timesheet_decided,
        link=payroll_link(int(first[:4]), int(first[5:7])),
    )
    return found


async def report_sent_timesheet_changed(
    db: AsyncSession,
    *,
    request: LeaveRequest,
    subject: User,
    actor_id: Optional[int],
    months: list[str],
) -> None:
    """Zmiana nieobecności przepisała godziny wysłanego albo przyjętego raportu
    osoby na B2B/zleceniu — dzwonek do koordynatora (decyzja Artura 19.10.2026:
    Kadry mogą to zrobić, ale koordynator ma wiedzieć). Bez rodzaju (D6)."""

    if not months:
        return
    from app.services.hr import people
    from app.services.hr.employment_terms import reports_absence
    from app.services.hr.time_flow import approvals_link

    profile = await people.profile_of(db, request.user_id)
    form = profile.employment_type if profile else None
    if not reports_absence(form):
        return
    found = sorted(set(months))
    words = terms(form)
    boss = await supervisor_of(db, profile)
    first = found[0]
    await notify(
        db,
        boss.user_ids,
        exclude={actor_id, request.user_id},
        title=f"{words['timesheet']}: godziny zmienione po wysłaniu",
        message=(
            f"{subject.name}, {', '.join(_month_label(key) for key in found)} — "
            "zmiana terminu przepisała godziny, które były już wysłane. "
            f"Sprawdź {words['timesheet_accusative']} przed akceptacją."
        ),
        ntype=NotificationType.hr_timesheet_decided,
        link=approvals_link(int(first[:4]), int(first[5:7]), request.user_id),
    )


__all__ = [
    "LINK_APPROVALS",
    "LINK_CALENDAR",
    "LINK_SELF",
    "LINK_SELF_LEAVE",
    "audit_request",
    "days_label",
    "format_range",
    "notify",
    "notify_auto_approved",
    "notify_cancelled",
    "notify_reported",
    "notify_requested",
    "payroll_locked_warning",
    "report_payroll_locked",
    "report_sent_timesheet_changed",
    "sent_timesheet_refusal",
]
