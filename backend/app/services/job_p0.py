"""P0 — rekrutacja ultrapilna przez 24 h (decyzje Artura 27.10.2026).

Prośba Olafa („Omawiane na Daily” — czerwony przycisk na co najmniej 24 h
i lista takich rekrutacji na pulpicie każdego), rozwinięta przez Artura
w poziom ponad P1:

* ustawia Head of Recruitment albo admin, z powodem, który widzą wszyscy;
* trwa 24 h (do wyboru 48 h albo do piątku 18:00), „Przedłuż o 24 h”
  i „Zdejmij P0” w nagłówku rekrutacji; bez limitu naraz;
* P0 to nakładka z terminem nad ``jobs.priority`` — po terminie po prostu
  przestaje obowiązywać (bez pętli w tle), a zespół nie przechodzi do
  „Poprzedni rekruter”, bo priorytet się nie zmienia;
* P0 stoi na górze listy rekrutacji, tablicy requestów i Daily niezależnie
  od sortowania; automat przydziału traktuje je jak P1; champion go nie
  wstrzymuje — to świadoma decyzja człowieka na krótki czas;
* przy ustawieniu dzwonek i mail obowiązkowy dostają rekruterzy i Delivery
  Lead rekrutacji (bez osoby, która ustawiła).

Reguła: ``docs/claude/rekrutacja-tablica/p0-ultrapilne-24-h.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

P0Duration = Literal["24h", "48h", "friday"]
P0_DURATIONS: tuple[str, ...] = ("24h", "48h", "friday")
EXTEND_BY = timedelta(hours=24)
REASON_MIN = 3
REASON_MAX = 300
# Do piątku = do końca dnia pracy w piątek (Warszawa).
FRIDAY_END_HOUR = 18

P0_ROLES: tuple[UserRole, ...] = (UserRole.admin, UserRole.head_of_recruitment)
SET_DENIED = "P0 ustawia Head of Recruitment albo administrator."

ACTION_SET = "p0_set"
ACTION_EXTENDED = "p0_extended"
ACTION_CLEARED = "p0_cleared"


@dataclass(frozen=True)
class P0Error(Exception):
    status: int
    detail: str


def can_set_p0(user: Any) -> bool:
    return bool(user is not None and user.has_any_role(*P0_ROLES))


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def until_for(duration: str, now: datetime) -> datetime:
    """Koniec P0 dla wybranego czasu; ``now`` w UTC."""
    if duration == "24h":
        return now + timedelta(hours=24)
    if duration == "48h":
        return now + timedelta(hours=48)
    if duration == "friday":
        zone = ZoneInfo(DEFAULT_TZ)
        local = now.astimezone(zone)
        friday = local.date() + timedelta(days=(4 - local.weekday()) % 7)
        end = datetime(
            friday.year, friday.month, friday.day, FRIDAY_END_HOUR, tzinfo=zone
        )
        if end <= local:
            end += timedelta(days=7)
        return end.astimezone(timezone.utc)
    raise P0Error(422, "Nieznany czas P0 — wybierz 24 h, 48 h albo „do piątku”.")


def normalize_reason(raw: Optional[str]) -> str:
    reason = re.sub(r"\s+", " ", raw or "").strip()
    if len(reason) < REASON_MIN:
        raise P0Error(422, "Napisz, po co P0 — zobaczą to wszyscy.")
    if len(reason) > REASON_MAX:
        raise P0Error(422, f"Powód P0 może mieć najwyżej {REASON_MAX} znaków.")
    return reason


def is_active(job: Any, now: Optional[datetime] = None) -> bool:
    until = getattr(job, "p0_until", None)
    if until is None or getattr(job, "status", None) != JobStatus.published:
        return False
    return _utc(until) > (now or datetime.now(timezone.utc))


def active_clause():
    """SQL: rekrutacja otwarta z P0, którego termin jeszcze nie minął."""
    return and_(
        Job.p0_until.is_not(None),
        Job.p0_until > func.now(),
        Job.status == JobStatus.published,
    )


def p0_rank_expr():
    """Pierwszy klucz sortowania list: 0 = aktywne P0, 1 = reszta."""
    return case((active_clause(), 0), else_=1)


def fields(job: Any, *, set_by_name: Optional[str] = None) -> dict[str, Any]:
    """Pola P0 do odpowiedzi API; po terminie — puste."""
    if not is_active(job):
        return {
            "is_p0": False,
            "p0_until": None,
            "p0_reason": None,
            "p0_set_at": None,
            "p0_set_by_name": None,
        }
    return {
        "is_p0": True,
        "p0_until": job.p0_until,
        "p0_reason": job.p0_reason,
        "p0_set_at": job.p0_set_at,
        "p0_set_by_name": set_by_name,
    }


def _require_open(job: Job) -> None:
    if job.status != JobStatus.published:
        raise P0Error(409, "P0 ustawia się tylko otwartej rekrutacji.")


async def set_p0(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    reason: Optional[str],
    duration: str = "24h",
    now: Optional[datetime] = None,
) -> None:
    """Ustawia (albo nadpisuje) P0 z nowym powodem i terminem."""
    _require_open(job)
    clean = normalize_reason(reason)
    now = now or datetime.now(timezone.utc)
    job.p0_until = until_for(duration, now)
    job.p0_reason = clean
    job.p0_set_at = now
    job.p0_set_by = actor_id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=ACTION_SET,
            user_id=actor_id,
            details={
                "until": job.p0_until.isoformat(),
                "duration": duration,
                "reason": clean,
            },
        )
    )
    await db.flush()


async def extend_p0(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    now: Optional[datetime] = None,
) -> None:
    """„Przedłuż o 24 h” — od obecnego terminu, nie od teraz."""
    _require_open(job)
    now = now or datetime.now(timezone.utc)
    if not is_active(job, now):
        raise P0Error(409, "P0 już nie obowiązuje — ustaw je od nowa z powodem.")
    job.p0_until = _utc(job.p0_until) + EXTEND_BY
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=ACTION_EXTENDED,
            user_id=actor_id,
            details={"until": job.p0_until.isoformat()},
        )
    )
    await db.flush()


async def clear_p0(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    """„Zdejmij P0”. ``False``, gdy P0 już nie obowiązywało."""
    active = is_active(job, now)
    job.p0_until = None
    job.p0_reason = None
    job.p0_set_at = None
    job.p0_set_by = None
    if active:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action=ACTION_CLEARED,
                user_id=actor_id,
                details={},
            )
        )
    await db.flush()
    return active


async def team_recipients(
    db: AsyncSession, job: Job, *, actor_id: Optional[int]
) -> list[int]:
    """Rekruterzy pracujący nad rekrutacją i jej Delivery Lead, bez autora."""
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415

    team = working((await recruiters_for_jobs(db, [job.id])).get(job.id, []))
    ids = [person.user_id for person in team]
    if job.delivery_lead_id is not None:
        ids.append(job.delivery_lead_id)
    return [uid for uid in dict.fromkeys(ids) if uid != actor_id]


def _local_label(moment: datetime) -> str:
    return _utc(moment).astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m %H:%M")


async def notify_set(
    db: AsyncSession, job: Job, *, actor_id: Optional[int]
) -> list[int]:
    """Dzwonek (i mail obowiązkowy z kolejki) do zespołu rekrutacji.

    Savepoint na osobę: nieudane powiadomienie nie cofa ustawienia P0.
    """
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    recipients = await team_recipients(db, job, actor_id=actor_id)
    if not recipients:
        return []
    client_name = await db.scalar(
        select(func.coalesce(Client.display_name, Client.name)).where(
            Client.id == job.client_id
        )
    )
    actor_name = (
        await db.scalar(select(User.name).where(User.id == actor_id))
        if actor_id is not None
        else None
    )
    title = f"P0: ultrapilne do {_local_label(job.p0_until)}"
    head = display_title(job)
    head = f"{head} · {client_name}" if client_name else head
    who = f" — {actor_name}" if actor_name else ""
    message = f"{head}. Powód: {job.p0_reason}{who}."
    sent: list[int] = []
    for user_id in recipients:
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.job_p0_set,
                    related_entity_type="job",
                    related_entity_id=job.id,
                    link=f"/jobs/{job.id}",
                )
            if row is not None:
                sent.append(user_id)
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć P0
            logger.exception(
                "job_p0: dzwonek dla user_id=%s job_id=%s nie powstał",
                user_id,
                job.id,
            )
    return sent


async def set_by_name(db: AsyncSession, job: Job) -> Optional[str]:
    if job.p0_set_by is None or not is_active(job):
        return None
    return await db.scalar(select(User.name).where(User.id == job.p0_set_by))


async def list_active(db: AsyncSession) -> list[dict[str, Any]]:
    """Aktywne P0 dla górnego paska i pulpitu — najbliższy koniec najpierw."""
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415
    from app.services.job_working_title import job_display_title_expr  # noqa: PLC0415

    setter = User.__table__.alias("p0_setter")
    lead = User.__table__.alias("p0_lead")
    rows = (
        await db.execute(
            select(
                Job.id,
                job_display_title_expr(),
                func.coalesce(Client.display_name, Client.name),
                Job.p0_until,
                Job.p0_reason,
                Job.p0_set_at,
                setter.c.name,
                lead.c.name,
            )
            .select_from(Job)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(setter, setter.c.id == Job.p0_set_by)
            .outerjoin(lead, lead.c.id == Job.delivery_lead_id)
            .where(active_clause())
            .order_by(Job.p0_until.asc(), Job.id.asc())
        )
    ).all()
    teams = await recruiters_for_jobs(db, [row[0] for row in rows])
    return [
        {
            "job_id": row[0],
            "title": row[1],
            "client_name": row[2],
            "p0_until": row[3],
            "p0_reason": row[4],
            "p0_set_at": row[5],
            "p0_set_by_name": row[6],
            "delivery_lead_name": row[7],
            "recruiters": [person.name for person in working(teams.get(row[0], []))],
        }
        for row in rows
    ]
