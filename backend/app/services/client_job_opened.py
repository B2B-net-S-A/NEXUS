"""„Nowa rekrutacja u Twojego klienta” — mail obowiązkowy dla Delivery Leada.

Decyzja Artura 26.10.2026 (maile obowiązkowe, PR 3). Do tej pory DL
dowiadywał się o nowym requeście z jednego zbiorczego dzwonka rano
(``request_review_needed``), a mail nie wychodził wcale.

**Zdarzenie.** Otwarcie rekrutacji to wpis ``Activity`` ``published`` na
rekrutacji: od 04.10.2026 założenie jest publikacją (``job_lifecycle``), tak
samo ponowne otwarcie zamkniętej (``details.reopened``). Kopia produkcji
z 22.10, 14 dni: 56 założonych rekrutacji i 198 ponownych otwarć, każde z tym
wpisem; Traffit nie zakłada rekrutacji od 12.10. Działa tak samo dla ekranu
i konta serwisowego API v1 (wpis bez autora).

**Kto.** Delivery Lead rekrutacji, a bez aktywnego DL-a Head of Recruitment —
ta sama reguła co ``request_allocation_notices.route_to_recipients``. Bez
osoby, która rekrutację otworzyła: 52 z 56 rekrutacji z tych 14 dni założył
ich własny DL, a mail o własnym kliknięciu to szum.

**Kiedy.** Pętla triggerów (co 5 min, dni robocze) zakłada wpis dzwonka
``client_job_opened`` na parę (osoba, rekrutacja) i otwarcie. Kolejka maili
(``tasks/notification_email_outbox``) wysyła je, gdy najstarszy czeka
``GROUP_WINDOW``: wszystko, co zebrało się do tej chwili, idzie jednym mailem
(12.10 ktoś otworzył ponownie 185 rekrutacji naraz). Bez zaległości:
otwarcia sprzed progu „wysyłaj od” tego rodzaju dostają tylko dzwonek.

**Treść.** Nazwa rekrutacji, klient, data otwarcia (z wpisu dzwonka) i kto ją
prowadzi — liczone przy wysyłce, bo automat przydziału rusza po otwarciu.
Rekrutacja zamknięta przed wysyłką z maila wypada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.job_team import recruiters_for_jobs, working
from app.services.job_working_title import display_title
from app.services.notification_delivery import CLIENT_JOB_KIND, load_policy
from app.services.request_allocation_notices import route_to_recipients

logger = logging.getLogger(__name__)

NTYPE = NotificationType.client_job_opened
# Pętla triggerów nie chodzi w weekend — poniedziałek ma dogonić piątek wieczór.
LOOKBACK = timedelta(hours=72)
# Kilka otwarć dla jednej osoby w tym oknie = jeden mail.
GROUP_WINDOW = timedelta(minutes=10)
MAX_LISTED = 5
TITLE = "Nowa rekrutacja u Twojego klienta"
LIST_LINK = "/jobs"


def _day(at: datetime) -> str:
    return at.astimezone(ZoneInfo(settings.BUSINESS_TZ)).strftime("%d.%m.%Y")


def bell_message(
    *, title: str, client: Optional[str], opened_at: datetime, reopened: bool
) -> str:
    """Treść dzwonka: „Tytuł · Klient · otwarta 22.10.2026”."""
    when = (
        f"otwarta ponownie {_day(opened_at)}"
        if reopened
        else f"otwarta {_day(opened_at)}"
    )
    return " · ".join(part for part in (title, client, when) if part)


async def _hor_ids(db: AsyncSession) -> list[int]:
    return sorted(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(
                        User.role == UserRole.head_of_recruitment,
                        User.roles.contains([UserRole.head_of_recruitment.value]),
                    ),
                )
            )
        ).all()
    )


async def emit_opened(db: AsyncSession, now: datetime) -> int:
    """Dzwonki ``client_job_opened`` za otwarcia z ostatnich ``LOOKBACK``.

    Idempotentne: para (osoba, rekrutacja) z wpisem po danym otwarciu nie
    dostaje drugiego. Zwraca liczbę nowych wpisów.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415

    since = now - LOOKBACK
    policy = await load_policy(db)
    cutoff = policy.cutoff_for(CLIENT_JOB_KIND)
    if policy.kind_enabled(CLIENT_JOB_KIND) and cutoff is not None:
        # Bez zaległości: otwarcie sprzed włączenia nie robi maila.
        since = max(since, cutoff)

    events = (
        await db.execute(
            select(
                Activity.entity_id,
                Activity.user_id,
                Activity.created_at,
                Activity.details,
            )
            .where(
                Activity.entity_type == "job",
                Activity.action == "published",
                Activity.created_at >= since,
            )
            .order_by(Activity.created_at.asc(), Activity.id.asc())
        )
    ).all()
    # Ostatnie otwarcie rekrutacji w oknie — ono się liczy.
    latest = {job_id: (actor, at, details) for job_id, actor, at, details in events}
    if not latest:
        return 0

    jobs = {
        job.id: (job, client_name)
        for job, client_name in (
            await db.execute(
                select(Job, Client.name)
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(sorted(latest)), Job.status == JobStatus.published)
            )
        ).all()
    }
    lead_ids = {
        job.delivery_lead_id for job, _ in jobs.values() if job.delivery_lead_id
    }
    active_leads = (
        set(
            (
                await db.scalars(
                    select(User.id).where(
                        User.id.in_(lead_ids), User.is_active.is_(True)
                    )
                )
            ).all()
        )
        if lead_ids
        else set()
    )
    announced: dict[tuple[int, int], datetime] = {}
    for user_id, job_id, created_at in (
        await db.execute(
            select(
                Notification.user_id,
                Notification.related_entity_id,
                Notification.created_at,
            ).where(
                Notification.notification_type == NTYPE,
                Notification.related_entity_type == "job",
                Notification.related_entity_id.in_(sorted(jobs)),
                Notification.created_at >= since,
            )
        )
    ).all():
        key = (user_id, job_id)
        announced[key] = max(created_at, announced.get(key, created_at))

    hor: Optional[list[int]] = None
    created = 0
    for job_id, (actor, at, details) in latest.items():
        if job_id not in jobs:
            continue
        job, client_name = jobs[job_id]
        if job.delivery_lead_id not in active_leads and hor is None:
            hor = await _hor_ids(db)
        recipients = route_to_recipients(job.delivery_lead_id, active_leads, hor or [])
        reopened = isinstance(details, dict) and details.get("reopened") is True
        message = bell_message(
            title=display_title(job),
            client=client_name,
            opened_at=at if reopened else (job.opened_at or job.created_at or at),
            reopened=reopened,
        )
        for user_id in recipients:
            if user_id == actor:
                continue
            seen = announced.get((user_id, job_id))
            if seen is not None and seen >= at:
                continue
            row = await emit(
                db,
                user_id=user_id,
                title=TITLE,
                message=message,
                ntype=NTYPE,
                related_entity_type="job",
                related_entity_id=job_id,
                link=f"/jobs/{job_id}",
            )
            created += int(row is not None)
    return created


