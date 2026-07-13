"""Cortex — API warstwy „central intelligence" (PR1: fact store + widoki).

- ``GET  /api/cortex/tech-map``   — mapa skill × derived-seniority (z fill-rate)
- ``GET  /api/cortex/coverage``   — jakość danych: fill-rates, świeżość, procesy
- ``GET  /api/cortex/unmatched-terms`` — kolejka kuracji taksonomii (admin)
- ``POST /api/cortex/admin/backfill-traffit`` (+ ``/status``) — backfill faktów
  z ``traffit_technologie`` (cała baza, bez LLM)

RBAC: widoki dla admin/head_of_recruitment/delivery_lead/tac (dane nazwiskowe
kandydatów — RODO gate jak w Insights); backfill i kuracja — admin only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, get_db, require_roles
from app.core.database import AsyncSessionLocal
from app.models.cortex import CortexUnmatchedTerm
from app.models.user import User, UserRole
from app.services.cortex import runs
from app.services.cortex.coverage import compute_coverage
from app.services.cortex.extractor_traffit import execute_run
from app.services.cortex.tech_map import compute_tech_map

logger = logging.getLogger(__name__)

router = APIRouter()

CortexUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.tac,
        )
    ),
]

# Referencje zadań w tle (fire-and-forget ``create_task`` gubi je pod GC).
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _run_backfill_task(run_id: int, limit: Optional[int]) -> None:
    """Wykonaj zarezerwowany run w osobnej sesji (przeżywa zamknięcie requestu)."""
    try:
        async with AsyncSessionLocal() as task_db:
            await execute_run(task_db, run_id, limit=limit)
    except Exception:  # noqa: BLE001 — run już oznaczony `failed` w execute_run
        logger.exception("[cortex] backfill task crashed (run_id=%s)", run_id)


@router.get("/tech-map")
async def tech_map(
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    source: Optional[str] = Query(
        default=None,
        pattern="^(traffit|cv_llm|screening)$",
        description="Ogranicz do jednego źródła faktów.",
    ),
    employment: Optional[str] = Query(
        default=None,
        pattern="^at_client$",
        description="`at_client` = tylko konsultanci obecnie u klientów.",
    ),
    min_count: int = Query(
        default=2,
        ge=1,
        le=100,
        description="Ukryj komórki z mniejszą liczbą kandydatów (szum).",
    ),
) -> dict[str, Any]:
    """Mapa technologiczna bazy: komórki (skill, derived-seniority) → liczność."""
    return await compute_tech_map(
        db, source=source, employment=employment, min_count=min_count
    )


@router.get("/coverage")
async def coverage(
    _user: CortexUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Jakość danych Cortexa: fill-rates, świeżość faktów, stan procesów."""
    return await compute_coverage(db)


@router.get("/unmatched-terms")
async def unmatched_terms(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    term_status: str = Query(
        default="new", alias="status", pattern="^(new|mapped|ignored|all)$"
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Kolejka kuracji taksonomii — najczęstsze tokeny spoza słownika."""
    q = select(CortexUnmatchedTerm).order_by(CortexUnmatchedTerm.occurrences.desc())
    if term_status != "all":
        q = q.where(CortexUnmatchedTerm.status == term_status)
    rows = (await db.execute(q.limit(limit))).scalars().all()
    return [
        {
            "term": row.term,
            "occurrences": row.occurrences,
            "status": row.status,
            "first_seen_at": (
                row.first_seen_at.isoformat() if row.first_seen_at else None
            ),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]


@router.post("/admin/backfill-traffit")
async def trigger_traffit_backfill(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Przetwórz co najwyżej N kandydatów (batch weryfikacyjny). "
        "Bez limitu = cała baza z niepustym traffit_technologie.",
    ),
) -> dict[str, Any]:
    """Odpal backfill faktów z Traffita w tle. Admin only.

    Single-flight jest atomowy: ``runs.create_run`` rezerwuje slot przez partial
    unique ``status='running'`` — zwraca ``None`` gdy inny run trwa (koniec
    TOCTOU z dawnej flagi in-memory). Sprzątamy najpierw osierocone runy.
    """
    await runs.reap_orphans(db)
    run_id = await runs.create_run(
        db, run_type="manual", triggered_by=getattr(_admin, "email", None)
    )
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backfill już trwa",
        )
    _spawn(_run_backfill_task(run_id, limit))
    return {"status": "started", "run_id": run_id, "limit": limit}


@router.get("/admin/backfill-traffit/status")
async def traffit_backfill_status(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Postęp ostatniego backfillu — z trwałego ``cortex_extraction_runs``
    (przeżywa restart kontenera, w przeciwieństwie do dawnego in-memory dict)."""
    run = await runs.latest_run(db)
    if run is None:
        return {
            "running": False,
            "status": "idle",
            "total": 0,
            "processed": 0,
            "facts_upserted": 0,
            "unmatched_tokens": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
        }
    stats = run.stats or {}
    return {
        "running": run.status == "running",
        "status": run.status,
        "run_id": run.id,
        "run_type": run.run_type,
        "triggered_by": run.triggered_by,
        "total": stats.get("total", 0),
        "processed": stats.get("processed", 0),
        "facts_upserted": stats.get("facts_upserted", 0),
        "unmatched_tokens": stats.get("unmatched_tokens", 0),
        "errors": stats.get("errors", 0),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "last_error": run.last_error,
    }
