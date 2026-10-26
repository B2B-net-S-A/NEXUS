"""Nieobecność ustawiona ręcznie w Outlooku bez wniosku → wniosek (Compass, faza 36).

Uzgadnianie skrzynek o 7:00 (i „Uzgodnij teraz” w karcie Microsoft 365) czyta
autoodpowiedź każdej skrzynki zespołu. Własna autoodpowiedź osoby (bez
znacznika NEXUSA ani Compassa) z harmonogramem mówi, kiedy osoby nie ma. Dni
robocze tego okna (kalendarz firmy), których nie pokrywa żaden aktywny wniosek
tej osoby, stają się wnioskiem ``leave_type='vacation'``, ``source='outlook_oof'``
z notatką „Wykryte z autoodpowiedzi w Outlooku (od–do)…” — tyle wniosków, ile
ciągłych odcinków niepokrytych dni (weekend i święto nie przerywają odcinka,
pokryty dzień roboczy tak).

* **Umowa o pracę** — wniosek czeka na decyzję przełożonego jak każdy inny
  (powiadomienie ``hr_leave_requested``). Pula liczy się tą samą funkcją co
  przy złożeniu (``plan_days``); odcinek ponad pulę nie powstaje — zostaje
  na liście „własnych autoodpowiedzi” w karcie Microsoft 365.
* **B2B i zlecenie** (D5) — zgłoszenie przyjęte od razu (``approved`` bez
  decydującego), godziny jak przy zgłoszeniu; informacja do koordynatora
  (``notify_reported``) i do Kadr — istniejący typ ``hr_absence_reported``.
  Dzień z raportu godzin wysłanego albo przyjętego blokuje odcinek (jak
  zwykłe zgłoszenie — najpierw koordynator cofa raport do szkicu).
* **Bez operacji Microsoft 365** — osoba ma już autoodpowiedź, NEXUS jej nie
  nadpisuje i nie zakłada wydarzenia (``leave_service._enqueue_m365`` pomija
  wszystko poza przekierowaniem, na które zgodę daje sama osoba).
* **Bez duplikatów** — kolejny przebieg widzi dni aktywnego wniosku jako
  pokryte. Odrzucony albo anulowany wniosek (dowolnego źródła) pokrywa swoje
  dni, a wniosek z Outlooka — całe okno autoodpowiedzi, z którego powstał,
  także po skróceniu edycją: decyzja Kadr, przełożonego albo osoby nie wraca
  następnego ranka (``_covered_days``, audyt 19.10.2026).
* Tylko osoby z kartoteką (status ≠ ``exited``), których skrzynka jest
  w zakresie uzgadniania (lista próbna ``HR_M365_MAILBOX_ALLOWLIST``), i przy
  włączonym module urlopów. Autoodpowiedź bez dat (włączona na stałe) nie
  daje wniosku — osoba zostaje na liście dla Kadr.

Funkcja nie commituje; wołający zapisuje skrzynkę po skrzynce.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_ops import HrAuditEvent
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import people
from app.services.hr.calendar import load_calendar, years_between
from app.services.hr.employment_terms import reports_absence
from app.services.hr.leave_balance import pools_for
from app.services.hr.leave_context import overlapping_request
from app.services.hr.leave_policy import (
    ACTIVE_DAY_UNIQUE,
    LeavePolicyError,
    plan_days,
    requested_days,
    validate_shape,
)
from app.services.hr.leave_recipients import (
    LINK_APPROVALS,
    audit_request,
    days_label,
    format_range,
    notify,
    notify_reported,
    notify_requested,
    report_payroll_locked,
    sent_timesheet_refusal,
)
from app.services.hr.m365 import oof_state
from app.services.hr.recipients import people_admin_ids
from app.services.hr_foundation_schema import EmploymentStatus

SOURCE = "outlook_oof"
LEAVE_TYPE = "vacation"
ACTION = "leave_detected_from_outlook"
#: Decyzja o wniosku z Outlooka zamyka jego okno — nie zakładamy go ponownie.
_CLOSED_BY_DECISION = ("rejected", "cancelled")


def note_for(start: date, end: date, *, reported: bool) -> str:
    span = format_range(start, end)
    if reported:
        return (
            f"Wykryte z autoodpowiedzi w Outlooku ({span}) — zgłoszenie przyjęte; "
            "jeśli się nie zgadza, anuluje je osoba albo Kadry."
        )
    return (
        f"Wykryte z autoodpowiedzi w Outlooku ({span}) — sprawdź i zatwierdź "
        "albo odrzuć."
    )


def missing_runs(
    working_days: Sequence[date], covered: Collection[date]
) -> list[tuple[date, date]]:
    """Ciągłe odcinki dni roboczych bez pokrycia.

    ``working_days`` — dni robocze okna po kolei (bez weekendów i świąt, więc
    piątek i poniedziałek są sąsiadami); pokryty dzień przerywa odcinek.
    """

    runs: list[tuple[date, date]] = []
    start: Optional[date] = None
    end: Optional[date] = None
    for day in working_days:
        if day in covered:
            if start is not None and end is not None:
                runs.append((start, end))
            start = end = None
            continue
        if start is None:
            start = day
        end = day
    if start is not None and end is not None:
        runs.append((start, end))
    return runs


async def _covered_days(
    db: AsyncSession, user_id: int, start: date, end: date
) -> set[date]:
    """Dni okna, z których wniosku z Outlooka już nie zakładamy.

    * dni aktywnego wniosku (oczekującego albo zatwierdzonego),
    * dni każdego odrzuconego albo anulowanego wniosku — decyzja człowieka
      o tych dniach zapadła (przełożony odrzucił, osoba anulowała); bez tego
      zostawiona w Outlooku autoodpowiedź zakładała nazajutrz nowy wniosek,
      a na B2B od razu przyjęte zgłoszenie,
    * całe okno autoodpowiedzi, z którego powstał wcześniejszy wniosek z
      Outlooka (``oof_window`` w śladzie) — wniosek skrócony edycją nie
      odrasta z tej samej autoodpowiedzi.
    """

    active = await db.scalars(
        select(LeaveRequestDay.day).where(
            LeaveRequestDay.user_id == user_id,
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day >= start,
            LeaveRequestDay.day <= end,
        )
    )
    covered = set(active.all())
    closed = await db.execute(
        select(LeaveRequest.start_date, LeaveRequest.end_date).where(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status.in_(_CLOSED_BY_DECISION),
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
    )
    spans: list[tuple[date, date]] = list(closed.tuples().all())
    detected = await db.scalars(
        select(HrAuditEvent.details).where(
            HrAuditEvent.subject_user_id == user_id,
            HrAuditEvent.entity_type == "leave_request",
            HrAuditEvent.action == ACTION,
        )
    )
    for details in detected.all():
        window = _audit_window(details)
        if window is not None:
            spans.append(window)
    for span_start, span_end in spans:
        day = max(span_start, start)
        while day <= min(span_end, end):
            covered.add(day)
            day += timedelta(days=1)
    return covered


def _audit_window(details: Any) -> Optional[tuple[date, date]]:
    raw = details.get("oof_window") if isinstance(details, dict) else None
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        return date.fromisoformat(str(raw[0])), date.fromisoformat(str(raw[1]))
    except ValueError:
        return None


async def from_custom_oof(
    db: AsyncSession,
    *,
    user: User,
    setting: Optional[dict[str, Any]],
    today: date,
) -> dict[str, int]:
    """Wnioski z własnej autoodpowiedzi jednej skrzynki; zwraca liczniki przebiegu."""

    window = oof_state.custom_absence_window(setting)
    if window is None:
        return {"custom_oof_without_dates": 1}
    profile = await people.profile_of(db, user.id)
    if profile is None or profile.employment_status == EmploymentStatus.exited:
        return {"custom_oof_no_profile": 1}
    start, end = window
    calendar = await load_calendar(db, start, end)
    covered = await _covered_days(db, user.id, start, end)
    counts: dict[str, int] = {}
    for run_start, run_end in missing_runs(calendar.working_days(start, end), covered):
        outcome = await _create(
            db,
            user=user,
            profile=profile,
            start=run_start,
            end=run_end,
            window=window,
            today=today,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    if not counts:
        counts["custom_oof_covered"] = 1
    return counts


async def _create(
    db: AsyncSession,
    *,
    user: User,
    profile: EmployeeProfile,
    start: date,
    end: date,
    window: tuple[date, date],
    today: date,
) -> str:
    """Jeden wniosek z odcinka; zwraca nazwę licznika (``oof_request_created`` albo powód pominięcia)."""

    form = profile.employment_type
    reported = reports_absence(form)
    try:
        validate_shape(
            leave_type=LEAVE_TYPE,
            start=start,
            end=end,
            half_day=None,
            employment_type=form,
            for_self=True,
        )
    except LeavePolicyError:
        return "oof_request_invalid"
    calendar = await load_calendar(db, start, end)
    days = requested_days(calendar, start, end, None)
    # Ta sama kolejka co przy złożeniu wniosku (pula liczona przed zapisem).
    await db.execute(
        select(EmployeeProfile.id)
        .where(EmployeeProfile.user_id == user.id)
        .with_for_update()
    )
    if await overlapping_request(db, user_id=user.id, start=start, end=end):
        return "oof_request_overlap"
    if reported:
        from app.services.hr import time_hooks

        months = await time_hooks.sent_months(
            db, user.id, [day for day, _ in days], lock=True
        )
        if sent_timesheet_refusal(form, months) is not None:
            return "oof_request_sent_timesheet"
    pools = await pools_for(db, user.id, years_between(start, end))
    try:
        plan = plan_days(
            leave_type=LEAVE_TYPE, employment_type=form, days=days, pools=pools
        )
    except LeavePolicyError:
        return "oof_request_over_limit"

    now = datetime.now(timezone.utc)
    request = LeaveRequest(
        id=uuid.uuid4(),
        user_id=user.id,
        leave_type=LEAVE_TYPE,
        status="approved" if reported else "pending",
        start_date=start,
        end_date=end,
        half_day=None,
        note=note_for(window[0], window[1], reported=reported),
        substitute_user_id=None,
        forward_mail_consent=False,
        paid_days=plan.paid,
        unpaid_days=plan.unpaid,
        decided_by=None,
        decided_at=now if reported else None,
        created_by=None,
        source=SOURCE,
    )
    try:
        async with db.begin_nested():
            db.add(request)
            await db.flush()
            db.add_all(
                LeaveRequestDay(
                    leave_request_id=request.id,
                    user_id=user.id,
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
            return "oof_request_overlap"
        raise

    span = format_range(start, end)
    days_text = days_label(plan.total)
    audit_request(
        db,
        actor_id=None,
        request=request,
        action=ACTION,
        extra={
            "days": f"{plan.total:.1f}",
            "oof_window": [window[0].isoformat(), window[1].isoformat()],
            **({"flow": "report"} if reported else {}),
        },
    )
    if not reported:
        await notify_requested(
            db,
            subject=user,
            profile=profile,
            leave_type=LEAVE_TYPE,
            span=span,
            days_text=days_text,
            today=today,
            request_id=request.id,
        )
        return "oof_request_created"

    await notify_reported(
        db, subject=user, profile=profile, span=span, days_text=days_text, today=today
    )
    await notify(
        db,
        await people_admin_ids(db),
        exclude={user.id},
        title="Nieobecność z autoodpowiedzi w Outlooku",
        message=(
            f"{user.name}: {span} ({days_text}) — wpisane z autoodpowiedzi, "
            "bez zgłoszenia w NEXUSIE."
        ),
        ntype=NotificationType.hr_absence_reported,
        link=LINK_APPROVALS,
    )
    from app.services.hr import time_hooks

    hooked = await time_hooks.on_leave_approved(
        db, user.id, [item.day for item in plan.days]
    )
    await report_payroll_locked(
        db,
        request=request,
        subject=user,
        actor_id=None,
        months=hooked["locked_conflicts"],
        event="approved",
    )
    return "oof_request_created"


__all__ = ["SOURCE", "from_custom_oof", "missing_runs", "note_for"]
