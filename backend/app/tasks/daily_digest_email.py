"""Poranny skrót mailem „Twój dzień w NEXUSIE” (07.10.2026).

Dzień roboczy od 8:00 (`BUSINESS_TZ`, nie później niż 17:00) każda osoba
z rolą operacyjną dostaje JEDEN mail z tym, co dziś na nią czeka — tą samą
kolejką co panel „Czeka na Ciebie” na pulpicie
(`api/board_tasks.build_board_tasks`), plus otwarte sprawy klientów DL
i terminy rekrutacji w 7 dni. Pusty skrót nie wychodzi.

Rezerwacja dnia, postęp wysyłki i ponowienia po restarcie (deploy w trakcie)
to mechanizm raportów KPI (`tasks/kpi_email_reports._send_report`): wiersz
`kpi_email_report_runs` (kind=`daily_digest`, period_key=data) i lista
oczekujących adresów w `app_settings`. Wynik niepewny nie jest ponawiany.
Rodzaj `daily_digest` włącza admin w Ustawieniach → Powiadomienia.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, is_business_day, local_now
from app.models.dl_alert import DL_ALERT_STATUS_NEW, DlAlert
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import daily_digest, loop_heartbeat
from app.services.dl_alerts import client_not_deleted_clause
from app.services.effective_access import resolve_effective_access
from app.services.job_team import jobs_worked_by_clause
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.tasks import kpi_email_reports as reports

logger = logging.getLogger(__name__)

KIND = "daily_digest"
SEND_FROM_HOUR = 8
SEND_UNTIL_HOUR = 17
CHECK_INTERVAL_SECONDS = 300
DEADLINE_DAYS = 7

# Kto dostaje skrót — rola główna albo dodatkowa. Admin bez tych ról nie:
# jego sprawy (awarie) idą mailem natychmiast (`system_failure`).
DIGEST_ROLES = (
    UserRole.recruiter,
    UserRole.talent_community_manager,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
    UserRole.finance,
)


def period_key(now_local: datetime) -> Optional[str]:
    """Klucz dnia, gdy skrót jest należny; `None` poza oknem i w dni wolne."""
    if not is_business_day(now_local):
        return None
    if not SEND_FROM_HOUR <= now_local.hour < SEND_UNTIL_HOUR:
        return None
    return now_local.date().isoformat()


async def _recipients(db: AsyncSession) -> list[User]:
    users = list(
        (
            await db.execute(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.email.is_not(None),
                    reports._has_any_role(DIGEST_ROLES),
                )
                .order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    for start in range(0, len(users), reports._ACCESS_BATCH):
        await resolve_effective_access(db, users[start : start + reports._ACCESS_BATCH])
    return with_pipeline_read(users)


def with_pipeline_read(users: list[User]) -> list[User]:
    """Tylko konta z odczytem sekcji Pipeline — lustro bramki `/api/board-tasks`.

    Kolejka „Czeka na Ciebie” niesie nazwiska kandydatów, a jej loadery nie
    sprawdzają sekcji same (robi to router). Konto, któremu admin odebrał
    Pipeline, nie może ich dostać mailem.
    """
    return [
        u
        for u in users
        if section_access_for_user(u, ProductSection.pipeline) >= SectionAccess.read
    ]


async def _open_client_cases(db: AsyncSession, user_id: int) -> int:
    """Otwarte sprawy panelu „Moi klienci” (jedna karta na `event_key`)."""
    return int(
        await db.scalar(
            select(
                func.count(
                    func.distinct(
                        func.coalesce(DlAlert.event_key, cast(DlAlert.id, String))
                    )
                )
            ).where(
                DlAlert.user_id == user_id,
                DlAlert.status == DL_ALERT_STATUS_NEW,
                client_not_deleted_clause(DlAlert.client_id),
            )
        )
        or 0
    )


async def _deadlines(db: AsyncSession, user_id: int, today) -> tuple:
    rows = await db.execute(
        select(Job.id, func.coalesce(Job.working_title, Job.title), Job.deadline)
        .where(
            Job.status == JobStatus.published,
            Job.deadline.is_not(None),
            Job.deadline >= today,
            Job.deadline <= today + timedelta(days=DEADLINE_DAYS),
            jobs_worked_by_clause([user_id]),
        )
        .order_by(Job.deadline, Job.id)
    )
    return tuple((job_id, title, day) for job_id, title, day in rows.all())


async def _mail_for(db: AsyncSession, user: User, today) -> Optional[reports._Mail]:
    from app.api.board_tasks import build_board_tasks

    tasks = await build_board_tasks(db, user)
    is_dl = user.has_any_role(UserRole.delivery_lead)
    sections = daily_digest.build_sections(
        tasks,
        open_client_cases=await _open_client_cases(db, user.id) if is_dl else 0,
        deadlines=await _deadlines(db, user.id, today),
    )
    if not sections:
        return None
    subject, text, html = daily_digest.render(user.name or user.email, sections, today)
    return reports._Mail(user.email, subject, text, html)


async def _digest_mails(db: AsyncSession, now_local: datetime) -> list[reports._Mail]:
    today = now_local.date()
    mails: list[reports._Mail] = []
    for user in await _recipients(db):
        # Jedna osoba nie może zatrzymać skrótu reszty zespołu.
        try:
            async with db.begin_nested():
                mail = await _mail_for(db, user, today)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "daily_digest_email: skrót user=%d pominięty: %s",
                user.id,
                type(exc).__name__,
            )
            continue
        if mail is not None:
            mails.append(mail)
    return mails


async def run_once(now: Optional[datetime] = None) -> str:
    now_local = (now or local_now()).astimezone(ZoneInfo(DEFAULT_TZ))
    key = period_key(now_local)
    if key is None:
        return "not_due"
    return await reports._send_report(
        KIND,
        key,
        lambda db: _digest_mails(db, now_local),
        now_local.astimezone(timezone.utc),
    )


async def daily_digest_email_loop() -> None:
    if not settings.DAILY_DIGEST_EMAIL_ENABLED:
        logger.info("daily_digest_email disabled")
        return
    beat = loop_heartbeat.register(
        "daily_digest_email", max_silence_seconds=CHECK_INTERVAL_SECONDS + 3600
    )
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("daily_digest_email_loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
