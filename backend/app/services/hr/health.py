"""Sondy `/api/health` modułów „Ludzi w NEXUSIE” — kolejka M365, czytnik administracja@, zadania HR.

Każda sonda zwraca ``disabled`` (funkcja wyłączona konfiguracją), ``healthy``
albo ``degraded``. Sondy są informacyjne: nie zmieniają ogólnego statusu
(ten liczy się z bazy), tylko pokazują po wdrożeniu i przy przełączeniu, że coś
utknęło — bez zaglądania w logi.

* ``hr_m365`` — operacje Graph dla urlopów: ``failed`` z ostatnich 7 dni albo
  ``pending`` po terminie dłużej niż 30 min (wykonawca biegnie co 60 s),
* ``admin_cases_mail`` — czytnik skrzynki: ostatni przebieg z błędem albo
  starszy niż 30 min (pętla co 5 min),
* ``hr_jobs`` — rezerwacje ``hr_job_runs``: ``failed`` z ostatniej doby albo
  ``claimed`` bez końca dłużej niż 2 h (przebieg zabity w połowie).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.admin_case import AdminMailIngestState
from app.models.hr_leave import HrM365Operation
from app.models.hr_ops import HrJobRun

M365_FAILED_WINDOW = timedelta(days=7)
M365_OVERDUE_GRACE = timedelta(minutes=30)
MAIL_STALE_AFTER = timedelta(minutes=30)
JOBS_FAILED_WINDOW = timedelta(days=1)
JOBS_STUCK_AFTER = timedelta(hours=2)


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


async def m365_state(db: AsyncSession, *, now: Optional[datetime] = None) -> str:
    from app.services.hr.m365.executor import current_mode

    if current_mode() == "off":
        return "disabled"
    moment = _now(now)
    problems = await db.scalar(
        select(func.count())
        .select_from(HrM365Operation)
        .where(
            or_(
                and_(
                    HrM365Operation.status == "failed",
                    HrM365Operation.created_at >= moment - M365_FAILED_WINDOW,
                ),
                and_(
                    HrM365Operation.status == "pending",
                    HrM365Operation.next_attempt_at < moment - M365_OVERDUE_GRACE,
                ),
            )
        )
    )
    return "degraded" if problems else "healthy"


async def admin_cases_mail_state(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> str:
    from app.services.admin_cases.mail_ingest import ingest_enabled
    from app.services.hr.modules import load_modules

    if not ingest_enabled() or not (await load_modules(db)).get("cases"):
        return "disabled"
    state = await db.scalar(select(AdminMailIngestState).limit(1))
    if state is None or state.last_run_finished_at is None:
        return "degraded"
    if state.last_status == "error":
        return "degraded"
    if state.last_run_finished_at < _now(now) - MAIL_STALE_AFTER:
        return "degraded"
    return "healthy"


async def hr_jobs_state(db: AsyncSession, *, now: Optional[datetime] = None) -> str:
    if not settings.HR_LOOPS_ENABLED:
        return "disabled"
    moment = _now(now)
    problems = await db.scalar(
        select(func.count())
        .select_from(HrJobRun)
        .where(
            or_(
                and_(
                    HrJobRun.status == "failed",
                    HrJobRun.claimed_at >= moment - JOBS_FAILED_WINDOW,
                ),
                and_(
                    HrJobRun.status == "claimed",
                    HrJobRun.finished_at.is_(None),
                    HrJobRun.claimed_at < moment - JOBS_STUCK_AFTER,
                ),
            )
        )
    )
    return "degraded" if problems else "healthy"


PROBES = (
    ("hr_m365", m365_state),
    ("admin_cases_mail", admin_cases_mail_state),
    ("hr_jobs", hr_jobs_state),
)
