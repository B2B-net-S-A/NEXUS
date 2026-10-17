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
from app.services.hr import job_runs
from app.services.hr.employment_terms import terms
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each
from app.services.hr.time_calendar import (
    DEADLINE_DAY,
    month_range,
    previous_month,
    submission_deadline,
)
from app.services.hr.time_flow import month_label, my_month_link
from app.services.hr.time_month import TIMESHEET_EMPLOYMENT_STATUSES

logger = logging.getLogger(__name__)

JOB_KIND = "hr_timesheet_reminder"
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
