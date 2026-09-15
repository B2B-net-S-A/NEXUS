"""HTTP fallback for presence / currently-viewing state.

Serves an initial snapshot of active viewers for a resource so the frontend
can render immediately, before the first WebSocket `presence:update` arrives.

Source of truth is the in-memory ConnectionManager in `app.api.ws`.
"""

from typing import Literal

from fastapi import APIRouter, Depends

from app.api.recruitment_access import RecruitmentReadAccess
from app.api.section_access import require_section_access_any_read
from app.api.ws import manager
from app.services.section_permissions import ProductSection

# Lustro bramki WebSocketu (`presence_subscribe_allowed`): obecność widać z
# profilu kandydata (Sourcing) i z rekrutacji (Pipeline) — ale nie bez żadnej
# z tych sekcji (F02, audyt 14.09.2026).
router = APIRouter(
    prefix="/api/presence",
    tags=["presence"],
    dependencies=[
        Depends(
            require_section_access_any_read(
                ProductSection.sourcing, ProductSection.pipeline
            )
        )
    ],
)


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
