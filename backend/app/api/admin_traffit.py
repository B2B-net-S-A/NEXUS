"""Admin endpoints for the scheduled Traffit → Nexus sync.

- ``POST /api/admin/traffit/sync?mode=delta|full`` — kick a run now (returns
  immediately; the import runs in the background). Used to activate / verify
  without waiting for the 02:00 UTC window.
- ``GET  /api/admin/traffit/sync/status`` — watermark + last-run stats per phase.

RBAC: admin z JWT **albo** konto serwisowe z odpowiednim scope'em
(``traffit:sync`` / ``traffit:read``) w nagłówku ``X-API-Key``.

To są endpointy odpalane operacyjnie poza przeglądarką — dokumentacja aktywacji
w CLAUDE.md każe „odpalić ``POST /api/admin/traffit/sync``", a pełny reconcile
domyka się przez kilkukrotne wywołanie. Robienie tego tokenem wyklikanym
w przeglądarce znaczyło, że automatyzacja podszywa się pod człowieka
poświadczeniem, które i tak umiera po 8 h. Scope'y są rozdzielone celowo:
klucz monitoringu czytający status nie ma prawa uruchomić pełnego importu.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia adnotacje
# FastAPI w ForwardRef, a `@limiter.limit` (slowapi #579) rozwiązuje je już
# w SWOICH globalsach, więc `TraffitSyncCaller` przestaje być rozpoznawany
# i ląduje jako wymagany parametr QUERY. Ten sam trap co w
# `candidate_activity_summary.py`.

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TraffitReadCaller, TraffitSyncCaller
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.tasks.traffit_sync import (
    run_traffit_sync,
    sync_is_running,
    validate_phases,
)

router = APIRouter()


def _service_rate_limit() -> str:
    """Limit czytany przy KAŻDYM requeście, nie w chwili importu modułu.

    slowapi przyjmuje tu callable, więc zmiana ``SERVICE_ACCOUNT_RATE_LIMIT``
    w Coolify działa po restarcie procesu, a nie dopiero po przebudowie obrazu.
    """
    return settings.SERVICE_ACCOUNT_RATE_LIMIT


@router.post("/sync")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_sync(
    request: Request,
    _caller: TraffitSyncCaller,
    mode: str = Query("delta", pattern="^(delta|full)$"),
    phases: Optional[str] = Query(
        None,
        description=(
            "Comma-separated phase names to run INSTEAD of the whole plan, "
            "e.g. `candidate_files,candidates_cv`. A partial run deliberately "
            "does NOT advance the __daily__/__full__ markers."
        ),
    ),
) -> Dict[str, Any]:
    """Trigger a Traffit sync run in the background. Admin JWT or ``traffit:sync``.

    ``request`` jest w sygnaturze, bo wymaga go slowapi (kubełek limitu per IP).
    """
    if not settings.TRAFFIT_SYNC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffit sync disabled (TRAFFIT_SYNC_ENABLED=false)",
        )
    if sync_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Traffit sync is already running",
        )

    # Walidacja MUSI się wydarzyć tutaj, przed `create_task`. Bieg jest
    # fire-and-forget, więc `ValueError` rzucony w tasku poleciałby wyłącznie do
    # logów, a wywołujący dostałby 200 "started" za literówkę w nazwie fazy.
    #
    # Parsowanie po stronie ciała funkcji, nie przez `Annotated`/typ listy —
    # ten moduł ma `@limiter.limit`, a slowapi (#579) w połączeniu z PEP 563
    # potrafi wyprowadzić takie parametry jako WYMAGANE query i zwracać 422 na
    # poprawnym wywołaniu. Ten sam trap opisuje CLAUDE.md.
    selected: Optional[list[str]] = None
    if phases is not None:
        selected = [p.strip() for p in phases.split(",") if p.strip()]
        try:
            validate_phases(selected)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    # Fire-and-forget: a full reconcile can take minutes/hours; don't block the
    # request. Progress is observable via GET /sync/status.
    asyncio.create_task(run_traffit_sync(mode, phases=selected))
    out: Dict[str, Any] = {"status": "started", "mode": mode}
    if selected is not None:
        out["phases"] = selected
        out["markers_advanced"] = False
    return out


@router.get("/sync/status")
@limiter.limit(_service_rate_limit)
async def traffit_sync_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Current watermark + last-run stats for every phase + scheduler markers."""
    rows = await db.execute(
        text(
            "SELECT phase, last_synced_at, last_run_started_at, "
            "last_run_finished_at, last_status, stats, cursor_at, cursor_payload "
            "FROM traffit_sync_state ORDER BY phase"
        )
    )
    states = [
        {
            "phase": r.phase,
            "last_synced_at": r.last_synced_at.isoformat()
            if r.last_synced_at
            else None,
            "last_run_started_at": r.last_run_started_at.isoformat()
            if r.last_run_started_at
            else None,
            "last_run_finished_at": r.last_run_finished_at.isoformat()
            if r.last_run_finished_at
            else None,
            "last_status": r.last_status,
            "stats": r.stats,
            # Resume cursor (Stage 3) — non-null while a phase (e.g.
            # candidate_activities) is mid-catch-up; watch cursor.page advance
            # across runs to see resumable pagination working, NULL after a
            # full pass.
            "cursor_at": r.cursor_at.isoformat() if r.cursor_at else None,
            "cursor": r.cursor_payload,
        }
        for r in rows
    ]
    # Roll the parked rows up to the top level. Quarantine only works if
    # somebody sees it: a row that stops blocking the watermark but stays buried
    # three levels deep in a per-phase stats blob has simply been forgotten with
    # extra steps. This is the list an operator has to act on.
    quarantined: list[dict[str, Any]] = []
    for state in states:
        stats = state["stats"] or {}
        if not isinstance(stats, dict):
            continue
        attempts = stats.get("quarantine") or {}
        for ref in stats.get("quarantined") or []:
            quarantined.append(
                {
                    "phase": state["phase"],
                    "ref": ref,
                    "attempts": attempts.get(ref),
                    "last_seen": state["last_run_finished_at"],
                }
            )

    return {
        "enabled": settings.TRAFFIT_SYNC_ENABLED,
        "running": sync_is_running(),
        "max_row_attempts": settings.TRAFFIT_MAX_ROW_ATTEMPTS,
        "quarantined": quarantined,
        "states": states,
    }
