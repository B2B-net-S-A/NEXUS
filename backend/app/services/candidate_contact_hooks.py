"""Fail-closed ingress hooks for the global candidate contact queue.

The domain service deliberately contains no knowledge of HTTP routes or
external feature flags.  Every existing write path calls these helpers instead
so the dormant-by-default rollout has exactly zero contact-queue writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate_contact import CandidateContactCase
from app.models.job_shortlist import JobShortlistEntry
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.candidate_contact import (
    ContactCaseSummaryResponse,
    ContactOwnerSummary,
)

_TERMINAL_PIPELINE_STAGES = {
    PipelineStage.hired,
    PipelineStage.rejected,
    PipelineStage.withdrawn,
}


async def has_active_contact_trigger(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    exclude_shortlist_entry_id: Optional[int] = None,
) -> bool:
    """Whether shortlist outreach or the latest pipeline stage keeps the link open."""

    shortlist_query = select(JobShortlistEntry.id).where(
        JobShortlistEntry.candidate_id == candidate_id,
        JobShortlistEntry.job_id == job_id,
        JobShortlistEntry.outreach_status == "do_kontaktu",
    )
    if exclude_shortlist_entry_id is not None:
        shortlist_query = shortlist_query.where(
            JobShortlistEntry.id != exclude_shortlist_entry_id
        )
    if await db.scalar(shortlist_query.limit(1)) is not None:
        return True
    latest_stage = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    return (
        latest_stage is not None and latest_stage.stage not in _TERMINAL_PIPELINE_STAGES
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def automatic_contact_intake_allowed(occurred_at: Optional[datetime]) -> bool:
    """Return whether an automatic source row belongs to the live cutover.

    An explicit activation timestamp is required.  This is intentional:
    accidentally enabling the feature without a cutover cannot reserve the
    historical pipeline or consume all queue slots.
    """

    if not settings.CANDIDATE_CONTACT_ENABLED:
        return False
    activation_at = settings.CANDIDATE_CONTACT_ACTIVATION_AT
    if activation_at is None:
        return False
    moment = _aware_utc(occurred_at or datetime.now(timezone.utc))
    return moment >= _aware_utc(activation_at)


async def maybe_ensure_contact_opportunity(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    source: str,
    source_external_ref: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    allow_declined_reopen: bool = False,
):
    """Create/extend one global case only when the cutover gate allows it.

    ``allow_declined_reopen`` must stay ``False`` for every automatic ingress;
    pass it only from a caller that carries a deliberate recruiter decision to
    approach a candidate who already declined this job.
    """

    if not automatic_contact_intake_allowed(occurred_at):
        return None
    if source == "traffit" and not settings.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED:
        return None
    from app.services.candidate_contact import ensure_contact_opportunity

    return await ensure_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        source=source,
        source_external_ref=source_external_ref,
        occurred_at=occurred_at,
        assign_if_possible=settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED,
        allow_declined_reopen=allow_declined_reopen,
    )


async def maybe_sync_calendar_handoff(
    db: AsyncSession,
    *,
    candidate_id: Optional[int],
    job_id: Optional[int],
    event_id: int,
    scheduled: bool,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
) -> None:
    """Synchronise a qualifying calendar event when the module is enabled."""

    if not settings.CANDIDATE_CONTACT_ENABLED or candidate_id is None or job_id is None:
        return
    from app.services.candidate_contact import sync_calendar_handoff

    await sync_calendar_handoff(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        event_id=event_id,
        scheduled=scheduled,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
    )


async def maybe_remove_calendar_handoff(
    db: AsyncSession,
    *,
    candidate_id: Optional[int],
    job_id: Optional[int],
    event_id: int,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
) -> None:
    """Remove one handoff without hiding another qualifying meeting.

    A candidate/job may have more than one screening or interview.  Cancelling
    or deleting one of them only reopens the opportunity when no other
    scheduled/completed handoff remains.
    """

    if not settings.CANDIDATE_CONTACT_ENABLED or candidate_id is None or job_id is None:
        return
    replacement_event_id = await db.scalar(
        select(CalendarEvent.id)
        .where(
            CalendarEvent.id != event_id,
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type.in_((EventType.screening, EventType.interview)),
            CalendarEvent.status.in_((EventStatus.scheduled, EventStatus.completed)),
        )
        .order_by(CalendarEvent.start_time, CalendarEvent.id)
        .limit(1)
    )
    await maybe_sync_calendar_handoff(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        event_id=replacement_event_id or event_id,
        scheduled=replacement_event_id is not None,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
    )


async def maybe_close_contact_opportunity(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    reason: str,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
    source: str = "nexus",
    source_external_ref: Optional[str] = None,
):
    """Close one job link without affecting the candidate's other jobs."""

    if not settings.CANDIDATE_CONTACT_ENABLED:
        return None
    if source == "traffit" and (
        not settings.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED
        or not automatic_contact_intake_allowed(occurred_at)
    ):
        return None
    from app.services.candidate_contact import close_contact_opportunity

    return await close_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        actor_user_id=actor_user_id,
        reason=reason,
        occurred_at=occurred_at,
        source=source if source == "traffit" else None,
        source_external_ref=(source_external_ref if source == "traffit" else None),
    )


async def maybe_close_job_contact_opportunities(
    db: AsyncSession,
    *,
    job_id: int,
    reason: str,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
):
    """Close every contact link before a job is closed or deleted."""

    if not settings.CANDIDATE_CONTACT_ENABLED:
        return []
    from app.services.candidate_contact import close_job_contact_opportunities

    return await close_job_contact_opportunities(
        db,
        job_id=job_id,
        reason=reason,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
    )


async def load_contact_case_summaries(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, ContactCaseSummaryResponse]:
    """Batch-load bounded badge data without N+1 queries.

    Callers already enforce candidate/job visibility; the summary carries no
    recruitment titles or other cross-job data.
    """

    if not settings.CANDIDATE_CONTACT_ENABLED or not candidate_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(CandidateContactCase).where(
                    CandidateContactCase.candidate_id.in_(set(candidate_ids))
                )
            )
        )
        .scalars()
        .all()
    )
    owner_ids = {row.owner_user_id for row in rows if row.owner_user_id is not None}
    owners = (
        {
            owner.id: owner
            for owner in (
                (await db.execute(select(User).where(User.id.in_(owner_ids))))
                .scalars()
                .all()
            )
        }
        if owner_ids
        else {}
    )
    output: dict[int, ContactCaseSummaryResponse] = {}
    for row in rows:
        owner = owners.get(row.owner_user_id)
        output[row.candidate_id] = ContactCaseSummaryResponse(
            id=row.id,
            status=row.state,
            owner=(
                ContactOwnerSummary(id=owner.id, name=owner.name)
                if owner is not None
                else None
            ),
            due_at=row.due_at,
            callback_at=row.due_at if row.state == "callback_due" else None,
            attempts_in_cycle=row.attempt_count,
            version=row.version,
        )
    return output


__all__ = [
    "automatic_contact_intake_allowed",
    "has_active_contact_trigger",
    "load_contact_case_summaries",
    "maybe_close_contact_opportunity",
    "maybe_close_job_contact_opportunities",
    "maybe_ensure_contact_opportunity",
    "maybe_remove_calendar_handoff",
    "maybe_sync_calendar_handoff",
]
