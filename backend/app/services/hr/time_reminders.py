"""Przypomnienie o timesheecie za zamknięty miesiąc (``hr_timesheet_reminder``).

Okno 1.–5. dnia miesiąca (kalendarz firmy, od 8:00), dotyczy POPRZEDNIEGO miesiąca —
termin wysłania to 5. dzień. Raz na osobę i miesiąc: rezerwacja w
``hr_job_runs`` (``kind`` + ``period_key`` = miesiąc i osoba), więc pięć
przebiegów w oknie i restart przy nocnym wdrożeniu dają jedno powiadomienie.

Kogo dotyczy: osoba z kartoteką i ``timesheet_required``, aktywnym kontem,
zatrudniona w rozliczanym miesiącu (start przed jego końcem, ostatni dzień
pracy nie przed jego początkiem), bez wysłanego timesheetu. Naprawy Compassa:
przypomnienie dostawały tylko role ``internal`` i ``admin`` (przełożeni,
Finanse i TCM, którzy też prowadzą timesheet, nie), a osoby, które odeszły,
nie były wykluczane.

„Przypomnij” z ekranu (``remind_one``, 19.10.2026): Płace, Kadry, admin albo
akceptujący tej osoby wysyłają jedno przypomnienie o timesheecie wskazanego
miesiąca — osobie, gdy raport jest szkicem albo go nie ma, a akceptującym
(``approval_recipients``), gdy czeka na akceptację. Raz dziennie na osobę,
miesiąc i adresata: rezerwacja ``hr_job_runs`` (``JOB_KIND_MANUAL``), drugi
klik tego dnia nic nie wysyła i odpowiada ``already_today``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_ops import HrJobRun
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import audit, job_runs, people
from app.services.hr.employment_terms import terms
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each
from app.services.hr.time_access import Actor, approval_recipients
from app.services.hr.time_calendar import (
    DEADLINE_DAY,
    month_range,
    previous_month,
    submission_deadline,
)
from app.services.hr.time_entries import (
    TimeConflict,
    TimeForbidden,
    TimeNotFound,
    find_timesheet,
    validate_period,
)
from app.services.hr.time_flow import approvals_link, month_label, my_month_link
from app.services.hr.time_month import TIMESHEET_EMPLOYMENT_STATUSES

logger = logging.getLogger(__name__)

JOB_KIND = "hr_timesheet_reminder"
#: „Przypomnij” z ekranu — osobna rezerwacja, bo dzienna, nie miesięczna.
JOB_KIND_MANUAL = "hr_timesheet_manual_reminder"
#: Dzwonek w godzinach pracy, nie o północy pierwszego dnia miesiąca.
SEND_FROM_HOUR = 8


def in_window(today: date) -> bool:
    return today.day <= DEADLINE_DAY


def period_key(year: int, month: int, user_id: int) -> str:
    return f"{year}-{month:02d}:u{user_id}"


async def eligible_user_ids(db: AsyncSession, year: int, month: int) -> list[int]:
    start, end = month_range(year, month)
    rows = await db.execute(
        select(EmployeeProfile.user_id)
        .join(User, User.id == EmployeeProfile.user_id)
        .outerjoin(
            Timesheet,
            (Timesheet.user_id == EmployeeProfile.user_id)
            & (Timesheet.year == year)
            & (Timesheet.month == month),
        )
        .where(
            User.is_active.is_(True),
            EmployeeProfile.timesheet_required.is_(True),
            EmployeeProfile.employment_status.in_(TIMESHEET_EMPLOYMENT_STATUSES),
            (EmployeeProfile.work_start_date.is_(None))
            | (EmployeeProfile.work_start_date <= end),
            (EmployeeProfile.last_working_day.is_(None))
            | (EmployeeProfile.last_working_day >= start),
            (Timesheet.id.is_(None)) | (Timesheet.status == "draft"),
        )
        .order_by(EmployeeProfile.user_id)
    )
    return [user_id for (user_id,) in rows.all()]


async def run_once(db: AsyncSession, *, today: Optional[date] = None) -> dict[str, Any]:
    """Jeden przebieg (pętla dzienna HR); idempotentny, commituje sam."""

    from app.services.hr import modules as hr_modules

    if not (await hr_modules.load_modules(db)).get(HrModule.time):
        return {"status": "disabled"}
    if today is None:
        now = local_now()
        if now.hour < SEND_FROM_HOUR:
            return {"status": "before_hours", "sent": 0}
        today = now.date()
    if not in_window(today):
        return {"status": "outside_window", "sent": 0}
    year, month = previous_month(today.year, today.month)
    deadline = submission_deadline(year, month)
    label = month_label(year, month)
    counts = {"eligible": 0, "sent": 0, "already": 0, "skipped": 0}
    ids = await eligible_user_ids(db, year, month)
    forms = dict(
        (
            await db.execute(
                select(EmployeeProfile.user_id, EmployeeProfile.employment_type).where(
                    EmployeeProfile.user_id.in_(ids or [-1])
                )
            )
        ).all()
    )
    for user_id in ids:
        counts["eligible"] += 1
        key = period_key(year, month, user_id)
        if not await job_runs.mark_once(db, JOB_KIND, key, status="claimed"):
            counts["already"] += 1
            continue
        # Słowa formy (D4): ewidencja czasu pracy, raport godzin, potwierdzenie godzin.
        words = terms(forms.get(user_id))
        notified = await notify_each(
            db,
            [user_id],
            title=f"Wyślij {words['timesheet_accusative']}",
            message=f"{words['timesheet']} za {label} czeka na wysłanie — "
            f"termin {deadline.day}.{deadline.month:02d}.",
            ntype=NotificationType.hr_timesheet_reminder,
            link=my_month_link(year, month),
            related_entity_type="timesheet",
            log_tag="hr_time",
        )
        await db.execute(
            update(HrJobRun)
            .where(HrJobRun.kind == JOB_KIND, HrJobRun.period_key == key)
            .values(
                status="done" if notified else "skipped",
                counts={"notified": notified},
                finished_at=local_now(),
            )
        )
        counts["sent" if notified else "skipped"] += 1
    await db.commit()
    logger.info("[hr_time] przypomnienia %s-%02d: %s", year, month, counts)
    return {"status": "ok", "period": f"{year}-{month:02d}", **counts}


# ── „Przypomnij” z ekranu (Płace, Akceptacje) ─────────────────────────────────


def manual_key(year: int, month: int, user_id: int, target: str, day: date) -> str:
    return f"{year}-{month:02d}:u{user_id}:{target}:{day.isoformat()}"


async def remind_one(
    db: AsyncSession,
    *,
    actor: Actor,
    user_id: int,
    year: int,
    month: int,
    today: date,
) -> dict[str, Any]:
    """Jedno przypomnienie o timesheecie osoby za miesiąc (bez commitu).

    Szkic albo brak timesheetu → osoba („wyślij”); wysłany → akceptujący
    („czeka na akceptację”). Przyjęty, zamknięty w płacach albo osoba bez
    obowiązku raportu = 409. Osoba spoza zakresu = 404 (bez zdradzania, że jest).
    """

    validate_period(year, month)
    if user_id == actor.user_id:
        raise TimeForbidden("Sobie nie przypominasz — raport wysyłasz w „Moim czasie”.")
    profile = await people.profile_of(db, user_id)
    if profile is None or not (
        actor.payroll or actor.approves_everyone or actor.can_approve(profile)
    ):
        raise TimeNotFound("Nie ma takiej osoby w Twoim zakresie.")
    words = terms(profile.employment_type)
    if not profile.timesheet_required:
        raise TimeConflict(
            f"Ta osoba nie składa {words['timesheet_genitive']} — nie ma o czym przypominać."
        )
    person = await db.get(User, user_id)
    if person is None or not person.is_active:
        raise TimeConflict("Konto tej osoby jest wyłączone.")
    timesheet = await find_timesheet(db, user_id, year, month)
    # Także bez timesheetu: raport założony w zamkniętym miesiącu od razu ma
    # ``payroll_locked``, więc przypomnienie byłoby niewykonalne (audyt 21.10).
    from app.services.hr import payroll_periods

    if (timesheet is not None and timesheet.payroll_locked) or (
        timesheet is None and await payroll_periods.is_closed(db, year, month)
    ):
        raise TimeConflict(
            "Miesiąc jest zamknięty w płacach — raport jest już rozliczony."
        )
    status = timesheet.status if timesheet is not None else "draft"
    if status == "approved":
        raise TimeConflict(
            f"{words['timesheet']} za {month_label(year, month)} jest już przyjęty."
        )
    label = month_label(year, month)
    if status == "draft":
        target = "person"
        recipients = [user_id]
        deadline = submission_deadline(year, month)
        title = f"Przypomnienie: wyślij {words['timesheet_accusative']}"
        message = (
            f"{words['timesheet']} za {label} czeka na wysłanie — "
            f"termin {deadline.day}.{deadline.month:02d}."
        )
        ntype = NotificationType.hr_timesheet_reminder
        link = my_month_link(year, month)
    else:
        target = "approver"
        approvers = await approval_recipients(db, user_id)
        recipients = [uid for uid in approvers if uid != actor.user_id]
        if not recipients:
            raise TimeConflict(
                f"{words['timesheet']} czeka na Twoją decyzję — otwórz „Akceptacje”."
            )
        title = f"Przypomnienie — {words['timesheet_submitted_title']}"
        message = f"{person.name}: {label} czeka na {words['review_noun']}."
        ntype = NotificationType.hr_timesheet_submitted
        link = approvals_link(year, month, user_id)

    result: dict[str, Any] = {
        "target": target,
        "status": status if timesheet is not None else "missing",
        "sent": False,
        "already_today": False,
    }
    key = manual_key(year, month, user_id, target, today)
    if not await job_runs.mark_once(db, JOB_KIND_MANUAL, key, status="done"):
        result["already_today"] = True
        return result
    notified = await notify_each(
        db,
        recipients,
        title=title,
        message=message,
        ntype=ntype,
        link=link,
        related_entity_type="timesheet",
        log_tag="hr_time",
    )
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=user_id,
        entity_type="timesheet",
        entity_id=timesheet.id if timesheet is not None else None,
        action="timesheet_reminder_sent",
        details={"year": year, "month": month, "target": target, "notified": notified},
    )
    result["sent"] = notified > 0
    return result
