"""HTTP fallback for presence / currently-viewing state.

Serves an initial snapshot of active viewers for a resource so the frontend
can render immediately, before the first WebSocket `presence:update` arrives.

Source of truth is the in-memory ConnectionManager in `app.api.ws`.
"""

from typing import Literal

from fastapi import APIRouter

from app.api.recruitment_access import RecruitmentReadAccess
from app.api.ws import manager

router = APIRouter(prefix="/api/presence", tags=["presence"])


ResourceType = Literal["candidate", "job"]


@router.get("/{resource_type}/{resource_id}/viewers")
async def get_viewers(
    resource_type: ResourceType,
    resource_id: int,
    current_user: RecruitmentReadAccess,
) -> dict:
    """Return a snapshot of who is currently viewing a candidate or job page.

    P1.3: gated to internal operational roles (viewer excluded), matching the
    WS presence subscribe gate. The payload no longer carries viewer emails.
    """
    viewers = manager.get_viewers(resource_type, resource_id)
    return {"viewers": viewers}