def _lead_text(names: list[str]) -> str:
    return (
        f"Prowadzi: {', '.join(names)}." if names else "Nikt jej jeszcze nie prowadzi."
    )


async def render(
    db: AsyncSession, rows: Iterable[Notification]
) -> Optional[tuple[str, str, str, list[int]]]:
    """(tytuł, treść, link, id wpisów w mailu) albo ``None`` (nic do wysłania).

    Wpis rekrutacji zamkniętej po otwarciu wypada z maila; jego id nie wraca,
    więc wołający zwalnia go bez stempla wysyłki.
    """
    rows = [row for row in rows if row.related_entity_id is not None]
    if not rows:
        return None
    open_ids = set(
        (
            await db.scalars(
                select(Job.id).where(
                    Job.id.in_({row.related_entity_id for row in rows}),
                    Job.status == JobStatus.published,
                )
            )
        ).all()
    )
    rows = [row for row in rows if row.related_entity_id in open_ids]
    if not rows:
        return None
    team = await recruiters_for_jobs(db, open_ids)
    lines = [
        f"{row.message} — "
        + _lead_text([p.name for p in working(team.get(row.related_entity_id, []))])
        for row in rows
    ]
    ids = [row.id for row in rows]
    if len(rows) == 1:
        return TITLE, lines[0], rows[0].link or LIST_LINK, ids
    shown = "\n".join(lines[:MAX_LISTED])
    rest = len(lines) - MAX_LISTED
    if rest > 0:
        shown += f"\n… i {rest} więcej — lista rekrutacji w NEXUSIE."
    return f"Nowe rekrutacje u Twoich klientów: {len(rows)}", shown, LIST_LINK, ids
