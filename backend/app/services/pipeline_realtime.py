"""Live kanban: tell the rest of a recruitment's team that its board changed.

A move made by one recruiter used to stay invisible to a colleague looking at
the same board until they reloaded it. After a committed change of the board
(move, bulk move, verification decision, bulk add, removal) the handler calls
:func:`broadcast_pipeline_changed`; the front debounces the event per job and
re-reads the board. The payload carries the job id only — never a candidate —
and the WebSocket manager drops it for users without the pipeline section
(``user_can_receive_realtime_event``).

Best-effort: a failed member lookup or a dead socket never fails the request
that already committed.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ws import notify_user
from app.services.job_membership import list_job_member_ids

logger = logging.getLogger(__name__)

PIPELINE_CHANGED_EVENT = "pipeline_changed"


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
            member_ids = await list_job_member_ids(db, job_id)
    except Exception:  # noqa: BLE001 — realtime never breaks a committed change
        logger.warning("pipeline_changed: member lookup failed job=%s", job_id)
        return
    event = {"type": PIPELINE_CHANGED_EVENT, "data": {"job_id": job_id}}
    for uid in member_ids:
        if uid == actor_id:
            continue
        try:
            await notify_user(uid, event)
        except Exception:  # noqa: BLE001 — one dead socket must not stop the rest
            continue
