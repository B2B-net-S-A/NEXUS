"""Admin trigger dla cyklicznej ekstrakcji notatek (``notes_insights_sync``).

- ``POST /api/admin/notes-insights/sync`` — odpal bieg teraz (fire-and-forget;
  postęp w ``GET /api/admin/traffit/sync/status`` — wiersz ``notes_insights``
  w ``traffit_sync_state``, ten endpoint czyta wszystkie fazy).

RBAC: admin JWT. Świadomie bez scope'u konta serwisowego na start — pętla
dzienna obsługuje rutynę sama, trigger jest do aktywacji i nadganiania
zaległości (operator odpala kilka razy, każdy bieg zjada kolejny budżet).
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 + slowapi #579
# zamienia Annotated guardy w wymagane parametry QUERY (trap z CLAUDE.md).

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.rate_limit import limiter
from app.tasks.notes_insights_sync import run_and_persist, sync_is_running

router = APIRouter()


@router.post("/sync")
@limiter.limit("10/minute")
async def trigger_notes_insights_sync(
    request: Request,
    _admin: AdminUser,
) -> Dict[str, Any]:
    """Uruchom bieg ekstrakcji w tle. ``request`` — wymóg slowapi."""
    if not settings.NOTES_INSIGHTS_SYNC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notes insights sync disabled (NOTES_INSIGHTS_SYNC_ENABLED=false)",
        )
    if sync_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A notes insights run is already in progress",
        )

    asyncio.create_task(run_and_persist())
    return {
        "status": "started",
        "batch_limit": settings.NOTES_INSIGHTS_SYNC_BATCH_LIMIT,
        "status_surface": "/api/admin/traffit/sync/status (phase=notes_insights)",
    }
