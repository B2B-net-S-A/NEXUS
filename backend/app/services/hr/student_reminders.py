"""Koniec zwolnienia ze składek ucznia/studenta na zleceniu (etap 2, D8).

Uczeń albo student do 26 lat na umowie zlecenie nie płaci składek ZUS z tej
umowy do końca statusu (obrona, skreślenie) albo do dnia przed 26. urodzinami
— co pierwsze. NEXUS nie przechowuje daty urodzenia: Kadry wpisują jedną datę
``contribution_exempt_until`` (wcześniejszą z dwóch). 30 dni przed nią Płace
(uprawnienie „Płace”) i Kadry dostają przypomnienie, bo przeoczony koniec
statusu oznacza zaległe składki.

Raz na osobę i datę: rezerwacja w ``hr_job_runs`` (``kind`` + ``period_key`` =
osoba i data), więc kolejne przebiegi pętli i restart przy nocnym wdrożeniu dają
jedno przypomnienie; nowa data (przedłużona legitymacja) — nowe przypomnienie.
Okno to 30 dni przed datą aż do niej włącznie: pętla, która nie biegła w dniu
„−30”, przypomni dzień później. Typ ``hr_lifecycle_task`` (zadanie Kadr),
tytuł i treść bez kwot.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_ops import HrJobRun
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.hr import job_runs
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each
from app.services.hr_foundation_schema import EmploymentStatus, EmploymentType

logger = logging.getLogger(__name__)

JOB_KIND = "hr_student_contribution_reminder"
LEAD_DAYS = 30
SEND_FROM_HOUR = 8


def period_key(user_id: int, until: date) -> str:
    return f"u{user_id}:{until.isoformat()}"


async def due_people(db: AsyncSession, today: date) -> list[tuple[int, str, date]]:
    """Osoby na zleceniu ze znacznikiem, którym zwolnienie kończy się w 30 dni."""

    rows = await db.execute(
        select(
            EmployeeProfile.user_id,
            User.name,
            EmployeeProfile.contribution_exempt_until,
        )
        .join(User, User.id == EmployeeProfile.user_id)
        .where(
            User.is_active.is_(True),
            EmployeeProfile.employment_type == EmploymentType.zlecenie,
            EmployeeProfile.employment_status != EmploymentStatus.exited,
            EmployeeProfile.student_contribution_exempt.is_(True),
            EmployeeProfile.contribution_exempt_until.is_not(None),
            EmployeeProfile.contribution_exempt_until >= today,
            EmployeeProfile.contribution_exempt_until
            <= today + timedelta(days=LEAD_DAYS),
        )
        .order_by(EmployeeProfile.contribution_exempt_until, EmployeeProfile.user_id)
    )
    return [(user_id, name, until) for user_id, name, until in rows.all()]


async def recipient_ids(db: AsyncSession) -> list[int]:
    """Płace (bez adminów, gdy są inni) i Kadry (bez Kadr — admini)."""

    from app.services.hr.leave_service import people_admin_ids
    from app.services.hr.time_access import users_with_permission

    payroll = [
        user.id
        for user in await users_with_permission(db, ProductAction.payroll)
        if not user.has_role(UserRole.admin)
    ]
    return list(dict.fromkeys([*payroll, *await people_admin_ids(db)]))


async def student_contribution_reminders(
    db: AsyncSession, *, today: Optional[date] = None
) -> dict[str, Any]:
    """Jeden przebieg (dzienna pętla HR); idempotentny, commituje sam."""

    from app.services.hr import modules as hr_modules

    loaded = await hr_modules.load_modules(db)
    if not (loaded.get(HrModule.people) or loaded.get(HrModule.payroll)):
        return {"status": "disabled"}
    if today is None:
        now = local_now()
        if now.hour < SEND_FROM_HOUR:
            return {"status": "before_hours", "sent": 0}
        today = now.date()
    due = await due_people(db, today)
    counts = {"due": len(due), "sent": 0, "already": 0, "skipped": 0}
    if not due:
        return {"status": "ok", **counts}
    recipients = await recipient_ids(db)
    for user_id, name, until in due:
        key = period_key(user_id, until)
        if not await job_runs.mark_once(db, JOB_KIND, key, status="claimed"):
            counts["already"] += 1
            continue
        start = until + timedelta(days=1)
        notified = await notify_each(
            db,
            recipients,
            exclude=[user_id],
            title=f"Koniec zwolnienia ze składek: {name}",
            message=(
                f"Zlecenie, uczeń lub student — zwolnienie ze składek "
                f"ZUS do {until:%d.%m.%Y}. Od {start:%d.%m.%Y} naliczamy "
                "składki, chyba że Kadry przesuną datę (nowa legitymacja)."
            ),
            ntype=NotificationType.hr_lifecycle_task,
            link=f"/people/{user_id}",
            related_entity_type="employee_profile",
            log_tag="hr_student",
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
    logger.info("[hr_student] przypomnienia o składkach: %s", counts)
    return {"status": "ok", **counts}


__all__ = [
    "JOB_KIND",
    "LEAD_DAYS",
    "due_people",
    "period_key",
    "recipient_ids",
    "student_contribution_reminders",
]
