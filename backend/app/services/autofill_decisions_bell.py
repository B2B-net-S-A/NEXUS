"""Poranny dzwonek „Osoby od systemu czekają na Twoją decyzję” (23.10.2026).

Silnik „Nowi na 20” dodaje osoby bez blokady; po 2 dniach roboczych bez
„Dzwonię” ani odrzucenia osoba trafia do „Czeka na Ciebie”
(``board_flow._autofill_decisions``), a Rekruterzy jej rekrutacji dostają
JEDEN dzwonek dziennie: ile osób czeka i w których rekrutacjach. Reguła
terminu jest jedna (``autofill_decisions.due_decisions``), więc dzwonek i lista
na pulpicie liczą to samo.

Kiedy: dni robocze, 8–17 (``BUSINESS_TZ``), pierwszy tick dnia. Stan
``last_sent_on`` w ``app_settings`` przeżywa restart, a dedup dobowy
``emit`` (user + typ + encja) i tak nie przepuści drugiego dzwonka.
Odbiorcy = Rekruterzy rekrutacji (``job_team.working``) — bez uczestników
kategorii (D7). Rekrutacja bez rekrutera nie ma terminu, więc i dzwonka.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.app_setting import AppSetting
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

FROM_HOUR = 8
UNTIL_HOUR = 17
JOBS_IN_MESSAGE = 3
STATE_KEY = "autofill_decisions_bell_state"
LINK = "/dashboard#czeka-na-ciebie"


def people_phrase(count: int) -> str:
    """„1 osoba od systemu czeka”, „3 osoby…”, „12 osób…”."""
    if count == 1:
        return "1 osoba od systemu czeka"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} osoby od systemu czekają"
    return f"{count} osób od systemu czeka"


def bell_title(count: int) -> str:
    return f"{people_phrase(count)} na Twoją decyzję"


def bell_message(per_job: list[tuple[str, int]]) -> str:
    """„Senior Java (3), Analityk (2) i 1 inna rekrutacja. Zadzwoń…”."""
    shown = ", ".join(f"{title} ({n})" for title, n in per_job[:JOBS_IN_MESSAGE])
    rest = len(per_job) - min(len(per_job), JOBS_IN_MESSAGE)
    tail = ""
    if rest == 1:
        tail = " i 1 inna rekrutacja"
    elif rest > 1:
        tail = (
            f" i {rest} inne rekrutacje"
            if rest % 10 in (2, 3, 4) and rest % 100 not in (12, 13, 14)
            else f" i {rest} innych rekrutacji"
        )
    return (
        f"{shown}{tail}. Zadzwoń („Dzwonię”) albo odrzuć z powodem — "
        "powody uczą system."
    )


async def _sent_today(db: AsyncSession, today: str) -> bool:
    row = await db.get(AppSetting, STATE_KEY)
    return bool(row is not None and (row.value or {}).get("last_sent_on") == today)


async def _mark_sent(db: AsyncSession, today: str, now: datetime, jobs: int) -> None:
    value = {
        "last_sent_on": today,
        "last_sent_at": now.astimezone(timezone.utc).isoformat(),
        "jobs": jobs,
    }
    await db.execute(
        pg_insert(AppSetting)
        .values(key=STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": value, "updated_at": datetime.now(timezone.utc)},
        )
    )


async def send_decision_bells(db: AsyncSession, now: datetime) -> int:
    """Wysyła dzwonki (raz dziennie, 8–17). Nie commituje — robi to wołający."""
    local = now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
    if not (FROM_HOUR <= local.hour < UNTIL_HOUR) or not is_business_day(local):
        return 0
    from app.services.autofill_decisions import due_decisions  # noqa: PLC0415
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415
    from app.services.job_working_title import (  # noqa: PLC0415
        job_display_title_expr,
    )
    from app.services.notification_triggers import emit  # noqa: PLC0415

    today = local.date().isoformat()
    try:
        async with db.begin_nested():
            if await _sent_today(db, today):
                return 0
            job_ids = list(
                (
                    await db.scalars(
                        select(Job.id).where(
                            Job.status == JobStatus.published,
                            Job.work_state.in_(IN_WORK_STATES),
                        )
                    )
                ).all()
            )
            due = await due_decisions(db, job_ids, now)
            per_job: dict[int, int] = {}
            for d in due:
                per_job[d.job_id] = per_job.get(d.job_id, 0) + 1
            await _mark_sent(db, today, now, len(per_job))
            if not per_job:
                return 0
            titles = dict(
                (
                    await db.execute(
                        select(Job.id, job_display_title_expr()).where(
                            Job.id.in_(sorted(per_job))
                        )
                    )
                ).all()
            )
            teams = await recruiters_for_jobs(db, sorted(per_job))
    except Exception:  # noqa: BLE001 — dzwonek nigdy nie psuje ticku
        logger.exception("autofill_decisions_bell: nie udało się policzyć planu")
        return 0

    by_user: dict[int, list[tuple[str, int]]] = {}
    for job_id, count in sorted(per_job.items(), key=lambda kv: (-kv[1], kv[0])):
        for user_id in sorted({p.user_id for p in working(teams.get(job_id, []))}):
            by_user.setdefault(user_id, []).append(
                (titles.get(job_id) or f"#{job_id}", count)
            )
    sent = 0
    for user_id, jobs in sorted(by_user.items()):
        total = sum(n for _, n in jobs)
        try:
            async with db.begin_nested():
                created = await emit(
                    db,
                    user_id=user_id,
                    title=bell_title(total),
                    message=bell_message(jobs),
                    ntype=NotificationType.autofill_decisions_due,
                    related_entity_type="user",
                    related_entity_id=user_id,
                    link=LINK,
                )
            sent += int(created is not None)
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
            logger.exception(
                "autofill_decisions_bell: dzwonek nie wyszedł user=%s", user_id
            )
    return sent


__all__ = [
    "LINK",
    "STATE_KEY",
    "bell_message",
    "bell_title",
    "people_phrase",
    "send_decision_bells",
]
