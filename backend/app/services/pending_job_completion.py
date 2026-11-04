"""Rekrutacje do dokończenia i niedokończone formularze — pulpit (04.10.2026).

Od decyzji Artura z 04.10.2026 rekrutacja nigdy nie jest szkicem: utworzenie
= przekazanie do searchu = publikacja. Zostały dwie rodziny rekrutacji sprzed
tej zmiany, które pulpit „Czeka na Ciebie” pokazuje, dopóki ktoś ich nie
dokończy:

* ``legacy_draft`` — szkic (``status = draft``). Zamyka się sam po 7 dniach
  od wdrożenia (``services/legacy_draft_autoclose.py``) — ``autoclose_on``
  mówi kiedy.
* ``published_not_handed_off`` — opublikowana, ale nikt jej nie przekazał do
  searchu (``is_open = false``), spoza Traffita (archiwum Traffita ma
  ``is_open = false`` z definicji i nie jest pracą do dokończenia).

Każda pozycja niesie listę braków tą samą funkcją co przycisk „Przekaż do
searchu” (``job_readiness.job_handoff_blockers``).

Kto widzi: Delivery Lead — rekrutacje, w których jest DL-em albo które
założył; Head of Recruitment i admin — wszystkie; reszta — nic (``None``).

Lista ``unfinished_forms`` to niedokończone formularze „Nowa rekrutacja” tej
osoby leżące dłużej niż ``job_intake_forms.STALE_AFTER_DAYS`` dni.

Awaria liczenia nigdy nie kładzie pulpitu: savepoint + log + pusta lista.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import job_intake_forms
from app.services.job_readiness import job_handoff_blockers
from app.services.job_working_title import display_title

logger = logging.getLogger(__name__)

KIND_LEGACY_DRAFT = "legacy_draft"
KIND_NOT_HANDED_OFF = "published_not_handed_off"
MAX_ROWS = 50

# Kto widzi wszystkie rekrutacje do dokończenia.
_SEES_ALL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
)


@dataclass(frozen=True)
class PendingJob:
    job_id: int
    title: str
    client_name: Optional[str]
    kind: str
    created_at: datetime
    delivery_lead_name: Optional[str]
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingJobs:
    autoclose_on: Optional[date]
    items: list[PendingJob]


@dataclass(frozen=True)
class UnfinishedForm:
    id: int
    label: str
    client_name: Optional[str]
    updated_at: datetime


def sees_all(user: User) -> bool:
    return user.has_any_role(*_SEES_ALL_ROLES)


def sees_pending_jobs(user: User) -> bool:
    return sees_all(user) or user.has_role(UserRole.delivery_lead)


def pending_clause():
    """SQL: rekrutacja sprzed „rekrutacji bez szkiców”, którą trzeba dokończyć."""
    return or_(
        Job.status == JobStatus.draft,
        and_(
            Job.status == JobStatus.published,
            Job.is_open.is_(False),
            Job.external_source.is_distinct_from("traffit"),
        ),
    )


def _kind(job: Job) -> str:
    return KIND_LEGACY_DRAFT if job.status == JobStatus.draft else KIND_NOT_HANDED_OFF


async def autoclose_on(db: AsyncSession) -> Optional[date]:
    """Kiedy zamkną się stare szkice — ta sama funkcja co samo zamykanie."""
    from app.services.legacy_draft_autoclose import (  # noqa: PLC0415
        legacy_draft_autoclose_on,
    )

    return await legacy_draft_autoclose_on(db)


async def load_pending_jobs(db: AsyncSession, user: User) -> Optional[PendingJobs]:
    """Rekrutacje do dokończenia widoczne dla tej osoby; ``None`` = nic."""
    if not sees_pending_jobs(user):
        return None
    delivery_lead = aliased(User)
    stmt = (
        select(Job, Client.name, delivery_lead.name)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(delivery_lead, delivery_lead.id == Job.delivery_lead_id)
        .where(pending_clause())
        # Najnowsze na górze — świeżo przerwana praca jest najbliżej dokończenia.
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(MAX_ROWS)
    )
    if not sees_all(user):
        stmt = stmt.where(
            or_(Job.delivery_lead_id == user.id, Job.created_by == user.id)
        )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None
    items = [
        PendingJob(
            job_id=job.id,
            title=display_title(job),
            client_name=client_name,
            kind=_kind(job),
            created_at=job.created_at,
            delivery_lead_name=dl_name,
            missing=job_handoff_blockers(job),
        )
        for job, client_name, dl_name in rows
    ]
    has_drafts = any(item.kind == KIND_LEGACY_DRAFT for item in items)
    return PendingJobs(
        autoclose_on=await autoclose_on(db) if has_drafts else None,
        items=items,
    )


async def load_unfinished_forms(
    db: AsyncSession, user: User, *, now: datetime
) -> list[UnfinishedForm]:
    """Moje formularze „Nowa rekrutacja” leżące dłużej niż 2 dni."""
    older_than = now - timedelta(days=job_intake_forms.STALE_AFTER_DAYS)
    return [
        UnfinishedForm(
            id=form.id,
            label=form.label,
            client_name=form.client_name,
            updated_at=form.updated_at,
        )
        for form in await job_intake_forms.list_forms(
            db, user.id, older_than=older_than
        )
    ]


async def load_pending_jobs_safely(
    db: AsyncSession, user: User
) -> Optional[PendingJobs]:
    try:
        async with db.begin_nested():
            return await load_pending_jobs(db, user)
    except Exception:  # noqa: BLE001
        logger.exception("pending_job_completion: nie udało się policzyć rekrutacji")
        return None


async def load_unfinished_forms_safely(
    db: AsyncSession, user: User, *, now: datetime
) -> list[UnfinishedForm]:
    try:
        async with db.begin_nested():
            return await load_unfinished_forms(db, user, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("pending_job_completion: nie udało się policzyć formularzy")
        return []


async def digest_counts(db: AsyncSession) -> dict[int, int]:
    """Poranny skrót: ile rekrutacji do dokończenia widzi każda osoba.

    Ta sama reguła widoczności co panel (``load_pending_jobs``), liczona dla
    wszystkich aktywnych adminów, Head of Recruitment i Delivery Leadów.
    """
    rows = (
        await db.execute(
            select(Job.id, Job.delivery_lead_id, Job.created_by).where(pending_clause())
        )
    ).all()
    if not rows:
        return {}
    roles = (*_SEES_ALL_ROLES, UserRole.delivery_lead)
    users = (
        await db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role.in_(roles),
                    *(User.roles.contains([r.value]) for r in roles),
                ),
            )
        )
    ).all()
    counts: dict[int, int] = {}
    for user in users:
        if sees_all(user):
            count = len(rows)
        elif user.has_role(UserRole.delivery_lead):
            count = sum(
                1 for row in rows if user.id in (row.delivery_lead_id, row.created_by)
            )
        else:
            count = 0
        if count:
            counts[user.id] = count
    return counts


def pending_jobs_phrase(count: int) -> str:
    """„1 rekrutacja czeka / 3 rekrutacje czekają / 5 rekrutacji czeka na dokończenie”."""
    if count == 1:
        return "1 rekrutacja czeka na dokończenie"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} rekrutacje czekają na dokończenie"
    return f"{count} rekrutacji czeka na dokończenie"


__all__ = [
    "KIND_LEGACY_DRAFT",
    "KIND_NOT_HANDED_OFF",
    "PendingJob",
    "PendingJobs",
    "UnfinishedForm",
    "autoclose_on",
    "digest_counts",
    "load_pending_jobs",
    "load_pending_jobs_safely",
    "load_unfinished_forms",
    "load_unfinished_forms_safely",
    "pending_clause",
    "pending_jobs_phrase",
    "sees_pending_jobs",
]
