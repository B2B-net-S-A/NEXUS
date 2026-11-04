"""Dziennik zdarzeń CPro, wyłączniki i pasek na rekrutacji (02.11.2026).

* ``GET /api/cpro/log`` — co przyszło, co zrobił NEXUS, czego nie umiał;
* ``PUT /api/cpro/rules`` — wyłączniki reguł: Head of Recruitment i admin;
* ``GET /api/jobs/{id}/cpro-events`` — pasek nad Tablicą.

Reguła: ``docs/claude/integracje/cpro-maile-nordei.md``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje w czasie rejestracji trasy.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import get_db
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.models.cpro_mail import CproMailEvent
from app.models.job import Job, JobStatus
from app.models.m365 import Email, M365Connection
from app.models.user import User, UserRole
from app.services import cpro_mail, cpro_mail_parse
from app.services.board_stage_badges import cpro_enabled_for_client
from app.services.job_closed_notices import CLOSE_REASON_LABELS

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

LOG_LIMIT = 200
BANNER_REJECTED_DAYS = 7
BANNER_REJECTED_MAX = 5
MAILBOX_STALE_AFTER = timedelta(hours=1)
MAILBOX_SEEN_DAYS = 30


class CproRulesIn(BaseModel):
    closed: Optional[bool] = None
    rejected: Optional[bool] = None
    interview: Optional[bool] = None


def _can_edit_rules(user: User) -> bool:
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


def _ensure_can_read(user: User) -> None:
    if not user.has_any_role(
        UserRole.admin, UserRole.head_of_recruitment, UserRole.delivery_lead
    ):
        raise HTTPException(
            status_code=403,
            detail="Dziennik CPro widzą Delivery Lead, Head of Recruitment i admin.",
        )


async def _mailboxes(db: AsyncSession, now: datetime) -> list[dict]:
    since = now - timedelta(days=MAILBOX_SEEN_DAYS)
    rows = (
        await db.execute(
            select(User.name, M365Connection.last_sync_at, M365Connection.is_active)
            .join(M365Connection, M365Connection.user_id == User.id)
            .where(
                User.id.in_(
                    select(Email.user_id).where(
                        func.lower(Email.from_address) == cpro_mail_parse.SENDER,
                        Email.received_at >= since,
                    )
                )
            )
            .order_by(User.name)
        )
    ).all()
    return [
        {
            "name": name,
            "last_sync_at": synced.isoformat() if synced else None,
            "stale": not active or synced is None or now - synced > MAILBOX_STALE_AFTER,
        }
        for name, synced, active in rows
    ]


@router.get("/cpro/log")
async def get_cpro_log(
    user: CandidatePIIAccess,
    outcome: Optional[str] = Query(default=None, pattern="^manual$"),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_read(user)
    now = datetime.now(timezone.utc)
    grouped = (
        await db.execute(
            select(
                CproMailEvent.kind,
                CproMailEvent.outcome,
                func.count(func.distinct(CproMailEvent.request_number)),
                func.count(),
            ).group_by(CproMailEvent.kind, CproMailEvent.outcome)
        )
    ).all()
    closed = sum(req for kind, _o, req, _n in grouped if kind == "closed")
    rejected = sum(n for kind, _o, _r, n in grouped if kind == "rejected")
    interview = sum(n for kind, _o, _r, n in grouped if kind == "interview")
    manual = sum(n for _k, out, _r, n in grouped if out == cpro_mail.OUTCOME_MANUAL)

    query = (
        select(CproMailEvent, Job.title, Job.working_title)
        .outerjoin(Job, Job.id == CproMailEvent.job_id)
        .order_by(CproMailEvent.received_at.desc(), CproMailEvent.id.desc())
        .limit(LOG_LIMIT)
    )
    if outcome:
        query = query.where(CproMailEvent.outcome == outcome)
    rows = (await db.execute(query)).all()
    return {
        "since": settings.CPRO_MAIL_SINCE,
        "enabled": settings.CPRO_MAIL_ENABLED,
        "can_edit": _can_edit_rules(user),
        "rules": await cpro_mail.load_rules(db),
        "counts": {
            "closed": closed,
            "rejected": rejected,
            "interview": interview,
            "manual": manual,
        },
        "mailboxes": await _mailboxes(db, now),
        "rows": [
            {
                "id": event.id,
                "at": event.received_at.isoformat(),
                "kind": event.kind,
                "request": event.request_number,
                "job_id": event.job_id,
                "job_title": working_title or title,
                "candidate_id": event.candidate_id,
                "person": event.person,
                "detail": event.reason,
                "outcome": event.outcome,
                "outcome_text": event.outcome_text,
            }
            for event, title, working_title in rows
        ],
    }


@router.put("/cpro/rules")
async def put_cpro_rules(
    body: CproRulesIn,
    user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    if not _can_edit_rules(user):
        raise HTTPException(
            status_code=403,
            detail="Reguły CPro zmienia Head of Recruitment albo admin.",
        )
    changes = body.model_dump(exclude_none=True)
    rules = await cpro_mail.save_rules(db, changes, actor_id=user.id)
    await db.commit()
    return {"rules": rules}


@router.get("/jobs/{job_id}/cpro-events")
async def get_job_cpro_events(
    job_id: int,
    user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    await ensure_job_read_access(db, user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    empty = {"closed": None, "rejected": [], "rejected_more": 0}
    if not job.client_reference or not cpro_enabled_for_client(job.client_id):
        return empty
    closed = None
    if job.status == JobStatus.closed:
        event = await db.scalar(
            select(CproMailEvent)
            .where(
                CproMailEvent.kind == cpro_mail_parse.KIND_CLOSED,
                CproMailEvent.request_number == job.client_reference,
                CproMailEvent.outcome == cpro_mail.OUTCOME_DONE,
            )
            .order_by(CproMailEvent.received_at.desc())
            .limit(1)
        )
        if event is not None:
            reason = getattr(job.close_reason, "value", job.close_reason)
            closed = {
                "at": event.received_at.isoformat(),
                "request": event.request_number,
                "cpro_reason": event.reason,
                "nexus_reason": CLOSE_REASON_LABELS.get(reason, reason),
                "notified": event.notified,
            }
    since = datetime.now(timezone.utc) - timedelta(days=BANNER_REJECTED_DAYS)
    rejected_rows = (
        await db.scalars(
            select(CproMailEvent)
            .where(
                CproMailEvent.kind == cpro_mail_parse.KIND_REJECTED,
                CproMailEvent.request_number == job.client_reference,
                CproMailEvent.outcome == cpro_mail.OUTCOME_DONE,
                CproMailEvent.candidate_id.is_not(None),
                CproMailEvent.created_at >= since,
            )
            .order_by(CproMailEvent.received_at.desc())
        )
    ).all()
    return {
        "closed": closed,
        "rejected": [
            {
                "at": row.received_at.isoformat(),
                "person": row.person,
                "reason": row.reason,
                "candidate_id": row.candidate_id,
            }
            for row in rejected_rows[:BANNER_REJECTED_MAX]
        ],
        "rejected_more": max(0, len(rejected_rows) - BANNER_REJECTED_MAX),
    }
