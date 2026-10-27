"""Live kanban: tell the rest of a recruitment's team that its board changed.

A move made by one recruiter used to stay invisible to a colleague looking at
the same board until they reloaded it. After a committed change of the board
(move, bulk move, verification decision, bulk add, removal) the handler calls
:func:`broadcast_pipeline_changed`; the front debounces the event per job and
re-reads the board. The payload carries the job id and the job's Delivery Lead
id — never a candidate — and the WebSocket manager drops it for users without
the pipeline section (``user_can_receive_realtime_event``).

Recipients (27.10.2026): the recruitment's team without admins outside it,
plus whoever has the job open right now (presence channel ``job:{id}``) and
may read its board (``ensure_job_read_access`` — presence itself is only a
role check, the board is members-only, P1-PIPE-01).
Until then every admin got every card move in the company and re-read their
queues after each one. ``delivery_lead_id`` lets the front refresh the
"to send" queue only for that job's Delivery Lead
(``frontend/src/lib/pipeline-changed-refresh.ts``).

Best-effort: a failed member lookup or a dead socket never fails the request
that already committed.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import ensure_job_read_access
from app.api.ws import manager, notify_user
from app.models.job import Job
from app.models.user import User
from app.services.job_membership import list_job_member_ids

logger = logging.getLogger(__name__)

PIPELINE_CHANGED_EVENT = "pipeline_changed"


async def _watchers_who_may_read(
    db: AsyncSession, job_id: int, viewer_ids: set[int]
) -> set[int]:
    """Viewers outside the team who pass the board's own read guard."""
    allowed: set[int] = set()
    for uid in viewer_ids:
        user = await db.get(User, uid)
        if user is None or not user.is_active:
            continue
        try:
            await ensure_job_read_access(db, user, job_id)
        except HTTPException:
            continue
        allowed.add(uid)
    return allowed


async def broadcast_pipeline_changed(
    db: AsyncSession, job_id: int, actor_id: int | None
) -> None:
    """Best-effort: po zatwierdzonej zmianie tablicy powiadom resztę zespołu.

    ``actor_id`` must be read BEFORE the commit — objects loaded through the
    request session (``current_user`` included) expire on commit.
    """
    try:
        # Savepoint: a failed lookup rolls back only itself, so the request
        # session stays usable (and its loaded objects unexpired) for the
        # handler's remaining post-commit work and response.
        async with db.begin_nested():
            member_ids = await list_job_member_ids(db, job_id, include_admins=False)
            job = await db.get(Job, job_id)
            watchers = await _watchers_who_may_read(
                db, job_id, manager.viewer_ids("job", job_id) - set(member_ids)
            )
    except Exception:  # noqa: BLE001 — realtime never breaks a committed change
        logger.warning("pipeline_changed: member lookup failed job=%s", job_id)
        return
    event = {
        "type": PIPELINE_CHANGED_EVENT,
        "data": {
            "job_id": job_id,
            "delivery_lead_id": job.delivery_lead_id if job else None,
        },
    }
    # Admin (and anyone else allowed) outside the team looking at this board.
    recipients = sorted(set(member_ids) | watchers)
    for uid in recipients:
        if uid == actor_id:
            continue
        try:
            await notify_user(uid, event)
        except Exception:  # noqa: BLE001 — one dead socket must not stop the rest
            continue
